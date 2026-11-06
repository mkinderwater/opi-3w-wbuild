import hashlib,os,stat,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import boot_allocation as a

class AllocationTests(unittest.TestCase):
    def test_dense_copy_preserves_data_links_owner_modes_and_fills_holes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);boot=root/'boot';boot.mkdir();kernel=boot/'uImage'
            with kernel.open('wb') as f:
                f.write(b'header');f.seek(4*1024**2);f.write(b'kernel tail')
            kernel.chmod(0o664);os.link(kernel,boot/'kernel-alias');(boot/'uInitrd').symlink_to('kernel-alias')
            before=a.snapshot(root)
            with kernel.open('rb') as f:self.assertLess(os.lseek(f.fileno(),0,os.SEEK_HOLE),kernel.stat().st_size)
            result=a.dense_boot(root)
            self.assertEqual(a.snapshot(root),before)
            self.assertEqual(kernel.stat().st_ino,(boot/'kernel-alias').stat().st_ino)
            with kernel.open('rb') as f:self.assertEqual(os.lseek(f.fileno(),0,os.SEEK_HOLE),kernel.stat().st_size)
            self.assertEqual(os.readlink(boot/'uInitrd'),'kernel-alias')
            self.assertEqual(stat.S_IMODE(kernel.stat().st_mode),0o664)
            self.assertTrue(result)

    def test_hardlink_outside_boot_is_rejected_before_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'boot').mkdir();p=root/'boot/file';p.write_bytes(b'keep');os.link(p,root/'external')
            before=a.snapshot(root)
            with self.assertRaisesRegex(ValueError,'outside'):a.dense_boot(root)
            self.assertEqual(a.snapshot(root),before)

    def test_boot_directory_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'other').mkdir();(root/'boot').symlink_to('other')
            with self.assertRaises(ValueError):a.dense_boot(root)


class FilesystemNormalizationTests(unittest.TestCase):
    def exercise(self,corrupt=False):
        from boot_manifest import snapshot
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);fs=w/'root.ext4';fs.write_bytes(b'filesystem fixture')
            root=w/'mounted';(root/'boot').mkdir(parents=True);(root/'boot/uImage').write_bytes(b'kernel')
            expected=snapshot(root)
            if corrupt:(root/'boot/uImage').write_bytes(b'changed')
            calls=[]
            def output(args,**kwargs):
                calls.append(tuple(args));return '/dev/loop999\n' if args[0]=='losetup' else 'kernel inode mapping\n'
            def run(args,**kwargs):calls.append(tuple(args))
            with patch.object(a.subprocess,'check_output',side_effect=output),patch.object(a.subprocess,'run',side_effect=run),patch.object(a.tempfile,'mkdtemp',return_value=str(root)):
                if corrupt:
                    with self.assertRaises(ValueError):a.normalize_filesystem(fs,expected)
                else:
                    result=a.normalize_filesystem(fs,expected)
                    self.assertTrue(result['all_regular_boot_files_dense'])
                    self.assertEqual(snapshot(root),expected)
                    self.assertTrue((root/'usr/share/opi-3w-wbuild/boot-allocation.json').is_file())
                    self.assertTrue(fs.with_suffix('.boot-allocation.json').is_file())
            self.assertIn(('mount','-t','ext4','-o','rw','/dev/loop999',str(root)),calls)
            self.assertIn(('umount',str(root)),calls)
            self.assertIn(('losetup','-d','/dev/loop999'),calls)
            self.assertEqual(fs.read_bytes(),b'filesystem fixture')
    def test_normalization_audits_and_unmounts_new_filesystem(self):self.exercise()
    def test_boot_mismatch_aborts_and_releases_loop(self):self.exercise(corrupt=True)

if __name__=='__main__':unittest.main()
