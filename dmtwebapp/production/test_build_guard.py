import unittest,tempfile
from pathlib import Path
import worker
from build_guard import reasons,owned
class Tests(unittest.TestCase):
 def test_gate(self):
  s=dict(steal=0,iowait=0,cpu_pressure=0,io_full=0,memory_full=0,available_mb=450,swap_free_mb=900,disk_free=25*1024**3)
  self.assertEqual(reasons(s),[])
  for k,v,reason in [('steal',78,'CPU_STEAL'),('iowait',83,'IO_WAIT'),('io_full',40,'IO_PRESSURE'),('available_mb',100,'RAM_RESERVE')]:
   self.assertIn(reason,reasons(dict(s,**{k:v})))
 def test_scope(self):
  base=Path('/var/lib/dmt-prod')
  self.assertTrue(owned(base,[{'Type':'bind','Destination':'/work','Source':'/var/lib/dmt-prod/work/build-a'}]))
  self.assertFalse(owned(base,[{'Type':'bind','Destination':'/work','Source':'/var/lib/dmt-prod-other/work/build-a'}]))
  self.assertFalse(owned(base,[{'Type':'bind','Destination':'/work','Source':'/var/lib/dmt-stage/work/build-a'}]))
 def test_timeout(self):
  self.assertEqual(worker.BUILD_TIMEOUT,1200)
if __name__=='__main__':unittest.main(verbosity=2)
