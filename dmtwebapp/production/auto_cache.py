"""Install registry dependencies in a network-isolated resolver through a registry-only tunnel."""
import contextlib,fcntl,json,os,re,select,shutil,socket,socketserver,subprocess,tempfile,threading,time,uuid
from pathlib import Path
from dependency_cache import checked_dependencies,cache_key,cache_hit,verified_lock
from engine import Error
MAX_CACHE=5*1024**3
MAX_PROFILES=24
REGISTRY='registry.npmjs.org'
RELAY=r"""
const net=require('node:net'),{spawn}=require('node:child_process');
const server=net.createServer(client=>{
 const target=net.createConnection('/relay/registry.sock');
 client.on('error',()=>target.destroy());target.on('error',()=>client.destroy());
 client.pipe(target);target.pipe(client);
});
server.listen(18765,'127.0.0.1',()=>{
 const args=process.argv.slice(2);
 const child=spawn('npm',args,{stdio:'inherit',env:{...process.env,HTTPS_PROXY:'http://127.0.0.1:18765',HTTP_PROXY:'http://127.0.0.1:18765',NO_PROXY:'',https_proxy:'http://127.0.0.1:18765',http_proxy:'http://127.0.0.1:18765',no_proxy:'',npm_config_https_proxy:'http://127.0.0.1:18765',npm_config_proxy:'http://127.0.0.1:18765'}});
 child.on('error',()=>process.exit(1));child.on('exit',code=>process.exit(code??1));
});
"""
def allowed_connect(line):
    return line in (b'CONNECT registry.npmjs.org:443 HTTP/1.1',b'CONNECT registry.npmjs.org:443 HTTP/1.0')
class Tunnel(socketserver.BaseRequestHandler):
    def handle(self):
        client=self.request;client.settimeout(15)
        try:
            header=b''
            while b'\r\n\r\n' not in header and len(header)<8192:
                chunk=client.recv(1024)
                if not chunk:return
                header+=chunk
            if b'\r\n\r\n' not in header or not allowed_connect(header.split(b'\r\n',1)[0]):
                client.sendall(b'HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');return
            with socket.create_connection((REGISTRY,443),timeout=20) as upstream:
                client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                extra=header.split(b'\r\n\r\n',1)[1]
                if extra:upstream.sendall(extra)
                upstream.settimeout(30);client.settimeout(30)
                while True:
                    ready,_,_=select.select([client,upstream],[],[],45)
                    if not ready:return
                    for source in ready:
                        data=source.recv(65536)
                        if not data:return
                        (upstream if source is client else client).sendall(data)
        except OSError:return
class RelayServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True
    request_queue_size=32
@contextlib.contextmanager
def registry_relay(directory):
    path=directory/'registry.sock'
    with RelayServer(str(path),Tunnel) as srv:
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        try:yield
        finally:srv.shutdown();thread.join(timeout=3)
def disk_size(path):
    return sum(p.lstat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink())
def install_profile(cache,deps,image,base):
    deps=checked_dependencies(deps);auto=cache/'auto'
    if not auto.is_dir():raise Error('AUTO_CACHE_NOT_CONFIGURED')
    key=cache_key(deps,image)
    with (auto/'install.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        hit=cache_hit(auto,deps,image)
        if hit:return hit
        dest=auto/key
        if dest.exists():raise Error('INVALID_CACHE_ENTRY_REQUIRES_REVIEW')
        if len(list(auto.glob('[a-f0-9]'*64)))>=MAX_PROFILES or disk_size(auto)>MAX_CACHE:raise Error('DEPENDENCY_CACHE_LIMIT')
        npm=auto/'npm';npm.mkdir(mode=0o750,exist_ok=True)
        uid,gid=os.getuid(),os.getgid()
        if uid==0:raise Error('NON_ROOT_WORKER_REQUIRED')
        docker=['/usr/bin/docker']
        if os.environ.get('DMT_TRIAL_DOCKER_SUDO')=='1':docker=['/usr/bin/sudo','-n','/usr/bin/docker']
        with tempfile.TemporaryDirectory(prefix='resolve-',dir=auto) as tmp:
            root=Path(tmp);work=root/'work';work.mkdir()
            # Unix socket path must fit the OS limit; short private /tmp directory.
            with tempfile.TemporaryDirectory(prefix='dmt-npm-') as relaydir:
                relay=Path(relaydir);(relay/'relay.cjs').write_text(RELAY)
                (work/'package.json').write_text(json.dumps({'name':'dmt-shared-deps','private':True,'dependencies':deps}))
                def run(args,seconds):
                    name='dmt-resolver-'+uuid.uuid4().hex
                    cmd=docker+['run','--name',name,'--pull=never','--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=128','--memory=384m','--memory-swap=768m','--cpus=.8','--ulimit','fsize=52428800:52428800','--log-driver=none','--user',f'{uid}:{gid}','--tmpfs','/tmp:rw,nosuid,nodev,size=128m','--mount',f'type=bind,src={work},dst=/work','--mount',f'type=bind,src={npm},dst=/npm-cache','--mount',f'type=bind,src={relay},dst=/relay,readonly','-w','/work','-e','HOME=/tmp','-e','npm_config_cache=/npm-cache',image,'node','/relay/relay.cjs',*args,'--ignore-scripts','--no-audit','--no-fund','--prefer-offline','--fetch-retries=2','--fetch-timeout=30000','--registry=https://registry.npmjs.org/']
                    try:
                        with subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) as proc:
                            start=time.monotonic();last=0
                            while proc.poll() is None:
                                time.sleep(1);elapsed=time.monotonic()-start
                                if elapsed>seconds or shutil.disk_usage(base).free<4*1024**3:
                                    proc.kill();raise Error('DEPENDENCY_INSTALL_LIMIT')
                                if elapsed-last>20:
                                    last=elapsed
                                    if disk_size(auto)>MAX_CACHE:
                                        proc.kill();raise Error('DEPENDENCY_CACHE_LIMIT')
                            if proc.returncode:raise Error('DEPENDENCY_INSTALL_FAILED')
                    finally:subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30,check=False)
                with registry_relay(relay):
                    run(['install','--package-lock-only'],480)
                    try:sha=verified_lock(work/'package-lock.json',deps)
                    except ValueError as e:raise Error(str(e)) from e
                    run(['ci'],480)
                if verified_lock(work/'package-lock.json',deps)!=sha:raise Error('LOCK_CHANGED')
                (work/'node_modules/.vite-temp').mkdir(exist_ok=True)
                (work/'READY.json').write_text(json.dumps({'key':key,'lock_sha256':sha}))
                for p in work.rglob('*'):
                    if not p.is_symlink():p.chmod(p.stat().st_mode|0o050 if p.is_dir() else p.stat().st_mode|0o040)
                work.chmod(0o750)
                work.rename(dest)
        if not cache_hit(auto,deps,image):raise Error('CACHE_VERIFY_FAILED')
        return dest
