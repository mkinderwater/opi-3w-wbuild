"""Real DTB edits and boot-provenance checks for the default GPU operating point."""
import hashlib,json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'scripts'))
from boot_manifest import snapshot
from board_profile import DTB
import gpu_opp

DTS='''/dts-v1/;
/ { model="sun60iw2"; compatible="xunlong,orangepi-4-pro","arm,sun60iw2p1";
 soc@3000000 {
  gpu@1800000 {compatible="img,gpu";gpu-supply=<&supply>;operating-points-v2=<&opps>;};
  opps:gpu-opp-table {opp@1008000000 {opp-hz=/bits/ 64 <1008000000>;opp-microvolt=<960000>;opp-microvolt-vfdefault=<960000>;};};
  twi@7083000 {pmu@36 {regulators@0 {supply:dcdc4 {regulator-name="axp8191-dcdc4";regulator-min-microvolt=<500000>;regulator-max-microvolt=<1540000>;};};};};
  i2s@2032000 {status="okay";pins="microphone-original";};
 }; cpu-opp-table {frequency=<2000000000>;voltage=<1000000>;};
};'''

@unittest.skipUnless(all(shutil.which(x) for x in ('dtc','fdtput')),'DT tools unavailable')
class GPUOperatingPoint(unittest.TestCase):
    def fixture(self,d):
        root=Path(d)/'root';path=root/'boot/dtb'/DTB;path.parent.mkdir(parents=True)
        src=Path(d)/'test.dts';src.write_text(DTS)
        subprocess.run(['dtc','-I','dts','-O','dtb','-o',str(path),str(src)],check=True,capture_output=True)
        (root/'boot/orangepiEnv.txt').write_text('fdtfile='+DTB+'\n')
        (root/'boot/uImage').write_bytes(b'original-kernel')
        return root,path,{'dtb':DTB,'dtb_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    def test_exact_gpu_changes_keep_kernel_env_cpu_microphone_and_original(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,profile=self.fixture(d);before=path.read_bytes();vendor=snapshot(root)
            configured=gpu_opp.apply(root,vendor,profile)
            original,oldnodes,oldreserve=gpu_opp.tree(before);after,nodes,reserve=gpu_opp.tree(path.read_bytes())
            changed={key for key in original.keys()|after.keys() if original.get(key)!=after.get(key)}
            self.assertEqual(changed,set(gpu_opp.CHANGES));self.assertEqual(nodes,oldnodes);self.assertEqual(reserve,oldreserve)
            self.assertEqual(after[('/soc@3000000/i2s@2032000','pins')],b'microphone-original\0')
            self.assertEqual(after[('/cpu-opp-table','voltage')],original[('/cpu-opp-table','voltage')])
            self.assertEqual({key for key in vendor if vendor[key]!=configured[key]},{str(path.relative_to(root))})
            data=root/'usr/share/opi-3w-wbuild'
            self.assertEqual((data/'gpu-opp-original.dtb').read_bytes(),before)
            self.assertEqual(json.loads((data/'board-profile.json').read_text())['vendor_dtb_sha256'],profile['dtb_sha256'])
            self.assertEqual(gpu_opp.authorized_boot(root,vendor),configured)
            (root/'boot/uImage').write_bytes(b'changed')
            with self.assertRaises(ValueError):gpu_opp.authorized_boot(root,vendor)
    def test_wrong_supply_or_opp_blocks_before_boot_mutation(self):
        for node,name,value in [(gpu_opp.GPU,'gpu-supply','99'),(gpu_opp.OPP+'/opp@1008000000','opp-microvolt','1000000')]:
            with self.subTest(property=name),tempfile.TemporaryDirectory() as d:
                root,path,profile=self.fixture(d)
                subprocess.run(['fdtput','-t','u',str(path),node,name,value],check=True)
                profile['dtb_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();before=snapshot(root)
                with self.assertRaises(ValueError):gpu_opp.apply(root,before,profile)
                self.assertEqual(snapshot(root),before)
    def test_shared_supply_is_rejected_before_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,profile=self.fixture(d)
            properties,_,_=gpu_opp.tree(path.read_bytes())
            ref=gpu_opp.number(properties,gpu_opp.REG,'phandle')
            subprocess.run(['fdtput','-t','u',str(path),'/soc@3000000/i2s@2032000','vdd-supply',str(ref)],check=True)
            profile['dtb_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();before=snapshot(root)
            with self.assertRaises(ValueError):gpu_opp.apply(root,before,profile)
            self.assertEqual(snapshot(root),before)
    def test_unrelated_dt_change_and_manifest_bypass_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root,path,profile=self.fixture(d);vendor=snapshot(root)
            gpu_opp.apply(root,vendor,profile)
            subprocess.run(['fdtput','-t','s',str(path),'/soc@3000000/i2s@2032000','pins','changed'],check=True)
            data=root/'usr/share/opi-3w-wbuild';(data/'configured-boot.json').write_text(json.dumps(snapshot(root)))
            with self.assertRaises(ValueError):gpu_opp.authorized_boot(root,vendor)

class OperatingPointReadback(unittest.TestCase):
    def test_actual_clock_and_voltage_and_missing_readback(self):
        from test_verification import FakeSystem,v
        with tempfile.TemporaryDirectory() as d:
            s=FakeSystem(d);verify=v.Verification(s);verify.gpu_operating_point()
            self.assertTrue(verify.report['gpu_operating_point']['confirmed'])
            s.path('/sys/class/regulator/regulator.6/microvolts').write_text('800000')
            verify=v.Verification(s);verify.gpu_operating_point()
            self.assertFalse(verify.report['gpu_operating_point']['confirmed'])
            self.assertEqual(verify.report['checks'][-1]['status'],'FAIL')
            s.path('/sys/class/regulator/regulator.6/microvolts').write_text('960000')
            s.path('/sys/kernel/debug/clk/clk_summary').unlink()
            verify=v.Verification(s);verify.gpu_operating_point()
            self.assertFalse(verify.report['gpu_operating_point']['confirmed'])
            self.assertEqual(verify.report['checks'][-1]['status'],'WARN')
