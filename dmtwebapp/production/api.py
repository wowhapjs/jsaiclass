#!/usr/bin/env python3
"""DMT management and isolated app origin gateway; listen on loopback only."""
import base64,hashlib,html,json,mimetypes,os,re,secrets,shutil,socket,threading,urllib.parse,uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from pg import call
from db_config import normalize,ConfigError
HERE=Path(__file__).resolve().parent
BASE=Path(os.environ.get('DMT_DATA','/var/lib/web-manager/site-media/jsaiclass/dmtwebapp-prod'))
PORT=int(os.environ.get('DMT_PORT','31107'))
ORIGIN=os.environ.get('DMT_MANAGER_ORIGIN','https://jsaiclass.duckdns.org')
MANAGER=urllib.parse.urlsplit(ORIGIN).netloc
HOST=re.compile(r'dmt-[a-f0-9]{32}\.jsaiclass\.duckdns\.org')
FOLDER=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}')
STUDENT=re.compile(r'\d{4}')
RESERVED={'api','versions','login','logout','admin','assets','trial'}
COOKIE='__Host-dmt-session'; BROWSER='__Host-dmt-browser'
DEMO_HOST='dmt-00000000000000000000000000000000.jsaiclass.duckdns.org'
DEMO_ROOT=Path('/var/lib/web-manager/site-media/jsaiclass/dmtwebapp-trial/findone')
MAX_ZIP=50*1024**2
uploads=threading.BoundedSemaphore(4)
requests=threading.BoundedSemaphore(32)
IP_SALT=os.environ.get('DMT_IP_SALT','dmt-private-rate-limit')
def digest(t):return hashlib.sha256(t.encode()).hexdigest()
class Bad(Exception):
    def __init__(self,code,status=400):self.code=code;self.status=status
def clean_folder(s):
    if not isinstance(s,str) or not FOLDER.fullmatch(s) or s.lower() in RESERVED:raise Bad('INVALID_FOLDER')
    return s
def clean_text(s,limit,required=False):
    if not isinstance(s,str) or len(s)>limit or any(ord(c)<32 and c not in '\n\t' for c in s) or (required and not s.strip()):
        raise Bad('INVALID_TEXT')
    return s.strip()
class Handler(BaseHTTPRequestHandler):
    server_version='DMT'
    def setup(self):
        super().setup();self.connection.settimeout(35)
    def log_message(self,*args):pass
    def reply(self,status,data=b'',typ='application/json; charset=utf-8',headers=None):
        if isinstance(data,dict):data=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
        self.send_response(status);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer');self.send_header('Cross-Origin-Resource-Policy','same-origin')
        self.send_header('X-Frame-Options','DENY')
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers()
        if self.command!='HEAD' and data:self.wfile.write(data)
    def cookie(self,name):
        try:
            c=SimpleCookie(self.headers.get('Cookie',''));v=c[name].value
            return v if re.fullmatch(r'[A-Za-z0-9_-]{43}',v) else ''
        except Exception:return ''
    def token(self):return digest(self.cookie(COOKIE)) if self.cookie(COOKIE) else ''
    def host(self):return self.headers.get('Host','').lower()
    def origin(self,expected):
        if self.headers.get('Origin')!=expected:raise Bad('ORIGIN_REJECTED',403)
    def read(self,max_size):
        if self.headers.get('Transfer-Encoding'):raise Bad('CONTENT_LENGTH_REQUIRED')
        try:n=int(self.headers.get('Content-Length','0'))
        except ValueError:raise Bad('CONTENT_LENGTH_REQUIRED')
        if not 0<n<=max_size:raise Bad('SIZE_LIMIT',413)
        body=self.rfile.read(n)
        if len(body)!=n:raise Bad('TRUNCATED_BODY')
        return body
    def body(self,max_size=16384):
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise Bad('JSON_REQUIRED')
        try:p=json.loads(self.read(max_size))
        except (ValueError,UnicodeError):raise Bad('INVALID_JSON')
        if not isinstance(p,dict):raise Bad('INVALID_JSON')
        return p
    def session(self):
        p=call('dashboard',{'token':self.token()})
        if p.get('error'):raise Bad('AUTH_REQUIRED',401)
        return p
    def result(self,p):
        if p.get('error'):
            code=p['error'];raise Bad(code,401 if code in ('AUTH_REQUIRED','LOGIN_FAILED') else 429 if code in ('RATE_LIMIT','QUEUE_FULL','STUDENT_QUEUE_FULL') else 409)
        return p
    def redirect(self,path):
        self.reply(302,b'',headers={'Location':path})
    def manager_get(self,path):
        prefix='/dmtwebapp'
        if path==prefix:self.redirect(prefix+'/');return
        if path==prefix+'/api/me':self.reply(200,self.session());return
        if path in (prefix+'/ui.js',prefix+'/ui.css'):
            f=HERE/path.rsplit('/',1)[1];self.reply(200,f.read_bytes(),mimetypes.guess_type(f.name)[0]);return
        if path==prefix+'/':
            self.page();return
        parts=path[len(prefix):].strip('/').split('/') if path.startswith(prefix+'/') else []
        if len(parts)==1 and STUDENT.fullmatch(parts[0]):
            try:s=self.session()
            except Bad:self.redirect(prefix+'/');return
            if s['folder']!=parts[0]:raise Bad('AUTH_REQUIRED',403)
            self.page();return
        if len(parts) in (2,4) and STUDENT.fullmatch(parts[0]) and FOLDER.fullmatch(parts[1]):
            p={'student':parts[0],'folder':parts[1]}
            if len(parts)==4:
                if parts[2]!='versions' or not re.fullmatch(r'[1-9]\d{0,8}',parts[3]):raise Bad('NOT_FOUND',404)
                s=self.session()
                if s['folder']!=parts[0]:raise Bad('AUTH_REQUIRED',403)
                p['version']=int(parts[3])
            app=call('resolve_app',p)
            if not app:raise Bad('NOT_FOUND',404)
            suffix='/__dmt_versions/'+str(app['version'])+'/' if 'version' in p else '/'
            self.redirect('https://'+app['host']+suffix);return
        raise Bad('NOT_FOUND',404)
    def page(self):
        self.reply(200,(HERE/'index.html').read_bytes(),'text/html; charset=utf-8',{
          'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
          'Permissions-Policy':'camera=(), microphone=(), geolocation=()'})
    def upload(self):
        self.session()
        if self.headers.get('Content-Type')!='application/zip':raise Bad('ZIP_REQUIRED')
        if self.headers.get('Transfer-Encoding'):raise Bad('CONTENT_LENGTH_REQUIRED')
        try:n=int(self.headers.get('Content-Length','0'))
        except ValueError:raise Bad('CONTENT_LENGTH_REQUIRED')
        if not 0<n<=MAX_ZIP:raise Bad('ZIP_SIZE_LIMIT',413)
        try:
            raw=self.headers.get('X-DMT-Meta','')
            if len(raw)>24000:raise ValueError()
            p=json.loads(base64.b64decode(raw,validate=True))
            if not isinstance(p,dict):raise ValueError()
        except (ValueError,TypeError,UnicodeError):raise Bad('INVALID_METADATA')
        p={'folder':clean_folder(p.get('folder')),'name':clean_text(p.get('name'),100,True),
           'filename':clean_text(p.get('filename'),255,True),'title':clean_text(p.get('title',''),100),
           'notes':clean_text(p.get('notes',''),1000),'config':normalize(p.get('config'))}
        if '/' in p['filename'] or '\\' in p['filename'] or not p['filename'].lower().endswith('.zip'):raise Bad('ZIP_REQUIRED')
        if not uploads.acquire(blocking=False):raise Bad('UPLOAD_BUSY',429)
        storage=str(uuid.uuid4());target=BASE/'incoming'/(storage+'.zip');keep=False;unknown=False
        try:
            if shutil.disk_usage(BASE).free<3*1024**3:raise Bad('DISK_RESERVE_LIMIT',503)
            with target.open('xb') as out:
                left=n
                while left:
                    chunk=self.rfile.read(min(left,65536))
                    if not chunk:raise Bad('TRUNCATED_UPLOAD')
                    out.write(chunk);left-=len(chunk)
            # The file is complete before its queue row is visible.
            target.chmod(0o640)
            p.update(token=self.token(),storage=storage,bytes=n)
            unknown=True
            response=call('enqueue',p);unknown=False
            result=self.result(response);keep=True
            self.reply(202,result)
        finally:
            # If the database transport failed, retain the spool for reconciliation
            # rather than deleting a file that might already be committed.
            if not keep and not unknown:target.unlink(missing_ok=True)
            uploads.release()
    def manager_post(self,path):
        self.origin(ORIGIN)
        prefix='/dmtwebapp/api/'
        if path==prefix+'login':
            p=self.body();phone=p.get('phone','')
            if not isinstance(phone,str) or not re.fullmatch(r'07\d{8}',phone):raise Bad('LOGIN_FAILED',401)
            raw=secrets.token_urlsafe(32)
            ip=self.headers.get('X-Forwarded-For',self.client_address[0]).split(',')[-1].strip()
            result=self.result(call('login',{'phone':phone,'token':digest(raw),'ip':digest(IP_SALT+ip)}))
            self.reply(200,result,headers={'Set-Cookie':f'{COOKIE}={raw}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=43200'});return
        if path==prefix+'upload':self.upload();return
        op=path[len(prefix):] if path.startswith(prefix) else ''
        if op not in ('serve','rollback','delete','delete_app','language','logout'):raise Bad('NOT_FOUND',404)
        p=self.body();payload={'action':op,'token':self.token()}
        if op=='language':
            if p.get('language') not in ('en','ko'):raise Bad('INVALID_LANGUAGE')
            payload['language']=p['language']
        elif op!='logout':
            payload['folder']=clean_folder(p.get('folder'))
            if op!='delete_app':
                v=p.get('version')
                if type(v)!=int or not 1<=v<=999999999:raise Bad('INVALID_VERSION')
                payload['version']=v
        result=self.result(call('student_action',payload))
        self.reply(200,result,headers={'Set-Cookie':f'{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0'} if op=='logout' else None)
    def preview(self,path):
        parts=path.strip('/').split('/') if path!='/' else []
        if any(not p or p.startswith('.') or '\\' in p or ':' in p or any(ord(c)<32 for c in p) for p in parts):raise Bad('NOT_FOUND',404)
        query={'host':self.host()}
        if parts and parts[0]=='__dmt_versions':
            if len(parts)<2 or not re.fullmatch(r'[1-9]\d{0,8}',parts[1]):raise Bad('NOT_FOUND',404)
            query['version']=int(parts[1]);parts=parts[2:]
            if not parts and not path.endswith('/'):self.redirect(path+'/');return
        demo=self.host()==DEMO_HOST and DEMO_ROOT.is_dir()
        app={'version':1} if demo and query.get('version',1)==1 else call('resolve_app',query)
        if not app:raise Bad('NOT_FOUND',404)
        if path=='/':
            self.redirect('/__dmt_versions/'+str(app['version'])+'/');return
        root=DEMO_ROOT if demo else BASE/'artifacts'/str(uuid.UUID(app['artifact']))/'web'
        p=root.joinpath(*parts) if parts else root/'index.html'
        if p.is_dir():p=p/'index.html'
        if not p.is_file() or not p.resolve().is_relative_to(root.resolve()) or p.is_symlink():raise Bad('NOT_FOUND',404)
        if p.stat().st_size>MAX_ZIP:raise Bad('NOT_FOUND',404)
        typ=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        # The app is intentionally allowed browser-side HTTPS APIs, but never
        # shares the manager's origin or cookies. Backend access remains scoped.
        csp="default-src 'none'; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https:; img-src 'self' data: blob: https:; font-src 'self' data: https:; connect-src 'self' https: wss:; media-src 'self' blob: data: https:; worker-src blob:; frame-src https:; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self' https:"
        self.reply(200,p.read_bytes(),typ,{'Content-Security-Policy':csp,'Permissions-Policy':'camera=(self), microphone=(self), geolocation=(self), payment=()'})
    def app_data(self,path):
        if path!='/__dmt_data':raise Bad('NOT_FOUND',404)
        self.origin('https://'+self.host())
        app=call('resolve_app',{'host':self.host()})
        if not app or app['database']!='managed':raise Bad('DB_NOT_ENABLED',404)
        p=self.body(70000)
        op=p.get('op');key=clean_text(p.get('key'),100,True)
        if op not in ('get','put','delete'):raise Bad('BAD_ACTION')
        raw=self.cookie(BROWSER) or secrets.token_urlsafe(32)
        data={'app':app['app'],'browser':digest(raw),'key':key,'op':op}
        if op=='put':
            if 'value' not in p or len(json.dumps(p['value'],ensure_ascii=False).encode())>64000:raise Bad('VALUE_LIMIT')
            data['value']=p['value']
        result=self.result(call('browser_data',data))
        self.reply(200,result,headers={'Set-Cookie':f'{BROWSER}={raw}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=31536000'})
    def dispatch(self):
        if not requests.acquire(blocking=False):self.reply(503,{'error':'BUSY'});return
        try:
            url=urllib.parse.urlsplit(self.path)
            if url.scheme or url.netloc:raise Bad('BAD_PATH')
            path=urllib.parse.unquote(url.path,errors='strict')
            if '\x00' in path:raise Bad('BAD_PATH')
            host=self.host()
            if host==f'127.0.0.1:{PORT}' and path=='/internal/tls' and self.command=='GET':
                d=urllib.parse.parse_qs(url.query).get('domain',[''])[0]
                allowed=bool(HOST.fullmatch(d) and ((d==DEMO_HOST and DEMO_ROOT.is_dir()) or call('tls_allowed',{'domain':d}).get('allowed')))
                self.reply(200 if allowed else 403,{'allowed':allowed});return
            if host==f'127.0.0.1:{PORT}' and path=='/internal/health' and self.command=='GET':self.reply(200,{'ok':True});return
            if host==MANAGER:
                if self.command in ('GET','HEAD'):self.manager_get(path)
                elif self.command=='POST':self.manager_post(path)
                else:raise Bad('METHOD_NOT_ALLOWED',405)
            elif HOST.fullmatch(host):
                if self.command in ('GET','HEAD'):self.preview(path)
                elif self.command=='POST':self.app_data(path)
                else:raise Bad('METHOD_NOT_ALLOWED',405)
            else:raise Bad('HOST_REJECTED',404)
        except Bad as e:self.reply(e.status,{'error':e.code})
        except ConfigError as e:self.reply(400,{'error':str(e)})
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass
        except Exception:self.reply(500,{'error':'INTERNAL_ERROR'})
        finally:requests.release()
    do_GET=do_POST=do_HEAD=dispatch

if __name__=='__main__':
    os.umask(0o027)
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    server.daemon_threads=True;server.request_queue_size=32
    print('DMT gateway ready',PORT,flush=True);server.serve_forever()
