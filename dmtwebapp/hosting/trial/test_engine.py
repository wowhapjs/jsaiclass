import io,json,tempfile,threading,unittest,urllib.request,urllib.error,zipfile
from pathlib import Path
from engine import Store,Error,inspect_and_extract,inspect
from server import create_servers

def archive(body='test',filename='index.html'):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr(filename,f'<html><body>{body}</body></html>')
    return b.getvalue()
class TrialTest(unittest.TestCase):
    def test_http_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            import socket
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            with socket.socket() as s:s.bind(('127.0.0.1',0));preview=s.getsockname()[1]
            m,p=create_servers(tmp,port,preview);origin=f'http://127.0.0.1:{port}';pv=f'http://127.0.0.1:{preview}/0000/test/'
            for server in (m,p):threading.Thread(target=server.serve_forever,daemon=True).start()
            def req(url,body=None,typ='application/json',expected=200,orig=origin):
                r=urllib.request.Request(url,data=body,headers={'Origin':orig,'Content-Type':typ})
                try:
                    with urllib.request.urlopen(r,timeout=5) as out:self.assertEqual(out.status,expected);return out.read()
                except urllib.error.HTTPError as e:self.assertEqual(e.code,expected);return e.read()
            def upload(body):return json.loads(req(origin+'/api/upload?filename=test.zip&folder=test&name=Test',body,'application/zip'))['version']
            def op(action,v,status=200,orig=origin):return req(origin+'/api/'+action,json.dumps({'folder':'test','version':v}).encode(),expected=status,orig=orig)
            try:
                self.assertIn(b'DMT WebApp',req(origin+'/'))
                self.assertEqual(upload(archive('v1')),1);self.assertEqual(upload(archive('v2')),2);self.assertEqual(upload(archive('v3')),3)
                req(pv,expected=404);op('serve',1);self.assertIn(b'v1',req(pv));self.assertIn(b'v3',req(pv+'versions/3/'));op('serve',3);self.assertIn(b'v3',req(pv));op('delete',3,400);op('rollback',1);self.assertIn(b'v1',req(pv));op('delete',2);req(pv+'versions/2/',expected=404);op('serve',2,400);op('serve',3,403,orig=f'http://127.0.0.1:{preview}');self.assertIn(b'v1',req(pv));req(origin+'/api/upload?filename=bad.zip&folder=test&name=Test',archive('bad','../escape'),'application/zip',400);self.assertIn(b'v1',req(pv));self.assertEqual(upload(archive('v5')),5);op('serve',5);self.assertIn(b'v5',req(pv));req(pv+'original.zip',expected=404);req(pv+'%2e%2e/',expected=404);op('rollback',3);self.assertIn(b'v3',req(pv));self.assertEqual(len(json.loads(req(origin+'/api/list'))['apps'][0]['versions']),5)
            finally:
                for server in (m,p):server.shutdown();server.server_close()
    def test_identical_zip_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);z=root/'same.zip';z.write_bytes(archive('same'))
            with Store(root/'data') as s:
                self.assertEqual(s.upload('0000','demo','Demo',z),1)
                self.assertEqual(s.upload('0000','demo','Demo',z),2)
                a=s.app('0000','demo')
                self.assertEqual(s.version(a,1)['artifact'],s.version(a,2)['artifact'])
                self.assertEqual(s.db.execute("SELECT action FROM events ORDER BY id DESC LIMIT 1").fetchone()[0],'cache_reused')
                s.serve('0000','demo',2);s.delete('0000','demo',1)
                self.assertIn('same',(s.resolve('0000','demo')/'index.html').read_text())
                self.assertEqual(s.upload('0001','demo','Demo',z),1)
                self.assertNotEqual(s.version(s.app('0001','demo'),1)['artifact'],s.version(a,2)['artifact'])
    def test_findone_inspection(self):
        sample=Path(__file__).parent/'samples'/'findone.zip'
        if not sample.exists(): self.skipTest('sample not included')
        with tempfile.TemporaryDirectory() as tmp:
            plan=inspect(inspect_and_extract(sample,Path(tmp)));self.assertEqual(plan['framework'],'vite');self.assertEqual(plan['database'],'browser');self.assertFalse(plan['lockfile'])
        with tempfile.TemporaryDirectory() as tmp:
            with Store(tmp) as s:
                with self.assertRaisesRegex(Error,'TRUSTED_BUILD_IMAGE_REQUIRED'):s.upload('0000','findone','FinDone',sample)
                a=s.app('0000','findone');self.assertIsNone(a['active']);self.assertEqual(s.version(a,1)['state'],'failed')
if __name__=='__main__': unittest.main(verbosity=2)
