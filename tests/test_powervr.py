import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'scripts'))
import powervr


class PowerVRTests(unittest.TestCase):
    def fixture(self, root):
        pins=json.loads((BASE/'gpu/pins.json').read_text())
        header=bytearray(64);header[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',header,18,183)
        for stem in powervr.LIBRARIES:
            p=root/('usr/lib/'+stem+'.so.'+pins['ddk']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(header)
        for relative in powervr.EXTRA_LIBRARIES:
            p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(header)
        for prefix in ('rgx.fw.','rgx.sh.'):
            p=root/('lib/firmware/'+prefix+pins['bvnc']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'firmware')
        return pins
    def test_runtime_is_isolated_and_manifest_has_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);pins=self.fixture(d/'vendor')
            powervr.install_runtime(d/'vendor',d/'root',pins)
            r=d/'root'/powervr.PREFIX
            self.assertEqual((r/'lib/libPVROCL.so').resolve(),r/'lib/libPVROCL.so.24.2.6603887')
            self.assertEqual((r/'OpenCL/pvr.icd').read_text(),'/opt/opi-3w-wbuild-powervr/lib/libPVROCL.so\n')
            self.assertFalse((d/'root/usr/lib/libOpenCL.so').exists())
            self.assertFalse((d/'root/usr/bin/Xorg').exists())
            manifest=json.loads((r/'manifest.json').read_text())
            self.assertFalse(manifest['hardware_validated'])
            self.assertEqual(len(manifest['files']),10)
            self.assertEqual((r/'lib/libpvr_mesa_wsi.so').read_bytes(),(d/'vendor/usr/local/lib/libpvr_mesa_wsi.so').read_bytes())
            self.assertTrue(all(len(h)==64 for h in manifest['files'].values()))
    def test_wrong_architecture_fails(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);pins=self.fixture(d/'vendor')
            p=d/'vendor/usr/lib/libPVROCL.so.24.2.6603887'
            h=bytearray(p.read_bytes());struct.pack_into('<H',h,18,62);p.write_bytes(h)
            with self.assertRaisesRegex(ValueError,'ARM64'):powervr.install_runtime(d/'vendor',d/'root',pins)
    def test_missing_dlopen_helper_fails_packaging(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);pins=self.fixture(d/'vendor')
            (d/'vendor'/powervr.EXTRA_LIBRARIES[0]).unlink()
            with self.assertRaises(FileNotFoundError):powervr.install_runtime(d/'vendor',d/'root',pins)
    def test_module_abi_and_ddk_must_both_match(self):
        powervr.check_module('6.6.98-sun60iw2','6.6.98-sun60iw2 SMP preempt mod_unload aarch64','24.2@6603887')
        for magic,version in [('6.6.98-vendor-sun60iw2 SMP','24.2@6603887'),('6.6.98-sun60iw2 SMP','23.3@6603887'),('6.6.98-sun60iw2 SMP','24.2@1111111')]:
            with self.assertRaises(ValueError):powervr.check_module('6.6.98-sun60iw2',magic,version)

if __name__=='__main__':unittest.main()

class PowerVRPreflightTests(unittest.TestCase):
    def test_missing_module_and_headers_stops_before_build(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);pins=json.loads((BASE/'gpu/pins.json').read_text())
            (d/'hardware/lib/modules'/pins['kernel_abi']).mkdir(parents=True)
            (d/'donor').mkdir()
            with self.assertRaisesRegex(ValueError,'No matching donor PowerVR module'):
                powervr.preflight(d/'hardware',d/'donor',d/'inputs',pins)
    def test_header_input_selects_build_path(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);pins=json.loads((BASE/'gpu/pins.json').read_text())
            (d/'hardware/lib/modules'/pins['kernel_abi']).mkdir(parents=True)
            (d/'inputs').mkdir();(d/'inputs/kernel-headers.deb').touch()
            self.assertIn('Will build',powervr.preflight(d/'hardware',d/'donor',d/'inputs',pins))
    def test_wrong_kernel_stops_preflight(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);pins=json.loads((BASE/'gpu/pins.json').read_text())
            (d/'hardware/lib/modules/6.6.99').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'requires kernel'):
                powervr.preflight(d/'hardware',d/'donor',d/'inputs',pins)

class ModuleMetadataTests(unittest.TestCase):
    def test_dedicated_ddk_field_is_preferred(self):
        from unittest.mock import patch
        with patch('powervr.subprocess.check_output',return_value='24.2.660.3887\n') as query:
            self.assertEqual(powervr.module_ddk('module.ko'),'24.2.660.3887')
            self.assertEqual(query.call_count,1)
    def test_standard_module_version_remains_valid_for_donors(self):
        from unittest.mock import patch
        with patch('powervr.subprocess.check_output',side_effect=['','24.2@6603887\n']) as query:
            self.assertEqual(powervr.module_ddk('module.ko'),'24.2@6603887')
            self.assertEqual(query.call_count,2)
    def test_split_numeric_ddk_passes_exact_module_validation(self):
        powervr.check_module('6.6.98-sun60iw2','6.6.98-sun60iw2 SMP','24.2.660.3887')
