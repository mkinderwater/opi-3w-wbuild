import sys
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'lib'))
spec=importlib.util.spec_from_file_location('firstboot_nm',BASE/'overlay/firstboot.py')
firstboot=importlib.util.module_from_spec(spec);spec.loader.exec_module(firstboot)
CONFIG='SSID=My WiFi\nPSK=private-wifi-secret\nCOUNTRY=CA\nHIDDEN=false\nTIMEZONE=America/Edmonton\nROOT_PASSWORD=private-root-secret\n'


class FirstBootTests(unittest.TestCase):
    def make_root(self,root):
        for path in ('config','etc','proc/sys/kernel/random'):(root/path).mkdir(parents=True,exist_ok=True)
        (root/'config/CONFIG.TXT').write_text(CONFIG)
        (root/'etc/machine-id').write_text('a'*32)
        (root/'etc/hosts').write_text('127.0.0.1 localhost\n192.168.1.9 donor-host\n')
        (root/'proc/sys/kernel/random/boot_id').write_text('test-boot-id')

    def runner(self,calls,fail=False,no_device=False):
        def execute(*args,**kwargs):
            calls.append((args,kwargs));out=''
            if args[:2]==('/usr/sbin/sshd','-T'):out='permitrootlogin yes\npasswordauthentication yes\n'
            if args[0]=='nmcli' and 'DEVICE,TYPE' in args:out='eth0:ethernet\nwlp2s0:wifi\n' if not no_device else 'eth0:ethernet\n'
            if args[0]=='nmcli' and 'up' in args and fail:
                raise subprocess.CalledProcessError(10,args,output='private-wifi-secret private-root-secret')
            if args[0]=='ip':out=json.dumps([{'addr_info':[{'scope':'global','local':'192.168.1.22'}]}])
            return subprocess.CompletedProcess(args,0,stdout=out,stderr='')
        return execute

    def test_milestones_credentials_dynamic_interface_and_secret_scrubbing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_root(root);calls=[]
            firstboot.write_status('LINUX_STARTED','',root,lambda p:True)
            firstboot.setup(root,self.runner(calls),lambda p:True)
            status=(root/'config/BOOT-STATUS.TXT').read_text()
            for stage in ('LINUX_STARTED','SSH_READY','WIFI_PROFILE_READY','WAITING_FOR_DHCP','CONFIGURED'):
                self.assertIn(stage,status)
            self.assertIn('192.168.1.22',status)
            self.assertNotIn('private-',status)
            self.assertIn('PSK=\n',(root/'config/CONFIG.TXT').read_text())
            self.assertIn('ROOT_PASSWORD=\n',(root/'config/CONFIG.TXT').read_text())
            self.assertEqual((root/'var/lib/opi-3w-wbuild/wifi-interface').read_text(),'wlp2s0\n')
            self.assertTrue((root/'var/lib/opi-3w-wbuild/ssh-ready').exists())
            self.assertIn('donor-host',(root/'etc/hosts').read_text())
            nm=root/'etc/NetworkManager/system-connections/opi-3w-wbuild.nmconnection'
            self.assertEqual(nm.stat().st_mode & 0o777,0o600)
            self.assertNotIn('private-wifi-secret',nm.read_text())
            self.assertEqual(next(k['input'] for a,k in calls if a[0]=='chpasswd'),'root:private-root-secret\n')
            ssh=next(i for i,(a,k) in enumerate(calls) if a==('systemctl','restart','ssh.service'))
            wifi=next(i for i,(a,k) in enumerate(calls) if a[0]=='nmcli' and 'up' in a)
            self.assertLess(ssh,wifi)

    def test_wifi_failure_preserves_credentials_and_retry_uses_same_connection_uuid(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_root(root);calls=[]
            with self.assertRaises(subprocess.CalledProcessError):firstboot.setup(root,self.runner(calls,fail=True),lambda p:True)
            self.assertEqual((root/'config/CONFIG.TXT').read_text(),CONFIG)
            status=(root/'config/BOOT-STATUS.TXT').read_text()
            self.assertIn('SSH_READY',status);self.assertIn('SETUP_FAILED',status)
            self.assertNotIn('private-',status)
            self.assertNotIn('private-',(root/'var/lib/opi-3w-wbuild/last-error').read_text())
            connection_uuid=(root/'var/lib/opi-3w-wbuild/connection-uuid').read_text()
            firstboot.setup(root,self.runner([]),lambda p:True)
            self.assertEqual((root/'var/lib/opi-3w-wbuild/connection-uuid').read_text(),connection_uuid)
            self.assertTrue((root/'var/lib/opi-3w-wbuild/configured').exists())

    def test_no_wifi_device_still_reports_linux_and_ssh_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_root(root)
            firstboot.write_status('LINUX_STARTED','',root,lambda p:True)
            with self.assertRaises(firstboot.SetupError):firstboot.setup(root,self.runner([],no_device=True),lambda p:True)
            status=(root/'config/BOOT-STATUS.TXT').read_text()
            self.assertIn('LINUX_STARTED',status);self.assertIn('SSH_READY',status)
            self.assertIn('NetworkManager detected no Wi-Fi device',status)

    def test_unmounted_config_is_not_written_as_a_false_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_root(root);calls=[]
            with self.assertRaises(RuntimeError):firstboot.setup(root,self.runner(calls),lambda p:False)
            self.assertFalse((root/'config/BOOT-STATUS.TXT').exists())
            self.assertEqual(calls,[])

    def test_regdomain_failure_does_not_prevent_network_provisioning(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_root(root);normal=self.runner([])
            def execute(*args,**kwargs):
                if args[0]=='iw':raise subprocess.CalledProcessError(1,args)
                return normal(*args,**kwargs)
            firstboot.setup(root,execute,lambda p:True)
            status=(root/'config/BOOT-STATUS.TXT').read_text()
            self.assertIn('REGDOMAIN_WARNING',status)
            self.assertIn('CONFIGURED',status)

    def test_configured_marker_finishes_scrub_after_interrupted_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_root(root)
            (root/'var/lib/opi-3w-wbuild').mkdir(parents=True)
            (root/'var/lib/opi-3w-wbuild/configured').write_text('complete')
            calls=[];firstboot.setup(root,self.runner(calls),lambda p:True)
            self.assertEqual(calls,[])
            self.assertNotIn('private-',(root/'config/CONFIG.TXT').read_text())

    def test_status_history_is_bounded_and_resets_for_new_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.make_root(root)
            for i in range(30):firstboot.write_status('STAGE'+str(i),'',root,lambda p:True)
            history=json.loads((root/'var/lib/opi-3w-wbuild/boot-stages.json').read_text())
            self.assertLessEqual(len(history['stages']),16)
            (root/'proc/sys/kernel/random/boot_id').write_text('new-boot')
            firstboot.write_status('LINUX_STARTED','',root,lambda p:True)
            history=json.loads((root/'var/lib/opi-3w-wbuild/boot-stages.json').read_text())
            self.assertEqual(len(history['stages']),1)
