#!/usr/bin/env python3
"""Loopback-only trial. No student roster or production credentials."""
import argparse, json, mimetypes, os, tempfile, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from engine import Store, Error, MAX_ZIP
HERE=Path(__file__).resolve().parent

def create_servers(base, port, preview_port, image=None):
    origin=f'http://127.0.0.1:{port}'; preview=f'http://127.0.0.1:{preview_port}'
    class Handler(BaseHTTPRequestHandler):
        def send(self,code,data,typ='application/json; charset=utf-8'):
            if isinstance(data,dict): data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(code);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(data)
        def log_message(self,*args): pass
        def validhost(self): return self.headers.get('Host')==f'127.0.0.1:{port}'
        def do_GET(self):
            if not self.validhost(): self.send(403,{'error':'INVALID_HOST'});return
            try:
                url=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(url.query)
                if url.path=='/': self.send(200,(HERE/'index.html').read_bytes(),'text/html; charset=utf-8');return
                if url.path=='/api/list':
                    with Store(base) as store:
                        db=store.db
                        apps=[]
                        for a in db.execute('SELECT * FROM apps ORDER BY id'):
                            d=dict(a);d['versions']=[dict(v) for v in db.execute('SELECT version,zip_name,title,notes,state,error,created FROM versions WHERE app=? ORDER BY version DESC',(a['id'],))];d['url']=f'{preview}/{a["student"]}/{a["folder"]}/';apps.append(d)
                    self.send(200,{'apps':apps,'preview':preview});return
                self.send(404,{'error':'NOT_FOUND'})
            except Exception: self.send(500,{'error':'INTERNAL_ERROR'})
        def do_POST(self):
            if not self.validhost() or self.headers.get('Origin')!=origin: self.send(403,{'error':'ORIGIN_REJECTED'});return
            s=None
            try:
                url=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(url.query);n=int(self.headers.get('Content-Length','0'));s=Store(base)
                if url.path=='/api/upload':
                    if not 0<n<=MAX_ZIP: raise Error('ZIP_SIZE_LIMIT')
                    if self.headers.get('Content-Type')!='application/zip': raise Error('ZIP_REQUIRED')
                    val=lambda k,default='':q.get(k,[default])[0]
                    with tempfile.TemporaryDirectory() as t:
                        name=val('filename','app.zip').replace('\\','/').split('/')[-1]
                        if not name.lower().endswith('.zip') or len(name)>255: raise Error('ZIP_REQUIRED')
                        z=Path(t)/name
                        with z.open('wb') as f:
                            left=n
                            while left:
                                chunk=self.rfile.read(min(left,65536))
                                if not chunk: raise Error('TRUNCATED_UPLOAD')
                                f.write(chunk);left-=len(chunk)
                        version=s.upload('0000',val('folder'),val('name')[:100],z,val('title')[:100],val('notes')[:1000],image)
                    self.send(200,{'version':version,'status':'ready'});return
                if url.path not in ('/api/serve','/api/rollback','/api/delete') or not 0<n<8192: raise Error('BAD_REQUEST')
                if self.headers.get('Content-Type')!='application/json': raise Error('JSON_REQUIRED')
                d=json.loads(self.rfile.read(n));v=int(d['version']);folder=d['folder'];getattr(s,url.path.rsplit('/',1)[1])('0000',folder,v);self.send(200,{'ok':True})
            except (Error,ValueError,KeyError,TypeError) as e: self.send(400,{'error':str(e) if isinstance(e,Error) else 'BAD_REQUEST'})
            except Exception: self.send(500,{'error':'INTERNAL_ERROR'})
            finally:
                if s is not None:s.close()
    class Preview(Handler):
        def do_POST(self): self.send(405,{'error':'READ_ONLY'})
        def do_GET(self):
            if self.headers.get('Host')!=f'127.0.0.1:{preview_port}': self.send(403,{'error':'INVALID_HOST'});return
            try:
                path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path);parts=path.strip('/').split('/')
                if len(parts)<2 or parts[0]!='0000' or any(x in ('.','..','') or x.startswith('.') or '\\' in x for x in parts): raise Error('NOT_FOUND')
                student,folder=parts[:2];tail=parts[2:];v=None
                if tail and tail[0]=='versions':
                    if len(tail)<2: raise Error('NOT_FOUND')
                    v=int(tail[1]);tail=tail[2:]
                with Store(base) as store:root=store.resolve(student,folder,v)
                p=root.joinpath(*tail) if tail else root/'index.html'
                if p.is_dir(): p=p/'index.html'
                if not p.is_file() or not p.resolve().is_relative_to(root.resolve()) or p.is_symlink(): raise Error('NOT_FOUND')
                self.send(200,p.read_bytes(),mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
            except Exception: self.send(404,{'error':'NOT_FOUND'})
    return ThreadingHTTPServer(('127.0.0.1',port),Handler),ThreadingHTTPServer(('127.0.0.1',preview_port),Preview)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',default=str(HERE/'trial-data'));p.add_argument('--port',type=int,default=8765);p.add_argument('--preview-port',type=int,default=8766);p.add_argument('--image');a=p.parse_args()
    m,v=create_servers(a.data,a.port,a.preview_port,a.image);threading.Thread(target=v.serve_forever,daemon=True).start();print(f'Trial: http://127.0.0.1:{a.port}/ (local only)',flush=True)
    try: m.serve_forever()
    except KeyboardInterrupt: pass
    finally: m.server_close();v.shutdown();v.server_close()
