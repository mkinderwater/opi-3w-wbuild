import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('donor_files',Path(__file__).resolve().parents[1]/'scripts/donor_files.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class DonorFilesTests(unittest.TestCase):
    def test_hardware_allowlist_excludes_vendor_accounts_services_and_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'donor';stage=Path(directory)/'hardware'
            for path,data in {'lib/modules/6.6/driver.ko':b'module','vendor/etc/firmware/aic.bin':b'firmware',
                              'vendor/etc/accounts':b'vendor accounts','etc/passwd':b'vendor user',
                              'etc/systemd/system/vendor.service':b'vendor service','home/orangepi/app':b'vendor app'}.items():
                f=root/path;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
            module.stage(root,stage)
            self.assertEqual((stage/'vendor/etc/firmware/aic.bin').read_bytes(),b'firmware')
            for path in ('vendor/etc/accounts','etc/passwd','etc/systemd','home','boot'):
                self.assertFalse((stage/path).exists())
    def test_absolute_alternatives_chain_is_materialized(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'donor'
            (root/'usr/lib/firmware').mkdir(parents=True)
            (root/'lib').symlink_to('usr/lib')
            (root/'etc/alternatives').mkdir(parents=True)
            for suffix in ('','.p7s'):
                (root/('usr/lib/firmware/regulatory.db-debian'+suffix)).write_bytes(b'actual donor data'+suffix.encode())
                (root/('usr/lib/firmware/regulatory.db'+suffix)).symlink_to('/etc/alternatives/regulatory.db'+suffix)
                (root/('etc/alternatives/regulatory.db'+suffix)).symlink_to('/lib/firmware/regulatory.db-debian'+suffix)
            (root/'boot').mkdir();(root/'boot/uImage').write_bytes(b'kernel')
            (root/'usr/lib/modules/6.6/vendor').mkdir(parents=True)
            (root/'usr/lib/modules/6.6/build').symlink_to('/usr/src/absent-headers')
            (root/'usr/lib/modules/6.6/vendor/test.ko').write_bytes(b'module')
            module.stage(root,base/'stage')
            for suffix in ('','.p7s'):
                output=base/('stage/usr/lib/firmware/regulatory.db'+suffix)
                self.assertFalse(output.is_symlink())
                self.assertEqual(output.read_bytes(),b'actual donor data'+suffix.encode())
            self.assertFalse((base/'stage/lib/modules/6.6/build').exists())
            self.assertEqual((base/'stage/lib/modules/6.6/vendor/test.ko').read_bytes(),b'module')
    def test_absolute_target_never_reads_host_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);root=base/'donor';root.mkdir()
            secret=base/'host-secret';secret.write_bytes(b'host')
            (root/'link').symlink_to(str(secret))
            with self.assertRaises(FileNotFoundError):module.Donor(root).copy('link',base/'output')
            # The same absolute path inside the donor resolves to donor bytes.
            inner=root/str(secret).lstrip('/');inner.parent.mkdir(parents=True)
            inner.write_bytes(b'donor')
            module.Donor(root).copy('link',base/'output')
            self.assertEqual((base/'output').read_bytes(),b'donor')
    def test_relative_links_and_root_dotdot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'a').mkdir();(root/'data').write_text('donor')
            (root/'a/link').symlink_to('../../../../data')
            self.assertEqual(module.Donor(root).resolve('a/link'),root/'data')
    def test_missing_firmware_fails_with_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'regulatory.db').symlink_to('/etc/alternatives/missing')
            with self.assertRaises(FileNotFoundError):module.Donor(root).copy('regulatory.db',root/'output')
    def test_link_and_directory_cycles_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'one').symlink_to('two');(root/'two').symlink_to('one')
            with self.assertRaisesRegex(ValueError,'symlink loop'):module.Donor(root).resolve('one')
            (root/'tree').mkdir();(root/'tree/loop').symlink_to('/tree')
            with self.assertRaisesRegex(ValueError,'directory link cycle'):module.Donor(root).copy('tree',root/'output')

if __name__=='__main__':unittest.main()
