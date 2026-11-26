import json, tempfile, unittest
from pathlib import Path
from db_config import detect_embedded,ConfigError
from auto_cache import allowed_connect
from worker import profile
from dependency_cache import FINDONE_FULL,FINDONE_KEYS
class Tests(unittest.TestCase):
 def test_firebase(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'firebase-applet-config.json';p.write_text(json.dumps({'apiKey':'public-web-key','projectId':'demo-class','authDomain':'demo-class.firebaseapp.com','appId':'1:123:web:456','firestoreDatabaseId':'(default)'}))
   plan={'db_dependencies':['firebase']}
   self.assertEqual(detect_embedded(Path(tmp),plan,{'mode':'none'})['mode'],'firebase')
   p.write_text(json.dumps({'apiKey':'public','projectId':'demo-class','private_key':'private'}))
   with self.assertRaises(ConfigError):detect_embedded(Path(tmp),plan,{'mode':'none'})
 def test_relay(self):
  self.assertTrue(allowed_connect(b'CONNECT registry.npmjs.org:443 HTTP/1.1'))
  for x in (b'CONNECT 127.0.0.1:5432 HTTP/1.1',b'CONNECT registry.npmjs.org.evil:443 HTTP/1.1',b'GET / HTTP/1.1'):
   self.assertFalse(allowed_connect(x))
 def test_profile(self):
  d={**FINDONE_FULL,'firebase':'^13.4.0','eslint':'^10.15.0','@firebase/eslint-plugin-security-rules':'^0.0.2'}
  self.assertEqual(set(profile(d)),FINDONE_KEYS|{'firebase'})
  d['new-package']='^1.0.0';self.assertIn('new-package',profile(d))
if __name__=='__main__':unittest.main(verbosity=2)
