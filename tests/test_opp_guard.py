import subprocess
from pathlib import Path
import shutil
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]


class OPPGuardTests(unittest.TestCase):
    def source(self,callback):
        return '''#include <stdio.h>
#include <stdarg.h>
typedef char IMG_CHAR;
typedef struct { void *pvPrivData; } OSDI_IMPL_ENTRY;
struct opp { unsigned long ui32Freq; unsigned long ui32Volt; };
struct sunxi_platform {
#if defined(SUPPORT_PDVFS) || defined(SUPPORT_LINUX_DVFS)
    struct opp asOPPTable[1]; unsigned int ui32OPPTableSize;
#else
    int unused;
#endif
};
void DIPrintf(const OSDI_IMPL_ENTRY *entry, const IMG_CHAR *format, ...) {
    (void)entry; va_list arguments; va_start(arguments,format);
    vprintf(format,arguments); va_end(arguments);
}
'''+callback+'''
int main(void) {
    struct sunxi_platform data={0};
#if defined(SUPPORT_PDVFS) || defined(SUPPORT_LINUX_DVFS)
    data.asOPPTable[0].ui32Freq=1000000;
    data.asOPPTable[0].ui32Volt=900000;
    data.ui32OPPTableSize=1;
#endif
    OSDI_IMPL_ENTRY entry={&data};
    return _DebugDumpOppInfoDIShow(&entry,0);
}
'''
    def test_vendor_failure_reproduced_and_all_guards_work(self):
        if not shutil.which('gcc') or not shutil.which('patch'):self.skipTest('gcc/patch unavailable')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            original=(BASE/'tests/fixtures/sunxi-opp-original.c').read_text()
            unit=root/'check.c';unit.write_text(self.source(original))
            command=['gcc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(unit),'-o',str(root/'probe')]
            before=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(before.returncode,0)
            self.assertIn('ui32OPPTableSize',before.stderr)
            target=root/'services/system/rogue/rgx_sunxi/sunxi_platform.c'
            target.parent.mkdir(parents=True);target.write_text(original)
            with (BASE/'gpu/sunxi-opp-guard.patch').open() as patch:
                subprocess.run(['patch','--batch','--fuzz=0','-p1','-d',str(root)],stdin=patch,check=True,capture_output=True,text=True)
            unit.write_text(self.source(target.read_text()))
            for defines in ([],['-DSUPPORT_LINUX_DVFS=1'],['-DSUPPORT_PDVFS=1'],['-DSUPPORT_LINUX_DVFS=1','-DSUPPORT_PDVFS=1']):
                with self.subTest(defines=defines):
                    subprocess.run(command+defines,check=True,capture_output=True,text=True)
                    result=subprocess.run([str(root/'probe')],capture_output=True,text=True)
                    self.assertEqual(result.returncode,0)
                    self.assertIn('opp0 is 1000000Hz---900mV' if defines else 'DVFS support disabled',result.stdout)

if __name__=='__main__':unittest.main()
