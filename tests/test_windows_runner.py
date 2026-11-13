"""Exercise the Windows-entry Linux flow with mock WSL and build operations."""
import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

RUNNER = Path(__file__).resolve().parents[1]/'windows-entry.sh'


class WindowsRunnerTests(unittest.TestCase):
    def exercise(self, fail=False, cached=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root/'source with spaces & symbols'
            project.mkdir()
            donor = root/'vendor $(touch SHOULD_NOT_EXIST) & copy.img'
            donor.write_bytes(b'mock donor')
            if cached:
                donor=root/'hardware $(touch SHOULD_NOT_EXIST).tar.gz'
                donor.write_bytes(b'cached bundle')
            home = root/'linuxhome';home.mkdir()
            commands = root/'bin';commands.mkdir()
            (commands/'grep').write_text('#!/bin/bash\nexit 0\n')
            (commands/'sudo').write_text('#!/bin/bash\nif [[ $1 == chown ]]; then\n printf \"%s\\n\" \"$@\" > \"$HOME/ownership-call\"\nfi\nexec \"$@\"\n')
            for command in commands.iterdir(): command.chmod(0o755)
            (project/'windows-entry.sh').write_bytes(RUNNER.read_bytes())
            (project/'inputs').mkdir()
            (project/'extract-hardware.sh').write_text('#!/bin/bash\necho MOCK-EXTRACT\nprintf bundle > "$2"\n')
            (project/'setup-wsl.sh').write_text('#!/bin/bash\necho MOCK-DEPENDENCIES\n')
            script = '#!/bin/bash\nset -eu\nif [[ $1 == --inspect ]]; then echo MOCK-INSPECT; exit 0; fi\n'
            script += '[[ $# == 3 ]] || exit 91\n'
            script += 'echo MOCK-BUILD-FAILED\nexit 7\n' if fail else 'printf "mock image" > "$2"\nprintf "mock checksum" > "$2.sha256"\necho MOCK-BUILD-OK\n'
            (project/'build.sh').write_text(script)
            env = dict(os.environ, HOME=str(home), PATH=str(commands)+os.pathsep+os.environ['PATH'])
            args=['bash',str(project/'windows-entry.sh'),str(donor),'4096']
            result = subprocess.run(args,env=env,cwd=root,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode, 7 if fail else 0, result.stdout+result.stderr)
            self.assertFalse((root/'SHOULD_NOT_EXIST').exists())
            destination=project/'out'
            log=(destination/'build.log').read_text()
            self.assertIn('MOCK-DEPENDENCIES',log)
            if cached:
                self.assertNotIn('MOCK-EXTRACT',log)
            else:
                self.assertIn('MOCK-EXTRACT',log)
                self.assertEqual((project/'inputs/zero3w-hardware.tar.gz').read_bytes(),b'bundle')
            self.assertFalse(list(home.glob('opi-3w-wbuild/*/donor.img')))
            name='opi-3w-wbuild-0.7.6.img.gz'
            image=destination/name
            if fail:
                self.assertIn('MOCK-BUILD-FAILED',log)
                self.assertFalse(image.exists())
            else:
                self.assertEqual(gzip.decompress(image.read_bytes()), b'mock image')
                ownership=(home/'ownership-call').read_text().splitlines()
                self.assertEqual(ownership[:3], ['chown','--',str(os.getuid())+':'+str(os.getgid())])
                self.assertTrue(ownership[3].endswith('/opi-3w-wbuild.img'))
                self.assertTrue(ownership[4].endswith('/opi-3w-wbuild.img.sha256'))
                checksum=Path(str(image)+'.sha256').read_text()
                self.assertIn('  '+name+'\n',checksum)
                self.assertNotIn(str(home),checksum)
                self.assertIn('MOCK-BUILD-OK',log)
                old=image.read_bytes()
                retry=subprocess.run(args,env=env,cwd=root,capture_output=True,text=True,timeout=10)
                self.assertEqual(retry.returncode,1)
                self.assertIn('Output already exists',retry.stderr)
                self.assertEqual(image.read_bytes(),old)
    def test_success_paths_compression_and_no_overwrite(self): self.exercise()
    def test_failure_keeps_log_and_does_not_export_image(self): self.exercise(fail=True)
    def test_cached_bundle_needs_no_vendor_image(self): self.exercise(cached=True)

if __name__ == '__main__': unittest.main()
