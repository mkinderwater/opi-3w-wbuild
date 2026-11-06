import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prepare_headers',BASE/'gpu/prepare-headers.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class HeaderPreparationTests(unittest.TestCase):
    def fixture(self,root,fail=False,change_abi=False):
        (root/'include/config').mkdir(parents=True)
        (root/'include/config/kernel.release').write_text('6.6.98-sun60iw2\n')
        (root/'Module.symvers').write_text('preserved donor symbols\n')
        (root/'scripts/basic').mkdir(parents=True);(root/'scripts/mod').mkdir()
        source=root/'helper.c';source.write_text('int main(void) { return 1; }\n')
        make=''' .PHONY: olddefconfig scripts all
olddefconfig:
\t@echo olddefconfig >> order
scripts:
\t@echo scripts >> order
'''.lstrip()
        if fail:make+='\t@false\n'
        else:make+='\t$(HOSTCC) helper.c -o scripts/basic/fixdep\n'
        make+='all:\n\t@echo modpost >> order\n\t$(HOSTCC) helper.c -o scripts/mod/modpost\n'
        if change_abi:make+='\t@echo wrong > include/config/kernel.release\n'
        # Kernel's default target depends on M, while olddefconfig/scripts are explicit.
        make='.DEFAULT_GOAL := all\n'+make
        (root/'Makefile').write_text(make)
    def test_native_helpers_are_rebuilt_and_executable(self):
        if not shutil.which('gcc'):self.skipTest('gcc unavailable')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            stale=bytearray(64);stale[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',stale,18,183)
            (root/'scripts/basic/fixdep').write_bytes(stale)
            (root/'scripts/mod/old.o').write_bytes(stale)
            # Test binaries run on the host CPU. Production requires ARM64 (183).
            machine=62 if __import__('platform').machine()=='x86_64' else 183
            m.prepare(root,'6.6.98-sun60iw2',machine)
            self.assertEqual((root/'order').read_text().splitlines(),['olddefconfig','scripts','modpost'])
            self.assertFalse((root/'scripts/mod/old.o').exists())
            self.assertEqual((root/'Module.symvers').read_text(),'preserved donor symbols\n')
    def test_tool_build_failure_stops_preparation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root,fail=True)
            with self.assertRaises(subprocess.CalledProcessError):m.prepare(root,'6.6.98-sun60iw2')
            self.assertNotIn('modpost',(root/'order').read_text())
    def test_changed_kernel_release_is_rejected(self):
        if not shutil.which('gcc'):self.skipTest('gcc unavailable')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root,change_abi=True)
            with self.assertRaisesRegex(ValueError,'changed kernel.release'):m.prepare(root,'6.6.98-sun60iw2')
    def test_changed_symbol_versions_are_rejected(self):
        if not shutil.which('gcc'):self.skipTest('gcc unavailable')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            p=root/'Makefile';p.write_text(p.read_text()+'\t@echo changed > Module.symvers\n')
            with self.assertRaisesRegex(ValueError,'changed donor Module.symvers'):m.prepare(root,'6.6.98-sun60iw2')
    def test_wrong_tool_architecture_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'fixdep';h=bytearray(64);h[:6]=b'\x7fELF\x02\x01';struct.pack_into('<H',h,18,62);p.write_bytes(h);p.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'wrong ELF architecture'):m.check_tool(p)

if __name__=='__main__':unittest.main()
