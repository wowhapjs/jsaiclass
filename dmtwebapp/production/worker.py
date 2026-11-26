"""Single-worker offline Vite builder using verified shared read-only dependencies."""
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,time,uuid,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'hosting'/'trial'))
from engine import inspect_and_extract,inspect,verify,Error
from dependency_cache import checked_dependencies,cache_key,cache_hit,verified_lock,FINDONE_FULL,FINDONE_KEYS
from db_config import normalize,ConfigError,detect_embedded
from auto_cache import install_profile
from pg import call,DatabaseUnavailable
from build_logging import BuildLog,NODE

BASE=Path(os.environ.get('DMT_DATA','/var/lib/web-manager/site-media/jsaiclass/dmtwebapp-prod'))
IMAGE=os.environ.get('DMT_IMAGE','node@sha256:be979e5523c76fa4d5ca4ebd3099078f220aa47ec39c48ad5b5df9314debd6eb')
CACHE=Path(os.environ.get('DMT_DEPENDENCY_CACHE',str(BASE/'common')))
PIPELINE=4
def profile(deps,root=None):
    try:deps=checked_dependencies(deps)
    except ValueError as e:raise Error(str(e)) from e
    # AI Studio's reviewed template includes many unused tooling packages.
    # Preserve every newly declared dependency except the known lint-only pair.
    template=FINDONE_FULL
    extra=set(deps)-set(template)
    if all(deps.get(k)==v for k,v in template.items()) and extra <= {'firebase','eslint','@firebase/eslint-plugin-security-rules'}:
        keys=set(FINDONE_KEYS)|({'firebase'} if 'firebase' in deps else set())
        if root:
            for p in root.rglob('*'):
                if p.is_file() and p.suffix in {'.js','.jsx','.ts','.tsx','.mjs','.cjs','.css'} and p.stat().st_size<512*1024 and not (p.name.startswith('eslint.config.') or '.test.' in p.name):
                    source=p.read_text(errors='replace')
                    for k in deps:
                        if re.search(r"""['"]"""+re.escape(k)+r"""(?:/[^'"]*)?['"]""",source):keys.add(k)
        return {k:deps[k] for k in sorted(keys)}
    return deps
def choose_cache(deps,root=None):
    deps=profile(deps,root)
    for directory in (CACHE,CACHE/'auto'):
        exact=cache_hit(directory,deps,IMAGE)
        if exact:return exact
        for p in sorted(directory.glob('[a-f0-9]'*64)):
            try:
                lock=json.loads((p/'package-lock.json').read_text())
                declared=lock['packages']['']['dependencies']
                if all(declared.get(k)==v for k,v in deps.items()) and cache_hit(directory,declared,IMAGE)==p:return p
            except (OSError,ValueError,KeyError,TypeError):pass
    return install_profile(CACHE,deps,IMAGE,BASE)
def shared_build(root,plan,config,log=None):
    if plan['backend']: raise Error('SERVER_BACKEND_REVIEW_REQUIRED')
    mode=config.get('mode','none')
    if plan['database']=='review' and mode not in ('supabase','firebase'):
        raise Error('DATABASE_CONFIGURATION_REQUIRED')
    if mode=='supabase' and set(plan['db_dependencies'])-{'@supabase/supabase-js'}: raise Error('DATABASE_PROVIDER_MISMATCH')
    if mode=='firebase' and set(plan['db_dependencies'])-{'firebase'}: raise Error('DATABASE_PROVIDER_MISMATCH')
    if plan['framework']=='static':
        return root/'dist' if (root/'dist/index.html').is_file() else root
    if plan['framework']!='vite': raise Error('UNSUPPORTED_FRAMEWORK')
    cache_start=time.monotonic()
    if log:log.emit('cache_lookup_start',provider=mode)
    cache=choose_cache(plan['dependencies'],root)
    if log:log.emit('cache_lookup_done',cache=cache.name,seconds=round(time.monotonic()-cache_start,2))
    if not (cache/'node_modules/.vite-temp').is_dir(): raise Error('CACHE_NOT_PREPARED')
    if (root/'node_modules').exists(): raise Error('PRIVATE_FILE')
    (root/'node_modules').mkdir()
    uid,gid=os.getuid(),os.getgid()
    if uid==0: raise Error('NON_ROOT_WORKER_REQUIRED')
    name='dmt-job-'+uuid.uuid4().hex
    docker=['/usr/bin/docker']
    if os.environ.get('DMT_TRIAL_DOCKER_SUDO')=='1': docker=['/usr/bin/sudo','-n','/usr/bin/docker']
    cmd=docker+['run','--rm','--name',name,'--pull=never','--network=none','--read-only','--cap-drop=ALL',
       '--security-opt=no-new-privileges','--pids-limit=128','--memory=384m','--memory-swap=768m','--cpus=.8',
       '--ulimit','fsize=52428800:52428800','--ulimit','nofile=512:512','--log-driver=none',
       '--user',f'{uid}:{gid}','--tmpfs','/tmp:rw,nosuid,nodev,size=128m',
       '--mount',f'type=bind,src={root},dst=/work',
       '--mount',f'type=bind,src={cache/"node_modules"},dst=/work/node_modules,readonly',
       '--tmpfs',f'/work/node_modules/.vite-temp:rw,nosuid,nodev,size=32m,uid={uid},gid={gid},mode=0700',
       '-w','/work','-e','HOME=/tmp']
    for k,v in config.get('env',{}).items():cmd+=['-e',k+'='+v]
    if log:cmd+=['-e','DEBUG=vite:resolve,vite:transform,vite:build,vite:deps']
    cmd += [IMAGE,'node','--input-type=module','-e',NODE if log else 'import {build} from "vite"; await build({base:"./",cacheDir:"/tmp/vite-cache",build:{reportCompressedSize:false}})']
    interrupted=False;monitor=None;reader=None
    try:
        if log:log.emit('docker_launch',container=name,auto_remove=True,cpu=.8,memory_mb=384,timeout_s=600)
        with subprocess.Popen(cmd,stdout=subprocess.PIPE if log else subprocess.DEVNULL,stderr=subprocess.STDOUT if log else subprocess.DEVNULL) as proc:
            start=time.monotonic()
            if log:
                log.emit('docker_cli_started',pid=proc.pid)
                reader=threading.Thread(target=log.drain,args=(proc.stdout,),daemon=True);reader.start()
                monitor=threading.Thread(target=log.monitor,args=(docker,name),daemon=True);monitor.start()
            while proc.poll() is None:
                time.sleep(.5)
                elapsed=time.monotonic()-start;free=shutil.disk_usage(BASE).free
                if elapsed>600 or free<3*1024**3:
                    if log:log.emit('build_limit',reason='wall_timeout' if elapsed>600 else 'disk_reserve',seconds=round(elapsed,2),disk_free=free)
                    interrupted=True;proc.kill();raise Error('BUILD_RESOURCE_LIMIT')
            if log:log.emit('docker_cli_exit',returncode=proc.returncode,seconds=round(time.monotonic()-start,2))
            if proc.returncode: raise Error('ISOLATED_BUILD_FAILED')
    finally:
        if log:
            log.stop.set()
            if reader:reader.join(timeout=3)
            if monitor:monitor.join(timeout=9)
        if interrupted:
            if log:log.emit('docker_cleanup_start',container=name)
            try:
                result=subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=90,check=False)
                if log:log.emit('docker_cleanup_exit',returncode=result.returncode)
            except subprocess.TimeoutExpired:
                if log:log.emit('docker_cleanup_timeout')
                raise Error('BUILD_CONTAINER_CLEANUP_TIMEOUT')
    return root/'dist'

def phase(jid,stage):
    try: call('update_phase',{'id':jid,'phase':stage})
    except DatabaseUnavailable: print('phase status temporarily unavailable',flush=True)

def process(job):
    jid=job['id'];src=BASE/'incoming'/(str(uuid.UUID(job['storage_key']))+'.zip')
    artifact=None;commit_attempted=False;log=None
    try:
        try:log=BuildLog(BASE,jid)
        except Exception:print('build diagnostic initialization failed',flush=True)
        if log:log.emit('job_start')
        if shutil.disk_usage(BASE).free<3*1024**3: raise Error('DISK_RESERVE_LIMIT')
        if src.stat().st_size!=job['zip_bytes']: raise Error('ZIP_SIZE_MISMATCH')
        sha=hashlib.sha256(src.read_bytes()).hexdigest()
        config=normalize(job.get('public_config'))
        with tempfile.TemporaryDirectory(prefix='build-',dir=BASE/'work') as tmp:
            root=inspect_and_extract(src,Path(tmp))
            if sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and p.suffix in {'.js','.ts','.jsx','.tsx','.mjs','.py'})>12*1024**2:raise Error('SOURCE_REVIEW_LIMIT')
            plan=inspect(root)
            if log:log.emit('project_inspected',framework=plan['framework'])
            config=detect_embedded(root,plan,config)
            key=hashlib.sha256(json.dumps({'sha':sha,'config':config,'image':IMAGE,'pipeline':PIPELINE},sort_keys=True).encode()).hexdigest()
            old=call('find_artifact',{'app':job['app_id'],'key':key})
            if old:
                if log:log.emit('artifact_reuse')
                phase(jid,'reuse')
                p=BASE/'artifacts'/old['artifact']/'web';info=verify(p)
                return call('finish_job',{'id':jid,'status':'ready','artifact':old['artifact'],'bytes':info['bytes'],'sha':sha,'key':key,'database':old['database'],'config':config})
            phase(jid,'build')
            out=shared_build(root,plan,config,log)
            phase(jid,'verify')
            if out.is_symlink() or not out.resolve().is_relative_to(root.resolve()):raise Error('UNSAFE_OUTPUT')
            info=verify(out)
            if log:log.emit('output_verified',files=info.get('files'),bytes=info['bytes'])
            mode=config.get('mode','none')
            database=mode if mode!='none' else plan['database']
            aid=str(uuid.uuid4());artifact=BASE/'artifacts'/aid
            artifact.mkdir(mode=0o750)
            shutil.copytree(out,artifact/'web',symlinks=False)
            verify(artifact/'web')
            for p in artifact.rglob('*'):p.chmod(0o750 if p.is_dir() else 0o640)
            artifact.chmod(0o750)
            commit_attempted=True
            result=call('finish_job',{'id':jid,'status':'ready','artifact':aid,'bytes':info['bytes'],'sha':sha,'key':key,'database':database,'config':config})
            if log:log.emit('finish_job',success=not bool(result.get('error')))
            if result.get('error'):
                shutil.rmtree(artifact);artifact=None
            return result
    except Exception as exc:
        if artifact and artifact.exists() and not commit_attempted:shutil.rmtree(artifact)
        if isinstance(exc,DatabaseUnavailable) and commit_attempted:
            # Keep the artifact: the DB may already have committed the ready status.
            raise
        code=str(exc) if isinstance(exc,(Error,ConfigError)) else 'BUILD_OR_ZIP_FAILED'
        if log:log.emit('job_failed',error=code[:100] if re.fullmatch(r'[A-Z0-9_]+',code) else 'BUILD_OR_ZIP_FAILED')
        return call('finish_job',{'id':jid,'status':'failed','error':code[:100]})
def main():
    import fcntl
    with (BASE/'work/worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            try:
                job=call('claim_job')
                if job.get('id'):
                    start=time.monotonic();result=process(job)
                    print('job',job['id'],round(time.monotonic()-start,2),result.get('error','processed'),flush=True)
                else: time.sleep(3)
            except Exception:
                print('worker retry',flush=True);time.sleep(3)
if __name__=='__main__':main()
