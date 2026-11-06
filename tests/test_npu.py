import copy,hashlib,importlib.util,json,math,os,shutil,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
probe=load('npu_test',BASE/'npu/test.py');prepare=load('npu_prepare',BASE/'npu/prepare.py')
GOLDEN=json.loads((BASE/'npu/golden.json').read_text())
def valid():return dict(schema=1,cid=0x1000003b,devices=1,input_format=2,runs=[dict(case_index=i%2,milliseconds=.1,hardware_cycles=65000,scores=GOLDEN['cases'][i%2]['scores']) for i in range(6)])

class NpuValidationTests(unittest.TestCase):
 def test_alternating_hardware_results_match_two_independent_references(self):self.assertEqual(probe.assess(valid(),GOLDEN)['inferences'],6)
 def test_wrong_scores_hardware_cycles_identity_and_missing_runs_fail(self):
  variations=[]
  x=valid();x['cid']=1;variations.append(x)
  x=valid();x['runs'][1]['scores']=x['runs'][0]['scores'];variations.append(x)
  x=valid();x['runs'][2]['hardware_cycles']=0;variations.append(x)
  x=valid();x['runs'][2]['scores']=[float('nan')]*10;variations.append(x)
  x=valid();x['runs'].pop();variations.append(x)
  for item in variations:
   with self.assertRaises(ValueError):probe.assess(item,GOLDEN)
 def test_generated_input_matches_committed_reference(self):self.assertEqual(hashlib.sha256(prepare.synthetic_seven()).hexdigest(),GOLDEN['cases'][1]['input_sha256'])
 def test_manifest_tampering_is_detected(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);(r/'bin').mkdir();p=r/'bin/npu-probe';p.write_bytes(b'probe');(r/'manifest.json').write_text(json.dumps(dict(files={'bin/npu-probe':prepare.digest(p)})))
   probe.integrity(r);p.write_bytes(b'changed')
   with self.assertRaises(ValueError):probe.integrity(r)
 def test_fetch_size_hash_and_architecture_are_checked(self):
  def bad(url,entry):return b'wrong'
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):prepare.prepare(Path(d)/'runtime',bad)

class NativeProbeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.headers=Path(os.environ.get('NPU_SDK_HEADERS','/nonexistent'))
  if not (cls.headers/'vip_lite.h').is_file() or not shutil.which('cc'):raise unittest.SkipTest('NPU SDK headers/compiler unavailable')
  cls.tmp=tempfile.TemporaryDirectory();cls.work=Path(cls.tmp.name)
  h='static const double fake_scores[2][10]={'+','.join('{'+','.join(format(v,'.12g') for v in x['scores'])+'}' for x in GOLDEN['cases'])+'};\n'
  h+='static const unsigned short fake_half_scores[2][10]={'+','.join('{'+','.join(str(struct.unpack('<H',struct.pack('<e',v))[0]) for v in x['scores'])+'}' for x in GOLDEN['cases'])+'};\n'
  (cls.work/'fake_golden.h').write_text(h)
  cls.binary=cls.work/'probe'
  subprocess.run(['cc','-std=c11','-D_POSIX_C_SOURCE=200809L','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I'+str(cls.headers),'-I'+str(cls.work),str(BASE/'npu/probe.c'),str(BASE/'tests/fake_viplite.c'),'-lm','-o',str(cls.binary)],check=True,capture_output=True)
  decoder=cls.work/'decoder.c'
  decoder.write_text('#define main probe_main\n#include "'+str(BASE/'npu/probe.c')+'"\n#undef main\nint main(void){for(unsigned i=0;i<65536;i++){double v=binary16((uint16_t)i);if(fwrite(&v,sizeof(v),1,stdout)!=1)return 1;}return 0;}\n')
  cls.decoder=cls.work/'decoder'
  subprocess.run(['cc','-std=c11','-D_POSIX_C_SOURCE=200809L','-O2','-I'+str(cls.headers),'-I'+str(cls.work),str(decoder),str(BASE/'tests/fake_viplite.c'),'-lm','-o',str(cls.decoder)],check=True,capture_output=True)
  for i in range(2):(cls.work/str(i)).write_bytes(bytes([i])*784)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def run_probe(self,mode=''):
  return subprocess.run([str(self.binary),'model.nb',str(self.work/'0'),str(self.work/'1')],env=dict(os.environ,NPU_FAKE_MODE=mode),capture_output=True,text=True)
 def test_actual_c_api_lifecycle_alternates_inputs_and_outputs(self):
  r=self.run_probe();self.assertEqual(r.returncode,0,r.stderr)
  payload=json.loads(next(l[11:] for l in r.stdout.splitlines() if l.startswith('NPU_RESULT=')))
  self.assertEqual(probe.assess(payload,GOLDEN)['cases'],2)
  self.assertEqual(payload['output_format'],1)
 def test_every_fp16_bit_pattern_matches_python_ieee754_decoder(self):
  data=subprocess.run([str(self.decoder)],check=True,capture_output=True).stdout
  self.assertEqual(len(data),65536*8)
  for i in range(65536):
   expected=struct.unpack('<e',struct.pack('<H',i))[0];actual=struct.unpack_from('=d',data,i*8)[0]
   if math.isnan(expected):self.assertTrue(math.isnan(actual),hex(i))
   else:
    self.assertEqual(actual,expected,hex(i))
    if expected==0:self.assertEqual(math.copysign(1,actual),math.copysign(1,expected),hex(i))
 def test_fp32_output_remains_supported(self):
  r=self.run_probe('fp32');self.assertEqual(r.returncode,0,r.stderr)
  payload=json.loads(next(l[11:] for l in r.stdout.splitlines() if l.startswith('NPU_RESULT=')))
  self.assertEqual(payload['output_format'],0);self.assertEqual(probe.assess(payload,GOLDEN)['cases'],2)
 def test_tensor_and_mapping_failures_include_diagnostics(self):
  for mode,message in [('nonfinite','Nonfinite output'),('unsupported','Unsupported output'),('short_buffer','Unexpected buffer bytes'),('map_input','vip_map_buffer(input)'),('map_output','vip_map_buffer(output)')]:
   r=self.run_probe(mode);self.assertNotEqual(r.returncode,0,mode);self.assertIn(message,r.stderr)
 def test_api_failure_wrong_chip_missing_cycles_and_cleanup_errors_fail(self):
  for mode in ['init','prepare','run','cid','profile','cleanup']:
   self.assertNotEqual(self.run_probe(mode).returncode,0,mode)
 def test_stale_backend_outputs_are_rejected_by_numeric_validator(self):
  r=self.run_probe('stale');self.assertEqual(r.returncode,0)
  payload=json.loads(next(l[11:] for l in r.stdout.splitlines() if l.startswith('NPU_RESULT=')))
  with self.assertRaises(ValueError):probe.assess(payload,GOLDEN)
