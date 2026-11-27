"""Conservative resource admission and scoped Docker recovery for the single worker."""
import json,os,re,shutil,subprocess,time
from pathlib import Path
from engine import Error

def read_cpu():
    return [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
def read_psi(kind,mode):
    for line in Path('/proc/pressure/'+kind).read_text().splitlines():
        if line.startswith(mode+' '):return float(re.search(r'avg10=([0-9.]+)',line)[1])
    raise ValueError('PSI_NOT_AVAILABLE')
def sample(base,sleep=time.sleep):
    a=read_cpu();sleep(2);b=read_cpu()
    d=[y-x for x,y in zip(a,b)];total=max(sum(d),1)
    m={k:int(v) for k,v in re.findall(r'^(MemAvailable|SwapFree):\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)}
    return dict(steal=round(100*d[7]/total,1),iowait=round(100*d[4]/total,1),
                cpu_pressure=read_psi('cpu','some'),io_full=read_psi('io','full'),memory_full=read_psi('memory','full'),
                available_mb=m['MemAvailable']//1024,swap_free_mb=m['SwapFree']//1024,
                disk_free=shutil.disk_usage(base).free)
def reasons(s):
    return [key for key,bad in (
        ('CPU_STEAL',s['steal']>40),('IO_WAIT',s['iowait']>35),
        ('CPU_PRESSURE',s['cpu_pressure']>75),('IO_PRESSURE',s['io_full']>25),
        ('MEMORY_PRESSURE',s['memory_full']>25),('RAM_RESERVE',s['available_mb']<180),
        ('SWAP_RESERVE',s['swap_free_mb']<256),('DISK_RESERVE',s['disk_free']<3*1024**3)) if bad]
def cli(docker,args,timeout=15):
    try:
        r=subprocess.run(docker+args,capture_output=True,text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired) as e:raise Error('DOCKER_UNAVAILABLE') from e
    if r.returncode:raise Error('DOCKER_UNAVAILABLE')
    return r.stdout
def docker_cmd():
    return ['/usr/bin/sudo','-n','/usr/bin/docker'] if os.environ.get('DMT_TRIAL_DOCKER_SUDO')=='1' else ['/usr/bin/docker']
def owned(base,mounts):
    for m in mounts:
        if m.get('Destination')!='/work' or m.get('Type')!='bind':continue
        src=Path(m.get('Source','/')).resolve()
        if src.is_relative_to((base/'work').resolve()) or src.is_relative_to((base/'common/auto').resolve()):return True
    return False
def reconcile(base,docker=None):
    docker=docker or docker_cmd()
    names=cli(docker,['ps','-a','--format','{{.Names}}']).splitlines()
    for name in names:
        if not re.fullmatch(r'dmt-(job|resolver)-[a-f0-9]{32}',name):continue
        mounts=json.loads(cli(docker,['inspect','--format','{{json .Mounts}}',name]))
        if not owned(base,mounts):continue
        print('DMT_RECOVERY cleanup '+name,flush=True)
        cli(docker,['rm','-f',name],timeout=90)
    # Confirm that no owned container remains before requeueing or taking a job.
    for name in cli(docker,['ps','-a','--format','{{.Names}}']).splitlines():
        if re.fullmatch(r'dmt-(job|resolver)-[a-f0-9]{32}',name):
            mounts=json.loads(cli(docker,['inspect','--format','{{json .Mounts}}',name]))
            if owned(base,mounts):raise Error('OWNED_CONTAINER_REMAINS')
