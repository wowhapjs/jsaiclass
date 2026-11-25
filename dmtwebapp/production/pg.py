"""Local peer-authenticated PostgreSQL function client. No DB passwords."""
import base64, json, os, subprocess
class DatabaseUnavailable(RuntimeError): pass
ALLOWED={'login','dashboard','enqueue','student_action','resolve_app','tls_allowed','claim_job','find_artifact','finish_job','browser_data','update_phase'}
def call(fn, payload=None):
    if fn not in ALLOWED: raise ValueError("INVALID_DB_FUNCTION")
    raw=base64.b64encode(json.dumps(payload or {},ensure_ascii=False,separators=(',',':')).encode()).decode()
    query="SET statement_timeout='15s'; SELECT dmtwebapp."+fn+"(convert_from(decode('"+raw+"','base64'),'UTF8')::jsonb);"
    env={'PATH':'/usr/bin:/bin','PGHOST':'/var/run/postgresql','PGDATABASE':os.environ.get('DMT_DB','dmtwebapp'),'PGCONNECT_TIMEOUT':'5','LANG':'C.UTF-8'}
    try:
        proc=subprocess.run(['/usr/bin/psql','-X','-qAt','-v','ON_ERROR_STOP=1'],input=query.encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=25)
    except (subprocess.TimeoutExpired,OSError) as exc:
        raise DatabaseUnavailable('DATABASE_UNAVAILABLE') from exc
    if proc.returncode: raise DatabaseUnavailable('DATABASE_UNAVAILABLE')
    return json.loads(proc.stdout) if proc.stdout.strip() else {}
