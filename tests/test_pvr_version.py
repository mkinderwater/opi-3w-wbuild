from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'lib'))
from pvr_version import canonical_ddk


class PVRVersionTests(unittest.TestCase):
    def test_all_equivalent_vendor_formats(self):
        for value in ('24.2@6603887','24.2.6603887','24.2.660.3887',
                      'Rogue_DDK_Linux_WS rogueddk 24.2@6603887',
                      '24.2.660.3887 (release)\n'):
            with self.subTest(value=value):self.assertEqual(canonical_ddk(value),'24.2.6603887')
    def test_other_versions_and_digit_extensions_are_rejected(self):
        for value in ('','24.2','24.2@1111111','24.2.660.3888','24.3.660.3887',
                      '124.2.660.3887','24.2.660.38870','24.2.66038870','24.2.660.3887.1'):
            with self.subTest(value=value):self.assertIsNone(canonical_ddk(value))

if __name__=='__main__':unittest.main()

class EmittedMetadataTests(unittest.TestCase):
    def test_metadata_compiles_from_the_ddk_header(self):
        import shutil,subprocess,tempfile
        base=Path(__file__).resolve().parents[1]
        if not shutil.which('gcc') or not shutil.which('readelf'):self.skipTest('gcc/readelf unavailable')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'linux').mkdir()
            (root/'linux/module.h').write_text('#define MODULE_INFO(tag, value) static const char metadata[] __attribute__((used,section(".modinfo"))) = #tag "=" value;\n#define MODULE_PARM_DESC(name, text)\n')
            (root/'linux/moduleparam.h').write_text('#define module_param_string(name, string, size, mode) static const void *parameter __attribute__((used)) = string;\n')
            (root/'pvrversion.h').write_text('#define PVRVERSION_STRING_NUMERIC "24.2.660.3887"\n')
            subprocess.run(['gcc','-Wall','-Wextra','-Werror','-I'+str(root),'-c',str(base/'gpu/opi_3w_wbuild_ddk_metadata.c'),'-o',str(root/'metadata.o')],check=True,capture_output=True,text=True)
            output=subprocess.check_output(['readelf','-p','.modinfo',str(root/'metadata.o')],text=True)
            self.assertIn('opi_3w_wbuild_ddk=24.2.660.3887',output)
