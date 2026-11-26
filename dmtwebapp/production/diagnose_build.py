"""Isolated staging-only diagnostic of a real Vite build; no deployment or DB writes.
Logs are private, bounded, and contain no raw project output in the system journal.
"""
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,threading,time,uuid
from pathlib import Path
from worker import BASE,CACHE,IMAGE,inspect_and_extract,inspect,verify,detect_embedded,profile,cache_hit

LIMIT=4*1024*1024
KEY='b32e7103033013920a04862de048d487ea5f932226d0628321b309a459deef1f'
NODE=r"""
import fs from 'node:fs';
import {performance} from 'node:perf_hooks';
const begin=performance.now();
const read=p=>{try{return fs.readFileSync(p,'utf8').trim()}catch{return null}};
const emit=(event,extra={})=>console.log('DMT_DIAG '+JSON.stringify({event,ms:Math.round(performance.now()-begin),...extra}));
let transformed=0;
function snapshot(){
 const m=process.memoryUsage(),cpu=process.cpuUsage();
 return {rss:m.rss,heap:m.heapUsed,cpu_user_us:cpu.user,cpu_system_us:cpu.system,
  memory_current:read('/sys/fs/cgroup/memory.current'),memory_events:read('/sys/fs/cgroup/memory.events'),
  cpu_stat:read('/sys/fs/cgroup/cpu.stat'),io_pressure:read('/sys/fs/cgroup/io.pressure'),
  memory_pressure:read('/sys/fs/cgroup/memory.pressure'),transformed};
}
emit('node_start',snapshot());
const timer=setInterval(()=>emit('heartbeat',snapshot()),10000);timer.unref();
try{
 emit('vite_import_start');
 const {build}=await import('vite');
 emit('vite_import_done',snapshot());
 const diag={name:'dmt-diagnostic',enforce:'pre',
  configResolved(){emit('config_resolved',snapshot())},
  buildStart(){emit('build_start',snapshot())},
  transform(){transformed++;if(transformed%100===0)emit('transform_progress',{transformed})},
  buildEnd(err){emit('build_end',{failed:!!err,...snapshot()})},
  renderStart(){emit('render_start',snapshot())},
  generateBundle(){emit('generate_bundle',snapshot())},
  writeBundle(){emit('write_bundle',snapshot())},
  closeBundle(){emit('close_bundle',snapshot())}};
 emit('vite_build_call');
 await build({base:'./',cacheDir:'/tmp/vite-cache',logLevel:'info',clearScreen:false,
  plugins:[diag],build:{reportCompressedSize:false}});
 emit('vite_build_done',snapshot());
}catch(e){emit('vite_error',{name:e?.name,code:typeof e?.code==='string'?e.code:null,...snapshot()});console.error(e);process.exitCode=1}
finally{clearInterval(timer)}
"""
def out(event,**kw):
    print('DIAG_HOST '+json.dumps({'event':event,'time':time.time(),**kw},separators=(',',':')),flush=True)
def read(path):
    try:return Path(path).read_text().strip()
    except OSError:return None
def host_sample(start,cg=None):
    mem=read('/proc/meminfo') or ''
    vals={k:int(v) for k,v in re.findall(r'^(MemAvailable|SwapFree|SwapTotal):\s+(\d+)',mem,re.M)}
    data={'elapsed':round(time.monotonic()-start,2),'cpu':(read('/proc/stat') or '').splitlines()[:1],
          'memory_kb':vals,'load':read('/proc/loadavg'),'free_disk':shutil.disk_usage(BASE).free,
          'pressure':{k:read('/proc/pressure/'+k) for k in ('cpu','memory','io')}}
    if cg:
        data['cgroup']={k:read(cg/k) for k in ('cpu.stat','memory.current','memory.peak','memory.events','memory.swap.current','io.stat','io.pressure','memory.pressure')}
    out('sample',**data)
def state(name):
    try:
        r=subprocess.run(['/usr/bin/docker','inspect','--format','{{json .State}}',name],capture_output=True,text=True,timeout=12)
        if r.returncode:return None
        v=json.loads(r.stdout)
        return {k:v.get(k) for k in ('Status','Running','OOMKilled','Dead','Pid','ExitCode','StartedAt','FinishedAt')}
    except (ValueError,subprocess.TimeoutExpired):return None
def run(zip_path,log_dir):
    if os.getuid()==0:raise RuntimeError('NON_ROOT_REQUIRED')
    log_dir.mkdir(mode=0o700,exist_ok=False)
    os.chmod(log_dir,0o700)
    with tempfile.TemporaryDirectory(prefix='diag-',dir=BASE/'work') as tmp:
        root=inspect_and_extract(zip_path,Path(tmp));plan=inspect(root);config=detect_embedded(root,plan,{'mode':'none'})
        deps=profile(plan['dependencies'],root)
        cache=cache_hit(CACHE/'auto',deps,IMAGE)
        if not cache or cache.name!=KEY:raise RuntimeError('EXACT_FIREBASE_CACHE_REQUIRED')
        out('input',zip_sha256=hashlib.sha256(zip_path.read_bytes()).hexdigest(),database=config.get('mode'),cache=cache.name)
        (root/'node_modules').mkdir();uid,gid=os.getuid(),os.getgid()
        name='dmt-diag-'+uuid.uuid4().hex
        cmd=['/usr/bin/docker','run','--name',name,'--pull=never','--network=none','--read-only','--cap-drop=ALL',
             '--security-opt=no-new-privileges','--pids-limit=128','--memory=384m','--memory-swap=768m','--cpus=.8',
             '--ulimit','fsize=52428800:52428800','--ulimit','nofile=512:512','--log-driver=none',
             '--user',f'{uid}:{gid}','--tmpfs','/tmp:rw,nosuid,nodev,size=128m',
             '--mount',f'type=bind,src={root},dst=/work','--mount',f'type=bind,src={cache/"node_modules"},dst=/work/node_modules,readonly',
             '--tmpfs',f'/work/node_modules/.vite-temp:rw,nosuid,nodev,size=32m,uid={uid},gid={gid},mode=0700',
             '-w','/work','-e','HOME=/tmp','-e','DEBUG=vite:config,vite:resolve,vite:transform,vite:build,vite:deps']
        for k,v in config.get('env',{}).items():cmd+=['-e',k+'='+v]
        cmd += [IMAGE,'node','--input-type=module','-e',NODE]
        start=time.monotonic();out('docker_launch',name=name);host_sample(start)
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        raw=log_dir/'vite.log';markers=log_dir/'markers.jsonl'
        def drain():
            written=0
            with raw.open('wb') as f,markers.open('w') as m:
                for line in iter(proc.stdout.readline,b''):
                    if written<LIMIT:
                        chunk=line[:LIMIT-written];f.write(chunk);f.flush();written+=len(chunk)
                    if line.startswith(b'DMT_DIAG ') and len(line)<20000:
                        try:
                            data=json.loads(line[9:]);m.write(json.dumps(data)+'\n');m.flush()
                        except (ValueError,UnicodeError):pass
        t=threading.Thread(target=drain,daemon=True);t.start()
        cg=None;next_sample=10;state_attempts=0;reason=None
        while proc.poll() is None:
            elapsed=time.monotonic()-start
            if elapsed>=600:reason='BASELINE_WALL_TIMEOUT';break
            if shutil.disk_usage(BASE).free<3*1024**3:reason='DISK_RESERVE';break
            if elapsed>=next_sample:
                if cg is None and state_attempts<3:
                    state_attempts+=1;v=state(name);out('container_state',state=v)
                    if v and v['Pid']:
                        info=read('/proc/'+str(v['Pid'])+'/cgroup') or ''
                        p=next((line.split(':',2)[2] for line in info.splitlines() if line.startswith('0::')),None)
                        if p:cg=Path('/sys/fs/cgroup')/p.lstrip('/')
                host_sample(start,cg);next_sample=time.monotonic()-start+10
            time.sleep(1)
        host_sample(start,cg)
        out('before_cleanup',reason=reason,returncode=proc.poll(),state=state(name),elapsed=round(time.monotonic()-start,2))
        if reason:
            try:subprocess.run(['/usr/bin/docker','kill',name],capture_output=True,timeout=90)
            except subprocess.TimeoutExpired:out('kill_timeout')
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        t.join(timeout=10)
        out('after_exit',returncode=proc.returncode,state=state(name))
        try:
            if not reason and proc.returncode==0:
                out('BUILD_VERIFY_PASS',result=verify(root/'dist'))
            else:out('BUILD_DIAG_FAILED',reason=reason or 'VITE_OR_DOCKER_EXIT')
        finally:
            try:subprocess.run(['/usr/bin/docker','rm','-f',name],capture_output=True,timeout=90)
            except subprocess.TimeoutExpired:out('cleanup_timeout')
if __name__=='__main__':run(Path(sys.argv[1]),Path(sys.argv[2]))
