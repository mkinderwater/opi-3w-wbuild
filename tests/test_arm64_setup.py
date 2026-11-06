import importlib.util
from pathlib import Path
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('arm64_setup', BASE / 'scripts/enable-arm64.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class Arm64SetupTests(unittest.TestCase):
    def exercise(self, modern=False, legacy=False, existing=None, registered='enabled\nflags: POCF\n'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'proc/sys/fs/binfmt_misc/qemu-aarch64'
            entry.parent.mkdir(parents=True)
            if existing is not None:
                entry.write_text(existing)
            if modern:
                for name in ('usr/lib/binfmt.d/qemu-aarch64.conf', 'usr/lib/systemd/systemd-binfmt'):
                    file = root / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.touch()
            if legacy:
                file = root / 'usr/share/binfmts/qemu-aarch64'
                file.parent.mkdir(parents=True)
                file.touch()
            calls = []
            def run(args, check):
                self.assertTrue(check)
                calls.append(args)
                entry.write_text(registered)
            setup.enable(root, run)
            return root, calls

    def test_existing_kernel_registration_needs_no_distribution_database(self):
        _, calls = self.exercise(existing='enabled\nflags: POCF\n')
        self.assertEqual(calls, [])

    def test_modern_package_uses_its_systemd_definition_directly(self):
        root, calls = self.exercise(modern=True)
        self.assertEqual(calls, [[str(root / 'usr/lib/systemd/systemd-binfmt'),
                                 str(root / 'usr/lib/binfmt.d/qemu-aarch64.conf')]])

    def test_legacy_definition_is_imported_before_enabling(self):
        _, calls = self.exercise(legacy=True)
        self.assertEqual(calls, [['update-binfmts', '--import', 'qemu-aarch64'],
                                 ['update-binfmts', '--enable', 'qemu-aarch64']])

    def test_disabled_handler_is_registered_again(self):
        _, calls = self.exercise(modern=True, existing='disabled\nflags: POCF\n')
        self.assertEqual(len(calls), 1)

    def test_registration_without_fix_binary_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'fix-binary'):
            self.exercise(modern=True, registered='enabled\nflags: POC\n')

    def test_missing_package_definitions_fail_clearly(self):
        with self.assertRaisesRegex(RuntimeError, 'packaged ARM64'):
            self.exercise()
