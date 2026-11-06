#!/usr/bin/python3
"""Verify the running opi-3w-wbuild and execute real GPU checks; save reviewable evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0,'/usr/local/lib/opi-3w-wbuild')
from pvr_version import canonical_ddk, EXPECTED_DDK
from boot_manifest import verify as verify_boot

RUNTIME=Path('/opt/opi-3w-wbuild-powervr')
REQUIRED_SERVICES=('opi-3w-wbuild-boot-status','opi-3w-wbuild-expand','opi-3w-wbuild-firstboot','NetworkManager','ssh')


class System:
    def __init__(self, root='/'):
        self.root=Path(root)
    def path(self, name): return self.root/str(name).lstrip('/')
    def text(self, name): return self.path(name).read_text(errors='replace')
    def exists(self, name): return self.path(name).exists()
    def run(self, *args):
        started=time.monotonic()
        try:
            result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=90)
            return dict(code=result.returncode,output=result.stdout,elapsed_ms=round((time.monotonic()-started)*1000))
        except subprocess.TimeoutExpired:
            return dict(code=124,output='Command timed out',elapsed_ms=round((time.monotonic()-started)*1000))
        except OSError as error:
            return dict(code=127,output=str(error),elapsed_ms=round((time.monotonic()-started)*1000))


class Verification:
    def __init__(self, system):
        self.system=system
        self.report={'schema':1,'created_utc':datetime.now(timezone.utc).isoformat(),
                     'scope':'running opi-3w-wbuild and small GPU computations; NPU inference not tested',
                     'checks':[],'evidence':{}}
    def add(self,name,status,detail):
        self.report['checks'].append(dict(name=name,status=status,detail=detail))
    def attempt(self,name,operation):
        try: operation()
        except Exception as error: self.add(name,'FAIL',str(error))
    def command(self,name,*args):
        result=self.system.run(*args)
        self.report['evidence'][name]=result
        return result
    def identity(self):
        s=self.system
        model=s.text('/proc/device-tree/model').replace('\x00','').strip()
        compatible=s.text('/proc/device-tree/compatible').replace('\x00',' ')
        architecture=self.command('architecture','uname','-m')
        release=self.command('kernel','uname','-r')
        self.report['identity']={'model':model,'compatible':compatible,'architecture':architecture['output'].strip(),'kernel':release['output'].strip(),
                                 'release':s.text('/etc/opi-3w-wbuild-release').strip()}
        profile=json.loads(s.text('/usr/share/opi-3w-wbuild/board-profile.json'))
        dtb='allwinner/sun60i-a733-orangepi-zero3w.dtb'
        env=dict(line.split('=',1) for line in s.text('/boot/orangepiEnv.txt').splitlines()
                 if '=' in line and not line.lstrip().startswith('#'))
        actual_compatible=s.text('/proc/device-tree/compatible').strip('\x00').split('\x00')
        ok=(profile.get('board')=='Orange Pi Zero 3W' and profile.get('dtb')==dtb
            and env.get('fdtfile','').strip()==dtb
            and self.hash_file('/boot/dtb/'+dtb)==profile.get('dtb_sha256')
            and model==profile.get('model') and actual_compatible==profile.get('compatible')
            and architecture['code']==0 and architecture['output'].strip()=='aarch64')
        self.add('board','PASS' if ok else 'FAIL','Live DT metadata and selected Zero 3W DTB must match the recorded vendor profile')
        if ok and 'xunlong,orangepi-4-pro' in actual_compatible:
            self.add('vendor_board_label','WARN','Vendor Zero 3W DTS contains the 4-Pro compatibility label; DTB selection and hash were checked')
        os_release=s.text('/etc/os-release')
        def os_identity(text):
            fields=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
            return {k:fields.get(k,'').strip('"\'') for k in ('ID','VERSION_ID')}
        actual=os_identity(os_release)
        self.add('debian','PASS' if actual=={'ID':'debian','VERSION_ID':'13'} else 'FAIL',str(actual))
        manifest=json.loads(s.text(RUNTIME/'manifest.json'))
        self.manifest=manifest
        ok=release['code']==0 and release['output'].strip()==manifest['kernel_abi']
        self.add('kernel','PASS' if ok else 'FAIL','Running kernel must match PowerVR manifest: '+manifest['kernel_abi'])
    def ramdisk(self):
        expected=json.loads(self.system.text('/usr/share/opi-3w-wbuild/vendor-boot.json'))
        verify_boot(self.system.root,expected)
        self.add('vendor_boot','PASS','All donor /boot files and symlinks remain unchanged')
    def provision(self):
        s=self.system
        for name in ('configured',):
            self.add('firstboot_'+name,'PASS' if s.exists('/var/lib/opi-3w-wbuild/'+name) else 'FAIL',name+' completion marker')
        for service in REQUIRED_SERVICES:
            result=self.command('service_'+service,'systemctl','is-active',service+'.service')
            self.add('service_'+service,'PASS' if result['code']==0 and result['output'].strip()=='active' else 'FAIL',result['output'].strip())
        result=self.command('failed_units','systemctl','--failed','--no-legend','--plain','--no-pager')
        self.add('failed_units','PASS' if result['code']==0 and not result['output'].strip() else 'FAIL',result['output'].strip() or 'No failed systemd units')
        result=self.command('clock','timedatectl','show','-p','NTPSynchronized','--value')
        self.add('clock_sync','PASS' if result['code']==0 and result['output'].strip()=='yes' else 'WARN','NTP synchronization state: '+result['output'].strip())
        machine=s.text('/etc/machine-id').strip()
        self.add('machine_id','PASS' if re.fullmatch('[0-9a-f]{32}',machine) and machine!='0'*32 else 'FAIL','Machine ID format only; uniqueness requires comparison with another card')
        keys=self.command('ssh_key','ssh-keygen','-lf','/etc/ssh/ssh_host_ed25519_key.pub')
        self.add('ssh_host_key','PASS' if keys['code']==0 else 'FAIL',keys['output'].strip())
    def network(self):
        interface=self.system.text('/var/lib/opi-3w-wbuild/wifi-interface').strip()
        if not re.fullmatch('[A-Za-z0-9_.-]+',interface):raise ValueError('Missing valid provisioned Wi-Fi interface')
        result=self.command('wifi_address','ip','-j','-4','address','show','dev',interface)
        addresses=json.loads(result['output']) if result['code']==0 else []
        assigned=[a['local'] for item in addresses for a in item.get('addr_info',[]) if a.get('scope')=='global']
        self.add('wifi_ipv4','PASS' if assigned else 'FAIL',', '.join(assigned) or 'No global Wi-Fi IPv4')
        # Do not collect SSIDs, NetworkManager profiles or CONFIG.TXT credentials.
    def storage(self):
        for mount,kind in (('/','ext4'),('/config','vfat')):
            result=self.command('mount_'+kind,'findmnt','-J','--mountpoint',mount,'-o','SOURCE,FSTYPE,OPTIONS')
            data=json.loads(result['output']) if result['code']==0 else {}
            mounts=data.get('filesystems',[])
            ok=bool(mounts and mounts[0].get('fstype')==kind and 'rw' in mounts[0].get('options','').split(','))
            self.add('mount_'+kind,'PASS' if ok else 'FAIL',mount+' must be mounted read-write as '+kind)
            if mount=='/' and mounts:self.root_source=mounts[0]['source']
        result=self.command('disk_space','df','-h','/','/config')
        self.add('disk_space','PASS' if result['code']==0 else 'FAIL',result['output'].strip())
        source=getattr(self,'root_source','')
        actual=self.command('root_uuid','blkid','-s','UUID','-o','value',source)
        layout=json.loads(self.system.text('/usr/share/opi-3w-wbuild/layout.json'))
        root_uuid=layout['filesystem']['uuid']
        declared=dict(line.split('=',1) for line in self.system.text('/boot/orangepiEnv.txt').splitlines() if '=' in line)
        ok=actual['code']==0 and actual['output'].strip()==root_uuid
        rootdev=declared.get('rootdev','')
        if rootdev.startswith('UUID='):ok=ok and rootdev=='UUID='+root_uuid
        elif rootdev.startswith('PARTUUID='):
            part=self.command('root_partuuid','blkid','-s','PARTUUID','-o','value',source)
            ok=ok and part['code']==0 and rootdev=='PARTUUID='+part['output'].strip()
        self.add('boot_root','PASS' if ok else 'FAIL','Mounted root UUID must equal the preserved donor UUID')
        expansion=self.command('root_expansion','opi-3w-wbuild-expand','--check')
        data=json.loads(expansion['output']) if expansion['code'] in (0,1) else {}
        self.report['root_expansion']=data
        self.add('root_expansion','PASS' if expansion['code']==0 and data.get('complete') is True else 'FAIL',
                 'Root partition and ext4 must fill the remaining SD capacity')
    def hash_file(self,path):
        digest=hashlib.sha256()
        with self.system.path(path).open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
        return digest.hexdigest()
    def integrity(self):
        files=json.loads(self.system.text(RUNTIME/'manifest.json')).get('files',{})
        if not files:raise ValueError('Runtime manifest has no file hashes')
        errors=[]
        for name,expected in files.items():
            p=Path(name)
            if p.is_absolute() or '..' in p.parts:raise ValueError('Invalid runtime hash path')
            try:
                if self.hash_file(p)!=expected:errors.append(name)
            except OSError:errors.append(name)
        self.add('runtime_integrity','FAIL' if errors else 'PASS',', '.join(errors) if errors else str(len(files))+' runtime files match build hashes')
        # Root-owned generated GNU sha256 manifest: validate boot, modules and firmware.
        result=self.command('hardware_integrity','bash','-c','cd / && sha256sum --check --quiet /usr/share/opi-3w-wbuild/hardware.sha256')
        self.add('hardware_integrity','PASS' if result['code']==0 else 'FAIL',result['output'].strip() or 'Boot, module and firmware hashes match')
    def snapshot(self):
        s=self.system;memory={}
        for line in s.text('/proc/meminfo').splitlines():
            key,_,value=line.partition(':')
            if key in ('MemTotal','MemAvailable','CmaTotal','CmaFree','SwapTotal','SwapFree'):memory[key]=value.strip()
        self.report['memory']=memory
        temperatures={}
        for path in s.path('/sys/class/thermal').glob('thermal_zone*/temp'):
            temperatures[path.parent.name]=path.read_text().strip()
        clocks={}
        for path in s.path('/sys/class/devfreq').glob('*/cur_freq'):
            clocks[path.parent.name]=path.read_text().strip()
        return {'memory':memory,'temperatures_millidegrees_c':temperatures,'devfreq_hz':clocks}
    def gpu(self):
        capabilities={}
        for name,marker in (('opencl','compiled and executed an OpenCL kernel; results verified'),('vulkan','executed a Vulkan compute shader; results verified')):
            result=self.command(name,'timeout','--kill-after=5','75','opi-3w-wbuild-gpu-run',str(RUNTIME/'bin'/f'{name}-check'))
            ok=result['code']==0 and ('PASS: PowerVR BXM-4-64 '+marker) in result['output']
            self.add(name+'_compute','PASS' if ok else 'FAIL',result['output'].strip() or 'No diagnostic output')
            capabilities[name+'_test_elapsed_ms']=result['elapsed_ms']
            for line in result['output'].splitlines():
                if line.startswith('OpenCL: '):capabilities['opencl_api']=line[8:]
                elif line.startswith('Driver: '):capabilities['opencl_driver']=line[8:]
                elif line.startswith('FP16 extension: '):capabilities['opencl_fp16_advertised']=line.endswith(': present')
                elif line.startswith('Vulkan device API: '):capabilities['vulkan_api']=line[19:]
        capabilities['timing_scope']='Whole tiny test process including startup/compilation; not a throughput benchmark'
        self.report['gpu_capabilities']=capabilities
        version_path='/sys/module/pvrsrvkm/parameters/opi_3w_wbuild_ddk' if self.system.exists('/sys/module/pvrsrvkm/parameters/opi_3w_wbuild_ddk') else '/sys/module/pvrsrvkm/version'
        result=self.command('gpu_module_version','cat',version_path)
        self.report['gpu_capabilities']['ddk_metadata_source']=version_path
        canonical=canonical_ddk(result['output'])
        self.report['gpu_capabilities']['ddk_version_canonical']=canonical
        ok=result['code']==0 and canonical==EXPECTED_DDK
        self.add('loaded_gpu_ddk','PASS' if ok else 'FAIL',result['output'].strip())
    def npu(self):
        self.report['npu']={'module_present':self.system.exists('/sys/module/vipcore'),
                            'device_present':self.system.exists('/dev/vipcore'),
                            'driver_version':self.system.text('/sys/module/vipcore/version').strip() if self.system.exists('/sys/module/vipcore/version') else None,
                            'inference_validated':False,
                            'reason':'Requires a matching VIPLite runtime and known NBG model with reference results'}
        self.add('npu_inference','NOT_TESTED','GPU execution does not validate the NPU; readiness observations only')
    def run(self):
        for name,operation in (('identity',self.identity),('vendor_boot',self.ramdisk),('provision',self.provision),('network',self.network),('storage',self.storage),('integrity',self.integrity)):
            self.attempt(name,operation)
        try:self.report['before_compute']=self.snapshot()
        except Exception as error:self.add('memory_thermal','WARN',str(error))
        required=('board','debian','kernel','boot_root','vendor_boot','runtime_integrity','hardware_integrity')
        states={c['name']:c['status'] for c in self.report['checks']}
        if all(states.get(name)=='PASS' for name in required):
            self.attempt('gpu_tests',self.gpu)
        else:
            self.add('gpu_tests','NOT_TESTED','GPU tests blocked by board, kernel or integrity failure')
        self.attempt('npu_readiness',self.npu)
        try:self.report['after_compute']=self.snapshot()
        except Exception as error:self.add('post_compute_snapshot','WARN',str(error))
        result=self.command('kernel_log','dmesg','--color=never')
        self.report['evidence']['kernel_log']['output']='\n'.join(line for line in result['output'].splitlines() if any(k in line.lower() for k in ('pvr','rgx','vipcore','gpu','thermal','out of memory')))
        self.report['build_passed']=all(c['status']!='FAIL' for c in self.report['checks'])
        self.report['npu_inference_validated']=False
        return self.report


def summary(report):
    lines=['opi-3w-wbuild verification: '+('PASS' if report['build_passed'] else 'FAIL')]
    lines += [f"{c['status']:10} {c['name']}: {c['detail']}" for c in report['checks']]
    lines += ['NPU inference: NOT TESTED. Small GPU success does not prove model compatibility or sustained performance.']
    return '\n'.join(lines)+'\n'


def save_report(report, parent):
    parent=Path(parent);parent.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='verification-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-',dir=parent))
    report['bundle']=str(folder)+'.tar.gz'
    (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (folder/'report.txt').write_text(summary(report))
    for name,result in report['evidence'].items():
        (folder/(re.sub('[^a-zA-Z0-9_-]','_',name)+'.log')).write_text(result['output'])
    with tarfile.open(report['bundle'],'w:gz') as archive:archive.add(folder,arcname=folder.name)
    return report['bundle']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',help='Parent directory for a new report bundle; default /var/log/opi-3w-wbuild')
    parser.add_argument('--json',action='store_true',help='Print JSON instead of the text summary')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.exit(2,'Run sudo opi-3w-wbuild-verify\n')
    os.umask(0o077)
    report=Verification(System()).run()
    save_report(report,args.output or '/var/log/opi-3w-wbuild')
    if args.json:print(json.dumps(report,indent=2))
    else:print(summary(report)+'Evidence: '+report['bundle'])
    return 0 if report['build_passed'] else 1

if __name__=='__main__':raise SystemExit(main())
