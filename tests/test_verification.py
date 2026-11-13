import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import zlib
import sys
import tarfile
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'lib'))
sys.path.insert(0,str(BASE/'scripts'))
from boot_manifest import snapshot as boot_snapshot
spec=importlib.util.spec_from_file_location('verification',BASE/'overlay/opi-3w-wbuild-verify.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)


class FakeSystem(v.System):
    def __init__(self,root):
        super().__init__(root);self.calls=[];self.kernel='6.6.98-sun60iw2';self.fail_opencl=False;self.fake_success=False;self.inactive='';self.hardware_ok=True;self.ddk='24.2@6603887'
        def put(name,data):
            p=self.path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
        put('/proc/device-tree/model','Orange Pi Zero3W\x00')
        put('/proc/device-tree/compatible','xunlong,orangepi-zero3w\x00allwinner,sun60iw2p1\x00')
        put('/etc/os-release','ID=debian\nVERSION_ID="13"\n')
        put('/usr/share/opi-3w-wbuild/layout.json',json.dumps({'filesystem':{'uuid':'root-uuid'}}))
        put('/var/lib/opi-3w-wbuild/wifi-interface','wlan0\n')
        put('/etc/opi-3w-wbuild-release','opi-3w-wbuild test')
        put('/etc/machine-id','a'*32)
        put('/var/lib/opi-3w-wbuild/configured','yes')
        put('/boot/orangepiEnv.txt','rootdev=PARTUUID=12345678-01\nfdtfile=allwinner/sun60i-a733-orangepi-zero3w.dtb\n')
        put('/boot/dtb/allwinner/sun60i-a733-orangepi-zero3w.dtb','known vendor DTB')
        put('/usr/share/opi-3w-wbuild/board-profile.json',json.dumps({
            'board':'Orange Pi Zero 3W','dtb':'allwinner/sun60i-a733-orangepi-zero3w.dtb',
            'model':'Orange Pi Zero3W','compatible':['xunlong,orangepi-zero3w','allwinner,sun60iw2p1'],
            'dtb_sha256':hashlib.sha256(b'known vendor DTB').hexdigest()}))
        payload=b'initramfs'
        header=bytearray(struct.pack('>7I4B32s',0x27051956,0,0,len(payload),0,0,zlib.crc32(payload)&0xffffffff,5,2,3,1,b'test'))
        struct.pack_into('>I',header,4,zlib.crc32(header)&0xffffffff)
        self.path('/boot/uInitrd').write_bytes(header+payload)
        put('/usr/share/opi-3w-wbuild/configured-boot.json',json.dumps(boot_snapshot(self.root)))
        put('/opt/opi-3w-wbuild-powervr/lib/test.so','library bytes')
        put('/opt/opi-3w-wbuild-powervr/manifest.json',json.dumps({'kernel_abi':self.kernel,'files':{'opt/opi-3w-wbuild-powervr/lib/test.so':hashlib.sha256(b'library bytes').hexdigest()}}))
        put('/proc/meminfo','MemTotal: 900000 kB\nMemAvailable: 600000 kB\nCmaTotal: 65536 kB\nCmaFree: 60000 kB\n')
        put('/sys/class/thermal/thermal_zone0/temp','45000')
        from gpu_opp import CHANGES
        for (node,name),value in CHANGES.items():
            path=self.path('/proc/device-tree'+node+'/'+name);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(struct.pack('>I',value))
        put('/usr/share/opi-3w-wbuild/gpu-opp.json',json.dumps({'frequency_hz':1008000000,'voltage_uv':960000,
            'changes':[{'node':node,'property':name,'value':value} for (node,name),value in CHANGES.items()]}))
        put('/sys/class/regulator/regulator.6/name','axp8191-dcdc4')
        put('/sys/class/regulator/regulator.6/microvolts','960000')
        put('/sys/kernel/debug/clk/clk_summary','gpu0 1 1 0 1008000000 0\n')
    def run(self,*args):
        self.calls.append(args);code=0;out=''
        if args==('uname','-m'):out='aarch64\n'
        elif args==('uname','-r'):out=self.kernel+'\n'
        elif args[:2]==('systemctl','is-active'):
            code=3 if args[2]==self.inactive else 0;out='inactive' if code else 'active'
        elif args[0]=='timedatectl':out='yes'
        elif args[0]=='ssh-keygen':out='256 SHA256:public-key opi-3w-wbuild ED25519'
        elif args[0]=='ip':out=json.dumps([{'addr_info':[{'local':'192.168.1.2','scope':'global'}]}])
        elif args[0]=='findmnt':
            kind='ext4' if '/' in args else 'vfat'
            out=json.dumps({'filesystems':[{'source':'/dev/mmcblk0p1','fstype':kind,'options':'rw,noatime'}]})
        elif args[0]=='df':out='SD root mounted'
        elif args[0]=='blkid':out='root-uuid' if 'UUID' in args else '12345678-01'
        elif args[0]=='opi-3w-wbuild-expand':out=json.dumps({'complete':True})
        elif args[0]=='bash':code=0 if self.hardware_ok else 1;out='' if self.hardware_ok else 'boot/uImage: FAILED'
        elif args[0]=='timeout':
            if args[-1].endswith('opencl-check'):
                code=1 if self.fail_opencl else 0
                out='FAIL: wrong numerical result' if code else ('placeholder' if self.fake_success else 'PASS: PowerVR BXM-4-64 compiled and executed an OpenCL kernel; results verified')
            else:out='PASS: PowerVR BXM-4-64 executed a Vulkan compute shader; results verified'
        elif args[0]=='cat':out=self.ddk
        elif args[0]=='dmesg':out='GPU initialized\nvipcore readiness\nunrelated line'
        return dict(code=code,output=out,elapsed_ms=1)


class VerificationTests(unittest.TestCase):
    def exercise(self,modify=None):
        with tempfile.TemporaryDirectory() as d:
            system=FakeSystem(d)
            if modify:modify(system)
            report=v.Verification(system).run()
            return report,system.calls
    def npu_fixture(self,system,success=True):
        path=system.path('/opt/opi-3w-wbuild-npu/manifest.json');path.parent.mkdir(parents=True);path.write_text('{}')
        old_run=system.run
        def run(*args):
            if args and args[0]=='opi-3w-wbuild-npu-test':
                system.calls.append(args)
                data=dict(status='PASS' if success else 'FAIL',npu_inference_validated=success,validation={'inferences':6,'cases':2})
                if not success:data['error']='Numerical result mismatch'
                return dict(code=0 if success else 1,output=json.dumps(data),elapsed_ms=1)
            return old_run(*args)
        system.run=run
    def test_npu_success_is_reported_only_when_probe_validates_inference(self):
        report,calls=self.exercise(lambda system:self.npu_fixture(system))
        self.assertTrue(report['build_passed']);self.assertTrue(report['npu_inference_validated'])
        self.assertEqual({c['name']:c['status'] for c in report['checks']}['npu_inference'],'PASS')
    def test_npu_numerical_failure_fails_full_verification(self):
        report,calls=self.exercise(lambda system:self.npu_fixture(system,False))
        self.assertFalse(report['build_passed']);self.assertFalse(report['npu_inference_validated'])
    def test_npu_does_not_execute_after_boot_integrity_failure(self):
        def prepare(system):self.npu_fixture(system);system.hardware_ok=False
        report,calls=self.exercise(prepare)
        self.assertFalse(report['npu_inference_validated'])
        self.assertFalse(any(c and c[0]=='opi-3w-wbuild-npu-test' for c in calls))
    def test_healthy_build_passes_without_claiming_npu(self):
        report,calls=self.exercise()
        self.assertTrue(report['build_passed'],report['checks'])
        self.assertFalse(report['npu_inference_validated'])
        self.assertEqual({c['name']:c['status'] for c in report['checks']}['npu_inference'],'NOT_TESTED')
        self.assertEqual(report['before_compute']['memory']['CmaFree'],'60000 kB')
        self.assertEqual(sum(c[0]=='timeout' for c in calls),2)
    def test_bad_opencl_does_not_skip_vulkan_or_pass(self):
        report,calls=self.exercise(lambda s:setattr(s,'fail_opencl',True))
        self.assertFalse(report['build_passed'])
        states={c['name']:c['status'] for c in report['checks']}
        self.assertEqual(states['opencl_compute'],'FAIL');self.assertEqual(states['vulkan_compute'],'PASS')
    def test_zero_exit_without_numeric_success_is_failure(self):
        report,_=self.exercise(lambda s:setattr(s,'fake_success',True))
        self.assertFalse(report['build_passed'])
    def test_changed_runtime_blocks_execution(self):
        report,calls=self.exercise(lambda s:s.path('/opt/opi-3w-wbuild-powervr/lib/test.so').write_text('changed'))
        self.assertFalse(report['build_passed'])
        self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_wrong_kernel_blocks_execution(self):
        report,calls=self.exercise(lambda s:setattr(s,'kernel','wrong-kernel'))
        self.assertFalse(report['build_passed']);self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_changed_initramfs_blocks_compute(self):
        report,calls=self.exercise(lambda s:s.path('/boot/uInitrd').write_bytes(b'changed initramfs'))
        self.assertFalse(report['build_passed'])
        self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_preserved_uuid_rootdev_is_supported(self):
        def modify(s):
            s.path('/boot/orangepiEnv.txt').write_text('rootdev=UUID=root-uuid\nfdtfile=allwinner/sun60i-a733-orangepi-zero3w.dtb\n')
            s.path('/usr/share/opi-3w-wbuild/configured-boot.json').write_text(json.dumps(boot_snapshot(s.root)))
        report,_=self.exercise(modify)
        self.assertTrue(report['build_passed'],report['checks'])
    def test_vendor_mislabeled_zero3w_profile_passes_with_warning(self):
        def modify(s):
            s.path('/proc/device-tree/model').write_bytes(b'sun60iw2\0')
            s.path('/proc/device-tree/compatible').write_bytes(b'xunlong,orangepi-4-pro\0arm,sun60iw2p1\0')
            p=s.path('/usr/share/opi-3w-wbuild/board-profile.json');data=json.loads(p.read_text())
            data.update(model='sun60iw2',compatible=['xunlong,orangepi-4-pro','arm,sun60iw2p1'])
            p.write_text(json.dumps(data))
        report,calls=self.exercise(modify)
        self.assertTrue(report['build_passed'],report['checks'])
        self.assertEqual({c['name']:c['status'] for c in report['checks']}['vendor_board_label'],'WARN')
        self.assertTrue(any(c[0]=='timeout' for c in calls))
    def test_4pro_label_without_matching_recorded_profile_is_rejected(self):
        report,calls=self.exercise(lambda s:s.path('/proc/device-tree/compatible').write_bytes(b'xunlong,orangepi-4-pro\0arm,sun60iw2p1\0'))
        self.assertFalse(report['build_passed']);self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_wrong_selected_dtb_is_rejected(self):
        def modify(s):
            s.path('/boot/orangepiEnv.txt').write_text('rootdev=UUID=root-uuid\nfdtfile=allwinner/sun60i-a733-orangepi-4-pro.dtb\n')
            s.path('/usr/share/opi-3w-wbuild/configured-boot.json').write_text(json.dumps(boot_snapshot(s.root)))
        report,calls=self.exercise(modify)
        self.assertFalse(report['build_passed']);self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_vendor_os_identity_is_not_accepted_as_fresh_debian(self):
        report,calls=self.exercise(lambda s:s.path('/etc/os-release').write_text('ID=ubuntu\nVERSION_ID="22.04"\n'))
        self.assertFalse(report['build_passed']);self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_wrong_root_uuid_blocks_compute(self):
        def modify(s):
            s.path('/usr/share/opi-3w-wbuild/layout.json').write_text(json.dumps({'filesystem':{'uuid':'different'}}))
        report,calls=self.exercise(modify)
        self.assertFalse(report['build_passed'])
        self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_unexpanded_root_is_reported_as_failure(self):
        class NotExpanded(FakeSystem):
            def run(self,*args):
                if args[0]=='opi-3w-wbuild-expand':return dict(code=1,output=json.dumps({'complete':False}),elapsed_ms=1)
                return super().run(*args)
        with tempfile.TemporaryDirectory() as directory:
            report=v.Verification(NotExpanded(directory)).run()
        self.assertFalse(report['build_passed'])
        self.assertEqual({c['name']:c['status'] for c in report['checks']}['root_expansion'],'FAIL')
    def test_changed_boot_payload_blocks_execution(self):
        report,calls=self.exercise(lambda s:setattr(s,'hardware_ok',False))
        self.assertFalse(report['build_passed']);self.assertFalse(any(c[0]=='timeout' for c in calls))
    def test_inactive_ssh_fails_build(self):
        report,_=self.exercise(lambda s:setattr(s,'inactive','ssh.service'))
        self.assertFalse(report['build_passed'])
    def test_npu_node_presence_is_not_inference_validation(self):
        def modify(s):
            s.path('/dev').mkdir();s.path('/dev/vipcore').touch()
        report,_=self.exercise(modify)
        self.assertTrue(report['npu']['device_present']);self.assertFalse(report['npu']['inference_validated'])
    def test_split_ddk_version_passes_loaded_driver_check(self):
        report,_=self.exercise(lambda s:setattr(s,'ddk','24.2.660.3887'))
        self.assertTrue(report['build_passed'])
        self.assertEqual(report['gpu_capabilities']['ddk_version_canonical'],'24.2.6603887')
    def test_dedicated_loaded_ddk_metadata_is_used(self):
        def modify(s):
            p=s.path('/sys/module/pvrsrvkm/parameters/opi_3w_wbuild_ddk')
            p.parent.mkdir(parents=True);p.write_text('24.2.660.3887')
            s.ddk='24.2.660.3887'
        report,_=self.exercise(modify)
        self.assertTrue(report['build_passed'])
        self.assertTrue(report['gpu_capabilities']['ddk_metadata_source'].endswith('/parameters/opi_3w_wbuild_ddk'))
    def test_wrong_loaded_ddk_fails(self):
        report,_=self.exercise(lambda s:setattr(s,'ddk','24.2.660.3888'))
        self.assertFalse(report['build_passed'])
    def test_report_bundle_contains_results_and_logs(self):
        report,_=self.exercise()
        with tempfile.TemporaryDirectory() as d:
            bundle=v.save_report(report,d)
            with tarfile.open(bundle) as archive:
                names=archive.getnames()
                name=next(n for n in names if n.endswith('/report.json'))
                content=json.load(archive.extractfile(name))
                self.assertTrue(content['build_passed'])
                self.assertFalse(content['npu_inference_validated'])
                self.assertTrue(any(n.endswith('/opencl.log') for n in names))
                self.assertFalse(any('CONFIG.TXT' in n or 'shadow' in n for n in names))

if __name__=='__main__':unittest.main()
