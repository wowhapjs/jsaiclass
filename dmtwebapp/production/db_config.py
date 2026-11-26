"""Public database connection options only; no private credentials."""
import re, urllib.parse, json, base64
class ConfigError(Exception): pass
def normalize(value):
    if value is None: return {}
    if not isinstance(value,dict): raise ConfigError('DB_CONFIG_INVALID')
    mode=value.get('mode','none')
    if mode in ('none','managed'): return {'mode':mode}
    if mode not in ('supabase','firebase'): raise ConfigError('DB_PROVIDER_UNSUPPORTED')
    env=value.get('env',{})
    if not isinstance(env,dict) or len(env)>12: raise ConfigError('DB_CONFIG_INVALID')
    allowed={'VITE_SUPABASE_URL','VITE_SUPABASE_ANON_KEY','VITE_SUPABASE_PUBLISHABLE_KEY'} if mode=='supabase' else {'VITE_FIREBASE_API_KEY','VITE_FIREBASE_AUTH_DOMAIN','VITE_FIREBASE_PROJECT_ID','VITE_FIREBASE_STORAGE_BUCKET','VITE_FIREBASE_MESSAGING_SENDER_ID','VITE_FIREBASE_APP_ID','VITE_FIREBASE_DATABASE_URL','VITE_FIREBASE_MEASUREMENT_ID'}
    for k,v in env.items():
        if k not in allowed or not isinstance(v,str) or not 1<=len(v)<=4096 or re.search(r'(?i)(service.role|sb_secret_|-----BEGIN|sk_live_)',v):
            raise ConfigError('PRIVATE_OR_UNKNOWN_DB_KEY')
        if v.count('.')==2:
            try:
                part=v.split('.')[1];decoded=json.loads(base64.urlsafe_b64decode(part+'='*(-len(part)%4)))
                if isinstance(decoded,dict) and decoded.get('role') not in (None,'anon'): raise ConfigError('PRIVATE_OR_UNKNOWN_DB_KEY')
            except (ValueError,TypeError,UnicodeError): pass
    origins=[]
    if mode=='supabase':
        u=urllib.parse.urlsplit(env.get('VITE_SUPABASE_URL',''))
        if u.scheme!='https' or not re.fullmatch(r'[a-z0-9-]+\.supabase\.co',u.netloc) or u.path not in ('','/') or u.query or u.fragment: raise ConfigError('SUPABASE_URL_REQUIRED')
        if not any(k in env for k in ('VITE_SUPABASE_ANON_KEY','VITE_SUPABASE_PUBLISHABLE_KEY')): raise ConfigError('PUBLIC_KEY_REQUIRED')
        origins=['https://'+u.netloc,'wss://'+u.netloc]
    else:
        p=env.get('VITE_FIREBASE_PROJECT_ID','')
        if not re.fullmatch(r'[a-z0-9-]{4,63}',p) or 'VITE_FIREBASE_API_KEY' not in env: raise ConfigError('FIREBASE_CONFIG_REQUIRED')
        for k in ('VITE_FIREBASE_AUTH_DOMAIN','VITE_FIREBASE_STORAGE_BUCKET'):
            if k in env and not re.fullmatch(r'[a-z0-9.-]+',env[k]): raise ConfigError('DB_CONFIG_INVALID')
        if 'VITE_FIREBASE_DATABASE_URL' in env:
            u=urllib.parse.urlsplit(env['VITE_FIREBASE_DATABASE_URL'])
            if u.scheme!='https' or not re.fullmatch(r'[a-z0-9.-]+\.(?:firebaseio\.com|firebasedatabase\.app)',u.netloc) or u.username or u.password: raise ConfigError('DB_CONFIG_INVALID')
            origins+=['https://'+u.netloc,'wss://'+u.netloc]
        origins+=['https://*.googleapis.com','https://*.firebaseapp.com','https://*.firebaseio.com','wss://*.firebaseio.com','https://*.firebasedatabase.app','wss://*.firebasedatabase.app','https://*.gstatic.com']
    return {'mode':mode,'env':env,'origins':origins}

# Google AI Studio exports a public web client configuration in this file.
# Do not infer secrets or copy unknown keys into environment variables.
def detect_embedded(root,plan,config):
    if config.get('mode','none')!='none' or 'firebase' not in plan.get('db_dependencies',[]):return config
    p=root/'firebase-applet-config.json'
    if not p.is_file() or p.is_symlink() or p.stat().st_size>32768:return config
    try:value=json.loads(p.read_text())
    except (ValueError,UnicodeError):raise ConfigError('DB_CONFIG_INVALID')
    if not isinstance(value,dict):raise ConfigError('DB_CONFIG_INVALID')
    allowed={'apiKey','projectId','authDomain','storageBucket','messagingSenderId','appId','databaseURL','measurementId','firestoreDatabaseId','oAuthClientId','recaptchaSiteKey'}
    if set(value)-allowed or any(not isinstance(v,str) or len(v)>4096 or re.search(r'(?i)(service.role|sb_secret_|-----BEGIN|sk_live_)',v) for v in value.values()):raise ConfigError('PRIVATE_OR_UNKNOWN_DB_KEY')
    keys={'apiKey':'API_KEY','projectId':'PROJECT_ID','authDomain':'AUTH_DOMAIN','storageBucket':'STORAGE_BUCKET','messagingSenderId':'MESSAGING_SENDER_ID','appId':'APP_ID','databaseURL':'DATABASE_URL','measurementId':'MEASUREMENT_ID'}
    return normalize({'mode':'firebase','env':{'VITE_FIREBASE_'+keys[k]:v for k,v in value.items() if k in keys and v}})
