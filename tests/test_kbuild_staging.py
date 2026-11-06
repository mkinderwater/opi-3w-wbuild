import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('stage_kbuild',BASE/'scripts/stage_kbuild.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class KbuildStagingTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source';kernel=root/'kernel';kernel.mkdir()
        original=source/'services/server/env/linux/dkf_server.c';original.parent.mkdir(parents=True)
        original.write_text('int main(void) { return 0; }\n')
        output=source/'binary_sunxi_linux_nulldrmws_release/target_aarch64/kbuild'
        bridges=source/'binary_sunxi_linux_nulldrmws_release/target_neutral/intermediates'
        bridges.mkdir(parents=True)
        (bridges/'bridge.c').write_text('int bridge(void) { return 7; }\n')
        (kernel/'external.c').write_text('int external(void) { return 9; }\n')
        return source,kernel,output,bridges
    def test_generated_tree_has_compilable_source_and_bridge_links(self):
        with tempfile.TemporaryDirectory() as d:
            source,kernel,output,bridges=self.fixture(Path(d))
            count=m.stage(source,output,bridges,'rogue',kernel)
            self.assertEqual(count,3)
            target=output/'services/server/env/linux/dkf_server.c'
            self.assertTrue(target.is_symlink())
            self.assertFalse(target.readlink().is_absolute())
            self.assertEqual((output/'generated/rogue/bridge.c').read_text(),(bridges/'bridge.c').read_text())
            self.assertEqual((output/'external/external.c').read_text(),(kernel/'external.c').read_text())
            if shutil.which('gcc'):
                subprocess.run(['gcc',str(target),'-o',str(Path(d)/'probe')],check=True,capture_output=True)
                self.assertEqual(subprocess.run([str(Path(d)/'probe')]).returncode,0)
            self.assertEqual(m.stage(source,output,bridges,'rogue',kernel),0)
    def test_regular_output_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            source,kernel,output,bridges=self.fixture(Path(d))
            target=output/'services/server/env/linux/dkf_server.c';target.parent.mkdir(parents=True);target.write_text('keep')
            with self.assertRaisesRegex(ValueError,'overwrite'):m.stage(source,output,bridges,'rogue',kernel)
            self.assertEqual(target.read_text(),'keep')
    def test_source_link_outside_tree_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            source,kernel,output,bridges=self.fixture(Path(d))
            outside=Path(d)/'outside.c';outside.write_text('int outside;')
            (source/'escape.c').symlink_to(outside)
            with self.assertRaisesRegex(ValueError,'leaves its source tree'):m.stage(source,output,bridges,'rogue',kernel)
    def test_make_hook_runs_after_generated_bridges(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source,kernel,output,bridges=self.fixture(root)
            build=source/'build/linux';(build/'kbuild').mkdir(parents=True)
            for name in ('kbuild/Makefile.template','toplevel.mk','defs.mk'):(build/name).write_text('.SECONDARY:\n')
            # Execute the patched entry with make, with bridge creation deferred to its prerequisite.
            (bridges/'bridge.c').unlink()
            rule=build/'kbuild/kbuild.mk'
            rule.write_text('''TOP := '''+str(source)+'''\nTARGET_PRIMARY_OUT := '''+str(output.parent)+'''\nBRIDGE_SOURCE_ROOT := '''+str(bridges)+'''\nPVR_ARCH := rogue\nKERNELDIR := '''+str(kernel)+'''\n.PHONY: kbuild kbuild_check bridges\n'''+m.TARGET+'''\t@test -f "$(TARGET_PRIMARY_OUT)/kbuild/generated/rogue/bridge.c"\n\t@test -f "$(TARGET_PRIMARY_OUT)/kbuild/services/server/env/linux/dkf_server.c"\nkbuild_check:\n\t@true\nbridges:\n\t@printf 'int bridge(void) { return 7; }\\n' > "$(BRIDGE_SOURCE_ROOT)/bridge.c"\n$(TARGET_PRIMARY_OUT)/kbuild/Makefile:\n\t@mkdir -p "$(dir $@)"\n\t@touch "$@"\n''')
            m.patch(source)
            subprocess.run(['make','-f',str(rule),'kbuild'],check=True,capture_output=True,text=True)
            self.assertTrue((output/'generated/rogue/bridge.c').is_file())

if __name__=='__main__':unittest.main()
