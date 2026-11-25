import json
import tempfile
import unittest
from pathlib import Path
from dependency_cache import cache_key,cache_hit,verified_lock,dependency_profile,FINDONE_FULL

class CacheTest(unittest.TestCase):
    def test_identity_and_rejection(self):
        img="node@sha256:"+"a"*64
        a={"react":"^19.0.1","vite":"^8.3.0"}
        self.assertEqual(cache_key(a,img),cache_key(dict(reversed(list(a.items()))),img))
        self.assertNotEqual(cache_key(a,img),cache_key(a,"node@sha256:"+"b"*64))
        self.assertNotEqual(cache_key(a,img),cache_key({"react":"^19.0.2","vite":"^8.3.0"},img))
        with self.assertRaises(ValueError): cache_key({"vite":"file:../bad"},img)
        self.assertEqual(len(dependency_profile(FINDONE_FULL,True)),7)
        self.assertEqual(dependency_profile(a),a)
    def test_ready_marker(self):
        deps={"vite":"^8.3.0"}; img="node@sha256:"+"a"*64
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/cache_key(deps,img);p.mkdir()
            lock={"packages":{"":{"dependencies":deps},"node_modules/vite":{"resolved":"https://registry.npmjs.org/vite/-/vite-8.3.0.tgz","integrity":"sha512-YWJj"}}}
            f=p/"package-lock.json";f.write_text(json.dumps(lock))
            self.assertIsNone(cache_hit(tmp,deps,img))
            b=p/"node_modules"/".bin";b.mkdir(parents=True);(b/"vite").write_text("fake")
            (p/"READY.json").write_text(json.dumps({"key":p.name,"lock_sha256":verified_lock(f,deps)}))
            self.assertEqual(cache_hit(tmp,deps,img),p)
            lock["packages"]["node_modules/vite"]["resolved"]="https://example.com/vite.tgz"
            f.write_text(json.dumps(lock))
            self.assertIsNone(cache_hit(tmp,deps,img))
if __name__=="__main__": unittest.main(verbosity=2)
