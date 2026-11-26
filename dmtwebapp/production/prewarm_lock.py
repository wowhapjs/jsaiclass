"""Admin-only offline preparation of the reviewed classroom Firebase cache.
Use a verified registry lock plus npm content-addressed tarballs. No package
scripts, network, or student project files are executed during extraction.
"""
import base64,copy,fcntl,hashlib,json,os,platform,re,shutil,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath
from worker import CACHE,IMAGE,BASE,cache_hit,cache_key,verified_lock,FINDONE_KEYS,FINDONE_FULL
PKG=r'(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+'
LAYOUT=re.compile(r'node_modules/'+PKG+r'(?:/node_modules/'+PKG+r')*')
def applicable(entry):
    for field,value in [('os','linux'),('cpu','x64'),('libc','glibc')]:
        values=entry.get(field,[])
        if values and (('!'+value) in values or (any(not x.startswith('!') for x in values) and value not in values)):return False
    return True
def prepare(lock_path):
    if os.getuid()==0 or platform.machine()!='x86_64' or sys.platform!='linux':raise RuntimeError('UNSUPPORTED_PREWARM_HOST')
    lock=json.loads(lock_path.read_text());deps=lock['packages']['']['dependencies']
    if set(deps)!=FINDONE_KEYS|{'firebase'} or any(deps[k]!=FINDONE_FULL[k] for k in FINDONE_KEYS):raise RuntimeError('REVIEWED_FIREBASE_PROFILE_ONLY')
    sha=verified_lock(lock_path,deps);key=cache_key(deps,IMAGE)
    auto=CACHE/'auto';dest=auto/key
    with (auto/'install.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        if cache_hit(auto,deps,IMAGE):return dest
        if dest.exists():raise RuntimeError('INVALID_EXISTING_CACHE')
        if shutil.disk_usage(BASE).free<4*1024**3:raise RuntimeError('DISK_RESERVE')
        entries=lock['packages'];skipped=set();bins=[];total=0;count=0
        with tempfile.TemporaryDirectory(prefix='prewarm-',dir=auto) as td:
            root=Path(td)/'profile';root.mkdir(mode=0o750)
            for name,entry in sorted(entries.items(),key=lambda x:(x[0].count('/'),x[0])):
                if not name:continue
                if not LAYOUT.fullmatch(name):raise RuntimeError('INVALID_LOCK_PATH')
                if not applicable(entry) or any(name.startswith(x+'/node_modules/') for x in skipped):
                    if not entry.get('optional') and not any(name.startswith(x+'/node_modules/') for x in skipped):raise RuntimeError('REQUIRED_WRONG_PLATFORM')
                    skipped.add(name);continue
                pkg=root/name
                if entry.get('inBundle') and not entry.get('resolved'):
                    if not (pkg/'package.json').is_file():raise RuntimeError('BUNDLE_MISSING')
                    continue
                alg,b64=entry['integrity'].split('-',1)
                digest=base64.b64decode(b64,validate=True);h=digest.hex()
                archive=auto/'npm/_cacache/content-v2'/alg/h[:2]/h[2:4]/h[4:]
                with archive.open('rb') as fh:
                    if hashlib.file_digest(fh,alg).digest()!=digest:raise RuntimeError('TARBALL_INTEGRITY')
                pkg.mkdir(parents=True,exist_ok=True)
                with tarfile.open(archive,'r:gz') as tf:
                    for m in tf:
                        path=PurePosixPath(m.name)
                        if path.is_absolute() or '..' in path.parts or len(path.parts)<1 or path.parts[0]!='package':raise RuntimeError('TARBALL_PATH')
                        if len(path.parts)==1:
                            if not m.isdir():raise RuntimeError('TARBALL_ROOT')
                            continue
                        if not (m.isfile() or m.isdir()):raise RuntimeError('TARBALL_LINK_OR_SPECIAL')
                        count+=1;total+=m.size
                        if count>250000 or total>3*1024**3 or m.size>200*1024**2:raise RuntimeError('TARBALL_LIMIT')
                        item=copy.copy(m);item.name=str(PurePosixPath(*path.parts[1:]))
                        tf.extract(item,path=pkg,filter='data',set_attrs=True)
                manifest=json.loads((pkg/'package.json').read_text())
                if manifest.get('version')!=entry.get('version'):raise RuntimeError('PACKAGE_VERSION_MISMATCH')
                b=manifest.get('bin',{})
                if isinstance(b,str):b={manifest['name'].split('/')[-1]:b}
                if not isinstance(b,dict):raise RuntimeError('INVALID_BIN')
                nm=pkg.parent.parent if pkg.parent.name.startswith('@') else pkg.parent
                for name2,target in b.items():
                    if not re.fullmatch(r'[A-Za-z0-9_.-]+',name2) or name2 in ('.','..') or not isinstance(target,str):raise RuntimeError('INVALID_BIN')
                    exe=(pkg/target).resolve()
                    if not exe.is_relative_to(pkg.resolve()) or not exe.is_file():raise RuntimeError('INVALID_BIN_TARGET')
                    bins.append((nm/'.bin'/name2,exe))
                print('EXTRACTED',name,entry['version'],flush=True)
                if shutil.disk_usage(BASE).free<4*1024**3:raise RuntimeError('DISK_RESERVE')
            for link,target in bins:
                link.parent.mkdir(exist_ok=True)
                if not link.exists() and not link.is_symlink():
                    target.chmod(target.stat().st_mode|0o100)
                    link.symlink_to(os.path.relpath(target,link.parent))
            (root/'node_modules/.vite-temp').mkdir()
            shutil.copyfile(lock_path,root/'package-lock.json')
            (root/'package.json').write_text(json.dumps({'name':'dmt-shared-deps','private':True,'dependencies':deps}))
            (root/'READY.json').write_text(json.dumps({'key':key,'lock_sha256':sha}))
            root.rename(dest)
        if cache_hit(auto,deps,IMAGE)!=dest:raise RuntimeError('PREWARM_VERIFY_FAILED')
        print('PREWARM_PASS',dest.name,'files',count,'bytes',total,flush=True)
        return dest
if __name__=='__main__':prepare(Path(sys.argv[1]))
