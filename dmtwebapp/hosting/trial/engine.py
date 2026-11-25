#!/usr/bin/env python3
"""Private trial engine: SQLite metadata, immutable artifacts, explicit serving pointer.
Not an authenticated production service. Vite builds require an admin-supplied
trusted Docker image with an offline npm cache; no secrets or host network.
"""
import argparse, contextlib, hashlib, json, os, pathlib, re, shutil, sqlite3, stat, subprocess, tempfile, uuid, zipfile, fcntl
from pathlib import Path
from dependency_cache import cache_key, cache_hit, checked_dependencies, verified_lock, dependency_profile
MAX_ZIP=50*1024**2; MAX_TOTAL=250*1024**2; MAX_FILES=5000
SAFE=re.compile(r'^[a-z0-9][a-z0-9_-]{0,39}$'); ID=re.compile(r'^\d{4}$')
ASSETS={'.html','.htm','.js','.mjs','.css','.json','.webmanifest','.png','.jpg','.jpeg','.webp','.gif','.svg','.ico','.avif','.woff','.woff2','.ttf','.otf','.mp3','.wav','.ogg','.mp4','.webm','.wasm','.txt','.pdf','.xml','.csv'}
DENY={'.git','.svn','node_modules','.npmrc','.yarnrc','.yarnrc.yml','.pnpmfile.cjs','.netrc','id_rsa','id_ed25519'}
class Error(Exception): pass

def inspect_and_extract(z, dest):
    if z.stat().st_size>MAX_ZIP: raise Error('ZIP_TOO_LARGE')
    with zipfile.ZipFile(z) as f:
        infos=f.infolist()
        if len(infos)>MAX_FILES or sum(i.file_size for i in infos)>MAX_TOTAL: raise Error('ZIP_LIMIT')
        seen=set()
        for i in infos:
            n=i.filename.rstrip('/'); parts=n.split('/'); key=n.casefold()
            if not n or any(x in ('','.','..') for x in parts) or '\\' in n or ':' in n or any(ord(c)<32 for c in n) or key in seen: raise Error('UNSAFE_PATH')
            seen.add(key)
            if i.flag_bits&1 or stat.S_IFMT(i.external_attr>>16) not in (0,stat.S_IFREG,stat.S_IFDIR): raise Error('UNSAFE_TYPE')
            if any(x.lower() in DENY or (x.lower().startswith('.env') and x.lower()!='.env.example') or x.lower().endswith(('.pem','.key','.pfx','.p12')) for x in parts): raise Error('PRIVATE_FILE')
            if i.file_size>MAX_ZIP or (i.file_size>1024**2 and i.file_size>max(i.compress_size,1)*250): raise Error('ZIP_EXPANSION_LIMIT')
            p=dest.joinpath(*parts)
            if i.is_dir(): p.mkdir(parents=True,exist_ok=True); continue
            p.parent.mkdir(parents=True,exist_ok=True)
            with f.open(i) as src,p.open('xb') as out: shutil.copyfileobj(src,out,65536)
            if p.stat().st_size!=i.file_size: raise Error('SIZE_MISMATCH')
    def valid(p): return any((p/x).is_file() for x in ['package.json','index.html','dist/index.html'])
    if valid(dest): root=dest
    else:
        roots=[x for x in dest.iterdir() if x.is_dir() and valid(x)]
        if len(roots)!=1: raise Error('PROJECT_ROOT_NOT_FOUND')
        root=roots[0]
    return root

def inspect(root):
    pkg=json.loads((root/'package.json').read_text()) if (root/'package.json').is_file() else {}
    deps={**pkg.get('dependencies',{}),**pkg.get('devDependencies',{})}
    dbs=sorted(set(deps)&{'@supabase/supabase-js','firebase','pg','postgres','@prisma/client','mongoose','mysql2','better-sqlite3'})
    sources='\n'.join(p.read_text(errors='replace') for p in root.rglob('*') if p.is_file() and p.suffix in {'.js','.ts','.jsx','.tsx','.mjs','.py'} and p.stat().st_size<512*1024)
    backend=bool(re.search(r'\b(?:app\.listen\s*\(|express\s*\(|createServer\s*\(|psycopg|sqlite3\.connect)',sources))
    browser='localStorage' in sources or 'indexedDB' in sources
    mode='vite' if 'vite' in deps else 'static' if not pkg and (root/'index.html').is_file() or (root/'dist/index.html').is_file() else 'unsupported'
    db='review' if dbs or backend else 'browser' if browser else 'none'
    return dict(framework=mode,database=db,dependencies=deps,db_dependencies=dbs,backend=backend,lockfile=(root/'package-lock.json').is_file())

def verify(p):
    if not (p/'index.html').is_file(): raise Error('INDEX_NOT_FOUND')
    n=b=0
    for x in p.rglob('*'):
        if x.is_symlink() or not(x.is_file() or x.is_dir()): raise Error('UNSAFE_OUTPUT')
        if x.is_dir(): continue
        if any(t.startswith('.') for t in x.relative_to(p).parts) or x.suffix.lower() not in ASSETS: raise Error('UNSUPPORTED_ASSET')
        n+=1;b+=x.stat().st_size
        if n>MAX_FILES or b>MAX_TOTAL or x.stat().st_size>MAX_ZIP: raise Error('OUTPUT_LIMIT')
    return {'files':n,'bytes':b}

def build(root, plan, image):
    if plan['database']=='review': raise Error('DB_RUNTIME_REVIEW_REQUIRED')
    if plan['framework']=='static': return root/'dist' if (root/'dist/index.html').is_file() else root
    if plan['framework']!='vite': raise Error('UNSUPPORTED_FRAMEWORK')
    if not image or not re.fullmatch(r'[\w./:-]+@sha256:[a-f0-9]{64}',image): raise Error('TRUSTED_BUILD_IMAGE_REQUIRED')
    if os.getuid()==0: raise Error('NON_ROOT_WORKER_REQUIRED')
    docker=['sudo','-n','docker'] if os.environ.get('DMT_TRIAL_DOCKER_SUDO')=='1' else ['docker']
    online=os.environ.get('DMT_TRIAL_ONLINE_DEPS')=='1'
    def run(work,command,network,seconds,cache=None):
        name='dmt-'+uuid.uuid4().hex
        cmd=docker+['run','--name',name,'--pull=never','--network='+network,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=128','--memory=384m','--memory-swap=768m','--cpus=.6','--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,nosuid,nodev,size=256m','--mount',f'type=bind,src={work},dst=/work','-w','/work','-e','HOME=/tmp','-e','npm_config_cache=/tmp/npm-cache','--entrypoint','/bin/sh',image,'-ec',command]
        if cache is not None:
            at=cmd.index('--entrypoint'); cmd[at:at]=['--mount',f'type=bind,src={cache},dst=/npm-cache','-e','npm_config_cache=/npm-cache']
        try:
            with tempfile.TemporaryFile() as log:
                r=subprocess.run(cmd,stdout=log,stderr=log,timeout=seconds)
                if r.returncode: raise Error('DEPENDENCY_INSTALL_FAILED' if network!='none' else 'ISOLATED_BUILD_FAILED')
        except subprocess.TimeoutExpired: raise Error('BUILD_TIMEOUT')
        except OSError: raise Error('DOCKER_UNAVAILABLE')
        finally:
            try: subprocess.run(docker+['rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=False)
            except (OSError,subprocess.TimeoutExpired): pass
    # Only trusted, registry semver declarations are passed to the networked
    # dependency installer. Uploaded config/scripts/source are never mounted there.
    deps=dependency_profile(plan['dependencies'],plan.get('reviewed_findone',False))
    if (root/'node_modules').exists(): raise Error('PRIVATE_FILE')
    cache_dir=Path(os.environ.get('DMT_DEPENDENCY_CACHE',str(Path.home()/'.cache'/'dmtwebapp-deps'))).resolve()
    cache_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    npm_cache=cache_dir/'npm';npm_cache.mkdir(mode=0o700,exist_ok=True)
    key=cache_key(deps,image)
    with (cache_dir/'cache.lock').open('a') as cache_lock:
        fcntl.flock(cache_lock,fcntl.LOCK_EX)
        hit=cache_hit(cache_dir,deps,image)
        if hit is None:
            # Resolution/install run without student source mounted. Cache is never
            # exposed to Vite or student scripts; cached modules are copied privately.
            with tempfile.TemporaryDirectory(prefix='resolve-',dir=cache_dir) as d:
                dep=Path(d);(dep/'package.json').write_text(json.dumps({'name':'dmt-trusted-deps','private':True,'dependencies':deps}))
                net='bridge' if online else 'none'
                flags='--prefer-offline --fetch-retries=1 --fetch-timeout=20000' if online else '--offline'
                run(dep,'npm install --package-lock-only --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org/ '+flags,net,480,cache=npm_cache)
                sha=verified_lock(dep/'package-lock.json',deps)
                run(dep,'npm ci --ignore-scripts --no-audit --no-fund --registry=https://registry.npmjs.org/ '+flags,net,480,cache=npm_cache)
                (dep/'READY.json').write_text(json.dumps({'key':key,'lock_sha256':sha}))
                final=cache_dir/key
                if final.exists(): raise Error('INVALID_CACHE_ENTRY_REQUIRES_REVIEW')
                dep.rename(final);hit=final
        subprocess.run(['cp','-a','--reflink=auto',str(hit/'node_modules'),str(root/'node_modules')],check=True,timeout=120)
        shutil.copyfile(hit/'package-lock.json',root/'package-lock.trial.json')
    run(root,'node --input-type=module -e \'import {build} from "vite"; await build({base:"./",build:{reportCompressedSize:false}})\'','none',360)
    return root/'dist'

class Store:
    def __init__(self,base):
        self.base=Path(base).resolve();self.base.mkdir(parents=True,exist_ok=True);(self.base/'artifacts').mkdir(exist_ok=True)
        self.db=sqlite3.connect(self.base/'trial.sqlite',timeout=15,isolation_level=None);self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS apps(id INTEGER PRIMARY KEY, student TEXT NOT NULL, folder TEXT NOT NULL, name TEXT NOT NULL, active INTEGER, previous INTEGER, next_version INTEGER NOT NULL DEFAULT 1, UNIQUE(student,folder)); CREATE TABLE IF NOT EXISTS versions(app INTEGER REFERENCES apps(id), version INTEGER, zip_name TEXT NOT NULL, sha256 TEXT, title TEXT, notes TEXT, state TEXT NOT NULL CHECK(state IN ('building','ready','failed','deleted')), artifact TEXT, error TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(app,version)); CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, app INTEGER, action TEXT, version INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);''')
        with self.tx():
            if 'build_key' not in {r[1] for r in self.db.execute('PRAGMA table_info(versions)')}:
                self.db.execute('ALTER TABLE versions ADD COLUMN build_key TEXT')
            self.db.execute('CREATE INDEX IF NOT EXISTS version_build_lookup ON versions(app,build_key,state)')
    def close(self): self.db.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    @contextlib.contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try: yield;self.db.commit()
        except BaseException: self.db.rollback();raise
    def app(self,student,folder):
        row=self.db.execute('SELECT * FROM apps WHERE student=? AND folder=?',(student,folder)).fetchone()
        if not row: raise Error('APP_NOT_FOUND')
        return row
    def upload(self,student,folder,name,z,title='',notes='',image=None):
        if not ID.fullmatch(student) or not SAFE.fullmatch(folder) or folder in {'api','versions','login','logout','admin','assets'}: raise Error('INVALID_FOLDER')
        z=Path(z)
        if z.stat().st_size>MAX_ZIP: raise Error('ZIP_TOO_LARGE')
        source_sha=hashlib.sha256(z.read_bytes()).hexdigest()
        key=uuid.uuid4().hex; artifact=self.base/'artifacts'/key
        # An identical ZIP can reuse a previously verified artifact for the same app.
        # Build image and pipeline identity are part of the key. No cross-student reuse.
        build_key=hashlib.sha256(json.dumps({'source':source_sha,'image':image,'pipeline':2},sort_keys=True).encode()).hexdigest()
        with self.tx():
            self.db.execute('INSERT OR IGNORE INTO apps(student,folder,name) VALUES(?,?,?)',(student,folder,name));a=self.app(student,folder);v=a['next_version'];self.db.execute('UPDATE apps SET next_version=next_version+1 WHERE id=?',(a['id'],));self.db.execute('INSERT INTO versions(app,version,zip_name,title,notes,state,sha256,build_key) VALUES(?,?,?,?,?,?,?,?)',(a['id'],v,z.name,title,notes,'building',source_sha,build_key))
        try:
            with (self.base/'build.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                existing=self.db.execute("SELECT artifact FROM versions WHERE app=? AND build_key=? AND state='ready' ORDER BY version DESC LIMIT 1",(a['id'],build_key)).fetchone()
                reused=False
                if existing:
                    try:
                        verify(self.base/'artifacts'/existing['artifact']/'web')
                        key=existing['artifact'];reused=True
                    except (OSError,Error,TypeError):
                        pass
                if not reused:
                    with tempfile.TemporaryDirectory(dir=self.base) as tmp:
                        root=inspect_and_extract(z,Path(tmp));plan=inspect(root);plan['reviewed_findone']=source_sha=='1ae73ebf9bc418a236fad7f53ae9cfc856c8af7d7cbad605978618e0396a02be';out=build(root,plan,image);verify(out)
                        artifact.mkdir();shutil.copyfile(z,artifact/'original.zip');shutil.copytree(out,artifact/'web');verify(artifact/'web')
                with self.tx():
                    self.db.execute('UPDATE versions SET state=?,artifact=? WHERE app=? AND version=?',('ready',key,a['id'],v)); self.db.execute('INSERT INTO events(app,action,version) VALUES(?,?,?)',(a['id'],'cache_reused' if reused else 'ready',v))
        except Exception as e:
            if artifact.exists(): shutil.rmtree(artifact)
            with self.tx(): self.db.execute('UPDATE versions SET state=?,error=? WHERE app=? AND version=?',('failed',str(e) if isinstance(e,Error) else 'BUILD_OR_ZIP_FAILED',a['id'],v))
            raise
        return v
    def version(self,a,v):
        r=self.db.execute('SELECT * FROM versions WHERE app=? AND version=?',(a['id'],v)).fetchone()
        if not r: raise Error('VERSION_NOT_FOUND')
        return r
    def serve(self,student,folder,v):
        with self.tx():
            a=self.app(student,folder);r=self.version(a,v)
            if r['state']!='ready': raise Error('VERSION_NOT_READY')
            verify(self.base/'artifacts'/r['artifact']/'web')
            if a['active']!=v:
                self.db.execute('UPDATE apps SET active=?,previous=? WHERE id=?',(v,a['active'],a['id']));self.db.execute('INSERT INTO events(app,action,version) VALUES(?,?,?)',(a['id'],'serve',v))
    def rollback(self,student,folder,v):
        # Explicit target, no version renumbering or database rollback.
        with self.tx():
            a=self.app(student,folder);r=self.version(a,v)
            if r['state']!='ready' or v==a['active'] or (a['active'] is not None and v>=a['active']): raise Error('INVALID_ROLLBACK_TARGET')
            verify(self.base/'artifacts'/r['artifact']/'web');self.db.execute('UPDATE apps SET active=?,previous=? WHERE id=?',(v,a['active'],a['id']));self.db.execute('INSERT INTO events(app,action,version) VALUES(?,?,?)',(a['id'],'rollback',v))
    def delete(self,student,folder,v):
        with self.tx():
            a=self.app(student,folder);r=self.version(a,v)
            if v==a['active']: raise Error('ACTIVE_VERSION_CANNOT_DELETE')
            if r['state'] not in ('ready','failed'): raise Error('INVALID_DELETE_TARGET')
            self.db.execute('UPDATE versions SET state=? WHERE app=? AND version=?',('deleted',a['id'],v));self.db.execute('UPDATE apps SET previous=NULL WHERE id=? AND previous=?',(a['id'],v));self.db.execute('INSERT INTO events(app,action,version) VALUES(?,?,?)',(a['id'],'delete',v))
        # Logical deletion immediately denies access; artifacts retained for admin cleanup.
    def resolve(self,student,folder,v=None):
        a=self.app(student,folder);r=self.version(a,v if v is not None else a['active'])
        if r['state']!='ready': raise Error('VERSION_NOT_READY')
        return self.base/'artifacts'/r['artifact']/'web'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('zip',type=Path);a=p.parse_args()
    with tempfile.TemporaryDirectory() as tmp: print(json.dumps(inspect(inspect_and_extract(a.zip,Path(tmp))),indent=2))
