"""Run adapted compute checks against a controlled OpenCL backend and host Vulkan."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
DEPS=Path(os.environ.get('GPU_TEST_DEPS','/usr'))
HEADERS=DEPS/'include'

class OpenCLChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (HEADERS/'CL/cl.h').exists() or not shutil.which('gcc'):raise unittest.SkipTest('OpenCL test headers/gcc unavailable')
        cls.temp=tempfile.TemporaryDirectory();cls.binary=Path(cls.temp.name)/'check'
        subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-I'+str(HEADERS),str(BASE/'gpu/opencl-check.c'),str(BASE/'tests/opencl-stub.c'),'-o',str(cls.binary)],check=True,capture_output=True,text=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_execution_and_result_validation(self):
        for mode in ['good','no-platform','cpu-only','wrong-gpu','compile-failure','wrong-result','nan']:
            with self.subTest(mode=mode):
                r=subprocess.run([str(self.binary)],env=dict(os.environ,CL_TEST_MODE=mode),capture_output=True,text=True)
                self.assertEqual(r.returncode,0 if mode=='good' else 1,r.stdout+r.stderr)
                self.assertEqual('PASS:' in r.stdout,mode=='good')

class VulkanChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=os.environ.get('GPU_TEST_GLSLANG','glslangValidator')
        if not shutil.which(compiler) or not (HEADERS/'vulkan/vulkan.h').exists():raise unittest.SkipTest('Vulkan headers/glslang unavailable')
        cls.temp=tempfile.TemporaryDirectory();d=Path(cls.temp.name)
        subprocess.run([compiler,'-V',str(BASE/'gpu/gpu-shader.comp'),'-o',str(d/'shader.spv')],check=True,capture_output=True)
        subprocess.run(['python3',str(BASE/'gpu/shader-header.py'),str(d/'shader.spv'),str(d/'gpu-shader.h')],check=True)
        cls.shim=d/'enumeration.so'
        subprocess.run(['gcc','-shared','-fPIC','-Wall','-Wextra','-Werror','-I'+str(HEADERS),str(BASE/'tests/vulkan-enumeration-stub.c'),'-o',str(cls.shim)],check=True,capture_output=True,text=True)
        cls.binary=d/'check'
        subprocess.run(['gcc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(HEADERS),'-I'+str(d),str(BASE/'gpu/vulkan-check.c'),'-l:libvulkan.so.1','-o',str(cls.binary)],check=True,capture_output=True,text=True)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_missing_icd_cannot_pass(self):
        r=subprocess.run([str(self.binary)],env=dict(os.environ,VK_DRIVER_FILES='/nonexistent/pvr.json',VK_ICD_FILENAMES='/nonexistent/pvr.json'),capture_output=True,text=True,timeout=15)
        self.assertNotEqual(r.returncode,0);self.assertNotIn('PASS:',r.stdout)
    def test_cpu_and_other_gpu_cannot_pass(self):
        for mode in ('cpu','wrong-gpu'):
            with self.subTest(mode=mode):
                r=subprocess.run([str(self.binary)],env=dict(os.environ,LD_PRELOAD=str(self.shim),VK_TEST_MODE=mode),capture_output=True,text=True,timeout=15)
                self.assertNotEqual(r.returncode,0);self.assertNotIn('PASS:',r.stdout)

if __name__=='__main__':unittest.main()
