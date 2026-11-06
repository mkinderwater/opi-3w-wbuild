import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'scripts'))
import image_layout as image
import boot_manifest


def vendor_fixture(path, rootfs):
    with path.open('wb') as output:
        output.truncate(32*image.MIB+rootfs.stat().st_size)
        mbr=bytearray(512)
        struct.pack_into('<I',mbr,440,0x12345678)
        struct.pack_into('<B3sB3sII',mbr,446,0x80,b'\xfe\xff\xff',0x83,b'\xfe\xff\xff',65536,rootfs.stat().st_size//512)
        mbr[510:]=b'\x55\xaa'
        output.write(mbr)
        for kind,offset in [('boot0',image.BOOT0_OFFSET),('toc1',image.TOC_OFFSET)]:
            data=bytearray(256)
            if kind=='boot0':
                data[4:12]=b'eGON.BT0';struct.pack_into('<I',data,16,len(data));check=12
            else:
                data[:13]=b'sunxi-package';struct.pack_into('<I',data,16,0x89119800);struct.pack_into('<I',data,36,len(data));check=20
            struct.pack_into('<I',data,check,image.STAMP)
            struct.pack_into('<I',data,check,sum(struct.unpack('<64I',data))&0xffffffff)
            output.seek(offset);output.write(data)
        output.seek(500000);output.write(b'unknown vendor reserved bytes')
        output.seek(32*image.MIB)
        with rootfs.open('rb') as incoming:shutil.copyfileobj(incoming,output)


class BootManifestTests(unittest.TestCase):
    def test_changed_added_and_retargeted_boot_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'boot').mkdir()
            kernel=root/'boot/kernel';kernel.write_bytes(b'donor')
            link=root/'boot/uImage';link.symlink_to('kernel')
            manifest=boot_manifest.snapshot(root)
            boot_manifest.verify(root,manifest)
            kernel.write_bytes(b'changed')
            with self.assertRaises(ValueError):boot_manifest.verify(root,manifest)
            kernel.write_bytes(b'donor');link.unlink();link.symlink_to('other')
            with self.assertRaises(ValueError):boot_manifest.verify(root,manifest)
            link.unlink();link.symlink_to('kernel');(root/'boot/extra').touch()
            with self.assertRaises(ValueError):boot_manifest.verify(root,manifest)
