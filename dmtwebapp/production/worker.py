"""Single-worker offline Vite builder using verified shared read-only dependencies."""
import hashlib,json,os,re,shutil,subprocess,sys,tempfile,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'hosting'/'trial'))
from engine import inspect_and_extract,inspect,verify,Error
from dependency_cache import checked_dependencies,cache_key,cache_hit,verified_lock,FINDONE_FULL,FINDONE_KEYS
from db_config import normalize,ConfigError
from pg import call

BASE=Path(os.environ.get('DMT_DATA','/var/lib/web-manager/site-media/jsaiclass/dmtwebapp-prod'))
IMAGE=os.environ.get('DMT_IMAGE','node@sha256:be979e5523c76fa4d5ca4ebd3099078f220aa47ec39c48ad5b5df9314debd6eb')
CACHE=Path(os.environ.get('DMT_DEPENDENCY_CACHE',str(BASE/'common')))
PIPELINE=3
def profile(deps):
    deps=checked_dependencies(deps)
    # Same AI Studio template: use the prevalidated minimal profile. Missing
    # actually imported modules fail closed rather than installing from source.
    if deps==FINDONE_FULL:
        return {k:deps[k] for k in sorted(FINDONE_KEYS)}
    return deps
def choose_cache(deps):
    deps=profile(deps)
    exact=cache_hit(CACHE,deps,IMAGE)
    if exact: return exact
    # A strict subset of a verified dependency profile can reuse its packages.
    for p in sorted(CACHE.glob('[a-f0-9]'*64)):
        try:
            lock=json.loads((p/'package-lock.json').read_text())
            declared=lock['packages']['']['dependencies']
            if all(declared.get(k)==v for k,v in deps.items()) and cache_hit(CACHE,declared,IMAGE)==p:
                return p
        except (OSError,ValueError,KeyError,TypeError): pass
    raise Error('DEPENDENCY_CACHE_REVIEW_REQUIRED')
def shared_build(root,plan,config):
    if plan['backend']: raise Error('SERVER_BACKEND_REVIEW_REQUIRED')
    mode=config.get('mode','none')
    if plan['database']=='review' and mode not in ('supabase','firebase'):
        raise Error('DATABASE_CONFIGURATION_REQUIRED')
    if mode=='supabase' and set(plan['db_dependencies'])-{'@supabase/supabase-js'}: raise Error('DATABASE_PROVIDER_MISMATCH')
    if mode=='firebase' and set(plan['db_dependencies'])-{'firebase'}: raise Error('DATABASE_PROVIDER_MISMATCH')
    if plan['framework']=='static':
        return root/'dist' if (root/'dist/index.html').is_file() else root
    if plan['framework']!='vite': raise Error('UNSUPPORTED_FRAMEWORK')
    cache=choose_cache(plan['dependencies'])
    if not (cache/'node_modules/.vite-temp').is_dir(): raise Error('CACHE_NOT_PREPARED')
    if (root/'node_modules').exists(): raise Error('PRIVATE_FILE')
    (root/'node_modules').mkdir()
    uid,gid=os.getuid(),os.getgid()
    if uid==0: raise Error('NON_ROOT_WORKER_REQUIRED')
    name='dmt-job-'+uuid.uuid4().hex
    docker=['/usr/bin/docker']
    if os.environ.get('DMT_TRIAL_DOCKER_SUDO')=='1': docker=['/usr/bin/sudo','-n','/usr/bin/docker']
    cmd=docker+['run','--name',name,'--pull=never','--network=none','--read-only','--cap-drop=ALL',
       '--security-opt=no-new-privileges','--pids-limit=128','--memory=384m','--memory-swap=768m','--cpus=.8',
       '--ulimit','fsize=52428800:52428800','--ulimit','nofile=512:512','--log-driver=none',
       '--user',f'{uid}:{gid}','--tmpfs','/tmp:rw,nosuid,nodev,size=128m',
       '--mount',f'type=bind,src={root},dst=/work',
       '--mount',f'type=bind,src={cache/"node_modules"},dst=/work/node_modules,readonly',
       '--tmpfs',f'/work/node_modules/.vite-temp:rw,nosuid,nodev,size=32m,uid={uid},gid={gid},mode=0700',
       '-w','/work','-e','HOME=/tmp']
    for k,v in config.get('env',{}).items():cmd+=['-e',k+'='+v]
    cmd += [IMAGE,'node','--input-type=module','-e','import {build} from "vite"; await build({base:"./",cacheDir:"/tmp/vite-cache",build:{reportCompressedSize:false}})']
    try:
        with subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as proc:
            start=time.monotonic()
            while proc.poll() is None:
                time.sleep(.5)
                if time.monotonic()-start>360 or shutil.disk_usage(BASE).free<3*1024**3:
                    proc.kill();raise Error('BUILD_RESOURCE_LIMIT')
            if proc.returncode: raise Error('ISOLATED_BUILD_FAILED')
    finally:
        subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=False)
    return root/'dist'

def process(job):
    jid=job['id'];src=BASE/'incoming'/(str(uuid.UUID(job['storage_key']))+'.zip')
    artifact=None
    try:
        if shutil.disk_usage(BASE).free<3*1024**3: raise Error('DISK_RESERVE_LIMIT')
        if src.stat().st_size!=job['zip_bytes']: raise Error('ZIP_SIZE_MISMATCH')
        sha=hashlib.sha256(src.read_bytes()).hexdigest()
        config=normalize(job.get('public_config'))
        key=hashlib.sha256(json.dumps({'sha':sha,'config':config,'image':IMAGE,'pipeline':PIPELINE},sort_keys=True).encode()).hexdigest()
        old=call('find_artifact',{'app':job['app_id'],'key':key})
        if old:
            p=BASE/'artifacts'/old['artifact']/'web';info=verify(p)
            return call('finish_job',{'id':jid,'status':'ready','artifact':old['artifact'],'bytes':info['bytes'],'sha':sha,'key':key,'database':old['database'],'config':config})
        with tempfile.TemporaryDirectory(prefix='build-',dir=BASE/'work') as tmp:
            root=inspect_and_extract(src,Path(tmp));plan=inspect(root)
            out=shared_build(root,plan,config);info=verify(out)
            mode=config.get('mode','none')
            database=mode if mode!='none' else plan['database']
            aid=str(uuid.uuid4());artifact=BASE/'artifacts'/aid
            artifact.mkdir(mode=0o750)
            shutil.copytree(out,artifact/'web',symlinks=False)
            verify(artifact/'web')
            for p in artifact.rglob('*'):p.chmod(0o750 if p.is_dir() else 0o640)
            artifact.chmod(0o750)
            result=call('finish_job',{'id':jid,'status':'ready','artifact':aid,'bytes':info['bytes'],'sha':sha,'key':key,'database':database,'config':config})
            if result.get('error'):
                shutil.rmtree(artifact);artifact=None
            return result
    except Exception as exc:
        if artifact and artifact.exists():shutil.rmtree(artifact)
        code=str(exc) if isinstance(exc,(Error,ConfigError)) else 'BUILD_OR_ZIP_FAILED'
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
                else: time.sleep(1)
            except Exception:
                print('worker retry',flush=True);time.sleep(3)
if __name__=='__main__':main()
