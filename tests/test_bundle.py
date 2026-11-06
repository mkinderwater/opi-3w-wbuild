"""Real archive, filesystem and boot preservation checks without root mounts."""
import io,json,os,shutil,subprocess,tarfile,tempfile,unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import hardware_bundle as bundle
import assemble_image as assemble
from test_clone import vendor_fixture
from image_layout import MIB

@unittest.skipUnless(all(shutil.which(x) for x in ['mkfs.ext4','mkfs.vfat','rsync','dtc','fdtget','e2fsck','debugfs']),'native filesystem and DT tools needed')
class BundleTests(unittest.TestCase):
    def fixture(self,w):
        donor=w/'vendor';(donor/'boot/dtb/allwinner').mkdir(parents=True)
        (donor/'boot/uImage').write_bytes(b'unchanged kernel')
        (donor/'boot/orangepiEnv.txt').write_text('fdtfile=allwinner/sun60i-a733-orangepi-zero3w.dtb\n')
        (donor/'boot/kernel-link').symlink_to('/boot/uImage')
        dts=w/'board.dts';dts.write_text('/dts-v1/; / {model="sun60iw2";compatible="xunlong,orangepi-4-pro","arm,sun60iw2p1";};')
        subprocess.run(['dtc','-I','dts','-O','dtb','-o',str(donor/'boot/dtb/allwinner/sun60i-a733-orangepi-zero3w.dtb'),str(dts)],check=True)
        (donor/'lib/modules/6.6.98-sun60iw2').mkdir(parents=True)
        (donor/'lib/modules/6.6.98-sun60iw2/wifi.ko').write_bytes(b'wifi')
        (donor/'lib/firmware').mkdir();(donor/'lib/firmware/wifi.bin').write_bytes(b'firmware')
        (donor/'etc').mkdir();(donor/'etc/passwd').write_text('VENDOR_ACCOUNT_MUST_NOT_SURVIVE')
        (donor/'home').mkdir();(donor/'home/secret').write_text('VENDOR_SECRET_MUST_NOT_SURVIVE')
        fs=w/'donor.ext4'
        with fs.open('wb') as f:f.truncate(64*MIB)
        subprocess.run(['mkfs.ext4','-F','-b','4096','-I','256','-O',assemble.FEATURES,'-d',str(donor),str(fs)],check=True,capture_output=True)
        image=w/'vendor.img';vendor_fixture(image,fs)
        payload=w/'payload';bundle.make_payload(image,donor,payload)
        archive=w/'hardware.tar.gz';bundle.pack(payload,archive)
        return donor,payload,archive

    def test_extract_reuse_and_fresh_assembly(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);donor,payload,archive=self.fixture(w)
            before=(w/'vendor.img').stat().st_size
            self.assertLess(archive.stat().st_size,before//10)
            restored=w/'restored';bundle.unpack(archive,restored)
            self.assertFalse((restored/'root/etc/passwd').exists());self.assertFalse((restored/'root/home').exists())
            self.assertEqual(os.readlink(restored/'root/boot/kernel-link'),'/boot/uImage')
            root=w/'fresh';shutil.copytree(restored/'root',root,symlinks=True)
            (root/'etc').mkdir(exist_ok=True);(root/'etc/os-release').write_text('ID=debian\n')
            layout=assemble.plan(restored);fat=w/'config.fat'
            with fat.open('wb') as f:f.truncate(64*MIB)
            subprocess.run(['mkfs.vfat','-F','32',str(fat)],check=True,capture_output=True)
            fs=w/'fresh.ext4';out=w/'fresh.img';normalized=[]
            def host_mount_substitute(image,expected):
                # Real format/assembly checks run here; mount behavior is tested
                # separately because the host test runner cannot create loops.
                self.assertEqual(Path(image),fs)
                self.assertEqual(expected,bundle.validate(restored)['vendor_boot'])
                value=subprocess.check_output(['debugfs','-R','cat /boot/uImage',str(image)],stderr=subprocess.DEVNULL)
                self.assertEqual(value,b'unchanged kernel');normalized.append(image)
            assemble.build(restored,root,fat,fs,out,layout,normalizer=host_mount_substitute)
            self.assertEqual(normalized,[fs])
            self.assertEqual(out.stat().st_size,2048*MIB)
            self.assertEqual(layout['root_start'],96*MIB)
            self.assertEqual(layout['root_start']+layout['root_bytes'],out.stat().st_size)
            contents=subprocess.check_output(['debugfs','-R','cat /boot/uImage',str(fs)],stderr=subprocess.DEVNULL)
            self.assertEqual(contents,b'unchanged kernel')
            result=subprocess.check_output(['debugfs','-R','stat /home/secret',str(fs)],stderr=subprocess.STDOUT)
            self.assertIn(b'File not found',result)
            with self.assertRaises(FileExistsError):assemble.build(restored,root,fat,fs,out,layout)
            with out.open('r+b') as f:f.seek(440);f.write(b'BAD!')
            with self.assertRaisesRegex(ValueError,'MBR'):assemble.verify(restored,out,layout)
            (restored/'root/boot/uImage').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'hashes'):bundle.validate(restored)

    def test_archive_rejects_traversal_symlink_and_extra_os(self):
        with tempfile.TemporaryDirectory() as d:
            w=Path(d);_,payload,archive=self.fixture(w)
            for i,(name,link) in enumerate([('../escape',None),('root/etc/passwd',None),('root/boot/evil','/etc/passwd')]):
                bad=w/f'bad{i}.tar.gz'
                with tarfile.open(archive) as source,tarfile.open(bad,'w:gz') as target:
                    for member in source.getmembers():target.addfile(member,source.extractfile(member) if member.isfile() else None)
                    member=tarfile.TarInfo(name)
                    if link:member.type=tarfile.SYMTYPE;member.linkname=link;target.addfile(member)
                    else:member.size=1;target.addfile(member,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):bundle.unpack(bad,w/f'extract{i}')
                self.assertFalse((w/'escape').exists())
