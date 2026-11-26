"""Bounded operator-only Vite diagnostics. Never publish raw logs or env values."""
import json,os,re,shutil,subprocess,threading,time,uuid
from pathlib import Path

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
 await build({base:'./',cacheDir:'/tmp/vite-cache',logLevel:'info',
  plugins:[diag],build:{reportCompressedSize:false}});
 emit('vite_build_done',snapshot());
}catch(e){emit('vite_error',{name:e?.name,code:typeof e?.code==='string'?e.code:null,...snapshot()});console.error(e);process.exitCode=1}
finally{clearInterval(timer)}
"""
CAP=2*1024*1024
EVENTS={'node_start','heartbeat','vite_import_start','vite_import_done','config_resolved','build_start','transform_progress','build_end','render_start','generate_bundle','write_bundle','close_bundle','vite_build_done','vite_error'}
METRICS={'ms','rss','heap','cpu_user_us','cpu_system_us','transformed'}
def read(p):
    try:return Path(p).read_text().strip()
    except OSError:return None
def numeric_rows(s):
    return {k:int(v) for k,v in re.findall(r'^([a-z_]+)\s+(\d+)$',s or '',re.M)}
class BuildLog:
    def __init__(self,base,jid):
        self.base=Path(base);self.jid=str(uuid.UUID(jid));self.start=time.monotonic();self.stop=threading.Event()
        self.folder=self.base/'work/build-logs'
        self.folder.mkdir(mode=0o700,exist_ok=True)
        if self.folder.is_symlink() or not self.folder.is_dir():raise RuntimeError('UNSAFE_LOG_DIR')
        self.folder.chmod(0o700)
        for p in sorted(self.folder.glob('*.log'),key=lambda p:p.stat().st_mtime,reverse=True)[30:]:
            if p.is_file() and not p.is_symlink():p.unlink()
        self.raw=self.folder/(self.jid+'.log')
    def emit(self,event,**fields):
        print('DMT_BUILD '+json.dumps({'job':self.jid,'event':event,'elapsed_s':round(time.monotonic()-self.start,2),**fields},separators=(',',':')),flush=True)
    def drain(self,stream):
        written=0;markers=0
        try:
            fd=os.open(self.raw,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as f:
                for line in iter(lambda:stream.readline(16384),b''):
                    if written<CAP:
                        chunk=line[:CAP-written];f.write(chunk);f.flush();written+=len(chunk)
                    if line.startswith(b'DMT_DIAG ') and markers<250:
                        try:
                            data=json.loads(line[9:])
                            ev=data.get('event')
                            if ev not in EVENTS:continue
                            safe={k:v for k,v in data.items() if k in METRICS and type(v) is int and 0<=v<10**15}
                            if isinstance(data.get('memory_events'),str):safe['memory_events']=numeric_rows(data['memory_events'])
                            if isinstance(data.get('cpu_stat'),str):safe['cpu_stat']=numeric_rows(data['cpu_stat'])
                            self.emit('vite_'+ev,**safe);markers+=1
                        except (ValueError,TypeError,AttributeError):pass
        except OSError:self.emit('log_write_error')
        finally:
            # Continue draining even if the private file cannot be written.
            try:
                while stream.read(16384):pass
            except OSError:pass
            self.emit('vite_log_closed',bytes=written,markers=markers,truncated=written>=CAP)
    def state(self,docker,name):
        try:
            r=subprocess.run(docker+['inspect','--format','{{json .State}}',name],capture_output=True,text=True,timeout=8)
            if r.returncode:return None
            v=json.loads(r.stdout)
            return {k:v.get(k) for k in ('Status','Running','OOMKilled','Dead','Pid','ExitCode','StartedAt','FinishedAt')}
        except (OSError,ValueError,subprocess.TimeoutExpired):return None
    def monitor(self,docker,name):
        cg=None
        while not self.stop.is_set():
            try:
                state=self.state(docker,name)
                if state and state.get('Pid') and cg is None:
                    info=read('/proc/'+str(state['Pid'])+'/cgroup') or ''
                    p=next((line.split(':',2)[2] for line in info.splitlines() if line.startswith('0::')),None)
                    if p:cg=Path('/sys/fs/cgroup')/p.lstrip('/')
                mem=read('/proc/meminfo') or ''
                fields={'state':state,'host_cpu':(read('/proc/stat') or '').splitlines()[:1],
                        'load':read('/proc/loadavg'),'disk_free':shutil.disk_usage(self.base).free,
                        'memory_kb':{k:int(v) for k,v in re.findall(r'^(MemAvailable|SwapFree|SwapTotal):\s+(\d+)',mem,re.M)},
                        'pressure':{k:read('/proc/pressure/'+k) for k in ('cpu','memory','io')}}
                if cg:fields['cgroup']={k:read(cg/k) for k in ('cpu.stat','memory.current','memory.peak','memory.events','memory.swap.current','io.stat','io.pressure','memory.pressure')}
                self.emit('system_sample',**fields)
            except Exception:self.emit('system_sample_error')
            self.stop.wait(10)
