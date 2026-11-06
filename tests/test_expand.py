import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'lib'))
spec=importlib.util.spec_from_file_location('expansion',BASE/'overlay/expand.py')
expansion=importlib.util.module_from_spec(spec);spec.loader.exec_module(expansion)
MIB=1024*1024


class SimulatedCard(expansion.System):
    """Real MBR/ext4 files; only the kernel's live partition refresh is simulated."""
    def __init__(self,root,capacity=512*MIB):
        self.root=root;self.calls=[];self.stages=[];self.refresh_fails=False;self.resize_fails=False
        self.disk=self.path('/dev/mmcblk1');self.disk.parent.mkdir(parents=True)
        self.part=self.path('/dev/mmcblk1p1')
        self.sysroot=self.path('/sys/class/block/mmcblk1p1');self.sysroot.mkdir(parents=True)
        self.sysdisk=self.path('/sys/class/block/mmcblk1');self.sysdisk.mkdir(parents=True)
        tree=root/'tree';(tree/'boot').mkdir(parents=True)
        (tree/'boot/uImage').write_bytes(b'working kernel survives expansion')
        with self.part.open('wb') as f:f.truncate(64*MIB)
        subprocess.run(['mkfs.ext4','-F','-d',str(tree),str(self.part)],check=True,capture_output=True)
        self.layout=dict(root_start=96*MIB,root_bytes=64*MIB,config_start=32*MIB,config_bytes=64*MIB,
                         filesystem={'uuid':expansion.filesystem(self.part)['uuid']})
        manifest=self.path('/usr/share/opi-3w-wbuild/layout.json');manifest.parent.mkdir(parents=True);manifest.write_text(json.dumps(self.layout))
        (self.sysroot/'start').write_text(str(96*MIB//512));(self.sysroot/'size').write_text(str(64*MIB//512))
        (self.sysdisk/'size').write_text(str(capacity//512))
        mbr=bytearray(512);mbr[:12]=b'BOOT-RESERVE';struct.pack_into('<I',mbr,440,0x12345678)
        struct.pack_into('<B3sB3sII',mbr,446,0x80,b'\xfe\xff\xff',0x83,b'\xfe\xff\xff',96*MIB//512,64*MIB//512)
        struct.pack_into('<B3sB3sII',mbr,462,0,b'\xfe\xff\xff',0x0c,b'\xfe\xff\xff',32*MIB//512,64*MIB//512)
        mbr[510:]=b'\x55\xaa'
        with self.disk.open('wb') as f:
            f.truncate(capacity);f.write(mbr);f.seek(500000);f.write(b'unknown reserved vendor data')
            f.seek(32*MIB);f.write(b'CONFIGURATION PARTITION MUST NOT CHANGE')
        self.original=mbr
    def devices(self):return self.part,self.disk,self.sysroot,self.sysdisk
    def mbr(self):
        with self.disk.open('rb') as source:return source.read(512)
    def status(self,stage,detail=''):self.stages.append((stage,detail))
    def refresh_kernel(self):
        with self.disk.open('rb') as f:mbr=f.read(512)
        sectors=struct.unpack_from('<I',mbr,458)[0]
        (self.sysroot/'size').write_text(str(sectors))
        with self.part.open('r+b') as f:f.truncate(sectors*512)
    def run(self,*args,timeout=30):
        self.calls.append(args)
        if args[0]=='partx':
            if self.refresh_fails:raise subprocess.CalledProcessError(1,args)
            self.refresh_kernel()
        elif args[0]=='resize2fs':
            if self.resize_fails:raise subprocess.CalledProcessError(1,args)
            return subprocess.run(args,check=True,capture_output=True,text=True,timeout=timeout)
        return subprocess.CompletedProcess(args,0,stdout='',stderr='')


@unittest.skipUnless(shutil.which('mkfs.ext4') and shutil.which('resize2fs') and shutil.which('debugfs'),'e2fsprogs required')
class ExpansionTests(unittest.TestCase):
    def test_root_reaches_card_end_and_ext4_size_while_boot_and_fat_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            card=SimulatedCard(Path(directory))
            with card.disk.open('rb') as f:
                original=f.read(512);f.seek(500000);reserve=f.read(40);f.seek(32*MIB);fat=f.read(64)
            self.assertFalse(expansion.check(card)['complete'])
            self.assertTrue(expansion.expand(card))
            checked=expansion.check(card);self.assertTrue(checked['complete'])
            self.assertEqual(checked['root_start']+checked['root_sectors'],checked['card_sectors'])
            self.assertEqual(checked['blocks']*checked['block_size'],checked['root_sectors']*512)
            self.assertEqual(checked['uuid'],card.layout['filesystem']['uuid'])
            with card.disk.open('rb') as f:
                after=f.read(512);f.seek(500000);self.assertEqual(f.read(40),reserve)
                f.seek(32*MIB);self.assertEqual(f.read(64),fat)
            self.assertEqual(after[:458],original[:458]);self.assertEqual(after[462:],original[462:])
            kernel=subprocess.check_output(['debugfs','-R','cat /boot/uImage',str(card.part)],stderr=subprocess.DEVNULL)
            self.assertEqual(kernel,b'working kernel survives expansion')
            subprocess.run(['e2fsck','-fn',str(card.part)],check=True,capture_output=True)
            count=len(card.calls);self.assertTrue(expansion.expand(card));self.assertEqual(len(card.calls),count)

    def test_kernel_refresh_failure_is_deferred_and_retry_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            card=SimulatedCard(Path(directory));card.refresh_fails=True
            self.assertFalse(expansion.expand(card))
            self.assertFalse(card.path('/var/lib/opi-3w-wbuild/expanded.json').exists())
            self.assertTrue(card.path('/var/lib/opi-3w-wbuild/resize-error').exists())
            self.assertFalse(any(c[0]=='resize2fs' for c in card.calls))
            card.refresh_fails=False
            self.assertTrue(expansion.expand(card));self.assertTrue(expansion.check(card)['complete'])
            self.assertFalse(card.path('/var/lib/opi-3w-wbuild/resize-error').exists())

    def test_filesystem_failure_retries_without_rewriting_partition_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            card=SimulatedCard(Path(directory));card.resize_fails=True
            self.assertFalse(expansion.expand(card));mbr=card.mbr()
            self.assertFalse(expansion.check(card)['complete'])
            card.resize_fails=False
            self.assertTrue(expansion.expand(card));self.assertEqual(card.mbr(),mbr)

    def test_reboot_after_partition_commit_finishes_filesystem_growth(self):
        with tempfile.TemporaryDirectory() as directory:
            card=SimulatedCard(Path(directory));card.refresh_fails=True
            self.assertFalse(expansion.expand(card))
            card.refresh_kernel();card.refresh_fails=False;card.calls=[]
            self.assertTrue(expansion.expand(card))
            self.assertFalse(any(c[0]=='partx' for c in card.calls))
            self.assertTrue(any(c[0]=='resize2fs' for c in card.calls))

    def test_unsafe_or_ambiguous_geometry_is_refused_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            card=SimulatedCard(Path(directory));bad=bytearray(card.original)
            struct.pack_into('<B3sB3sII',bad,478,0,b'\0'*3,0x83,b'\0'*3,200,100)
            with card.disk.open('r+b') as f:f.write(bad)
            self.assertFalse(expansion.expand(card));self.assertEqual(card.calls,[])
            self.assertEqual(card.mbr(),bad)
            wrong_uuid=dict(card.layout,filesystem={'uuid':'wrong'})
            card.path('/usr/share/opi-3w-wbuild/layout.json').write_text(json.dumps(wrong_uuid))
            with card.disk.open('r+b') as f:f.write(card.original)
            self.assertFalse(expansion.expand(card));self.assertEqual(card.calls,[])
            self.assertEqual(card.mbr(),card.original)

    def test_configuration_after_root_and_oversized_cards_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            card=SimulatedCard(Path(directory));bad=dict(card.layout,config_start=200*MIB)
            mbr=bytearray(card.original);struct.pack_into('<I',mbr,470,bad['config_start']//512)
            with self.assertRaisesRegex(ValueError,'before root'):expansion.geometry(mbr,512*MIB//512,bad)
            with self.assertRaisesRegex(ValueError,'MBR range'):expansion.geometry(card.original,0x100000001,card.layout)
