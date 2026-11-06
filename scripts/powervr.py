#!/usr/bin/env python3
"""Install selected pinned compute libraries without installing vendor Xorg."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import struct
import subprocess
import tempfile
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"lib"))
from pvr_version import canonical_ddk, EXPECTED_DDK
from donor_files import Donor

LIBRARIES = ('libPVROCL','libVK_IMG','libsrv_um','libusc','libufwriter','libpvr_dri_support','libglslcompiler')
EXTRA_LIBRARIES = ('usr/local/lib/libpvr_mesa_wsi.so',)
PREFIX = Path('opt/opi-3w-wbuild-powervr')


def check_elf(path):
    header=Path(path).read_bytes()[:20]
    if len(header)!=20 or header[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',header,18)[0]!=183:
        raise ValueError('Expected ARM64 ELF library: '+str(path))


def check_module(abi, vermagic, version):
    if vermagic.split()[:1]!=[abi]: raise ValueError('PowerVR module kernel ABI mismatch')
    if canonical_ddk(version)!=EXPECTED_DDK:
        raise ValueError(f'PowerVR module must be DDK {EXPECTED_DDK}; reported version: {version!r}')


def module_ddk(path):
    value=subprocess.check_output(['modinfo','-F','opi_3w_wbuild_ddk',str(path)],text=True).strip()
    if not value:
        value=subprocess.check_output(['modinfo','-F','version',str(path)],text=True).strip()
    return value


def install_runtime(extracted, root, pins):
    donor=Donor(extracted)
    root=Path(root)
    runtime=root/PREFIX
    (runtime/'lib').mkdir(parents=True, exist_ok=True)
    files=[]
    for stem in LIBRARIES:
        relative='usr/lib/'+stem+'.so.'+pins['ddk']
        source=donor.resolve(relative)
        check_elf(source)
        target=runtime/'lib'/source.name
        shutil.copy2(source,target)
        target.chmod(0o644)
        for alias in (stem+'.so',stem+'.so.1'):
            (runtime/'lib'/alias).symlink_to(target.name)
        files.append(str(target.relative_to(root)))
    # Vulkan loads this helper with dlopen, so libVK_IMG's ldd output misses it.
    for relative in EXTRA_LIBRARIES:
        source=donor.resolve(relative)
        check_elf(source)
        target=runtime/'lib'/source.name
        shutil.copy2(source,target)
        target.chmod(0o644)
        files.append(str(target.relative_to(root)))
    firmware=root/'usr/lib/firmware';firmware.mkdir(parents=True, exist_ok=True)
    for stem in ('rgx.fw.','rgx.sh.'):
        source=donor.resolve('lib/firmware/'+stem+pins['bvnc'])
        target=firmware/source.name
        shutil.copy2(source,target);target.chmod(0o644)
        files.append(str(target.relative_to(root)))
    (runtime/'OpenCL').mkdir(exist_ok=True)
    (runtime/'OpenCL/pvr.icd').write_text('/'+str(PREFIX/'lib/libPVROCL.so')+'\n')
    (runtime/'img_icd.json').write_text(json.dumps({'file_format_version':'1.0.0','ICD':{
        'library_path':'/'+str(PREFIX/'lib/libVK_IMG.so'),'api_version':'1.3.277'}},indent=2)+'\n')
    manifest=dict(pins, hardware_validated=False, files={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files})
    (runtime/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


def preflight(hardware, donor, inputs, pins):
    abi=pins['kernel_abi']
    modules=Path(hardware)/'lib/modules'
    if sorted(p.name for p in modules.iterdir()) != [abi]:
        raise ValueError('PowerVR candidate requires kernel '+abi)
    for path in (modules/abi).rglob('pvrsrvkm.ko*'):
        if not path.is_file(): continue
        try:
            magic=subprocess.check_output(['modinfo','-F','vermagic',str(path)],text=True).strip()
            version=module_ddk(path)
            check_module(abi,magic,version)
            return 'Matching donor PowerVR module available'
        except (ValueError,subprocess.CalledProcessError): continue
    supplied=Path(inputs)/'kernel-headers.deb'
    if supplied.is_file(): return 'Will build PowerVR using inputs/kernel-headers.deb'
    try: opt=Donor(donor).resolve('opt')
    except FileNotFoundError: opt=None
    headers=list(opt.glob('linux-headers*sun60iw2*.deb')) if opt else []
    if len(headers)!=1:
        raise ValueError('No matching donor PowerVR module. Need one donor /opt/linux-headers*sun60iw2*.deb or inputs/kernel-headers.deb for '+abi)
    return 'Will build PowerVR using donor kernel headers'


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    runtime=sub.add_parser('runtime')
    for name in ('root','work','pins'):runtime.add_argument(name)
    pre=sub.add_parser('preflight')
    for name in ('hardware','donor','inputs','pins'):pre.add_argument(name)
    args=parser.parse_args();pins=json.loads(Path(args.pins).read_text())
    if args.command=='preflight':
        print(preflight(args.hardware,args.donor,args.inputs,pins));return
    work=Path(args.work);work.mkdir(parents=True,exist_ok=True)
    package=work/'powervr.deb'
    with urllib.request.urlopen(pins['userspace_url'],timeout=120) as source, package.open('wb') as output:
        shutil.copyfileobj(source,output)
    if hashlib.sha256(package.read_bytes()).hexdigest()!=pins['userspace_sha256']:
        raise ValueError('PowerVR package checksum mismatch')
    extracted=work/'userspace';extracted.mkdir()
    subprocess.run(['dpkg-deb','-x',str(package),str(extracted)],check=True)
    install_runtime(extracted,args.root,pins)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        raise SystemExit('PowerVR preparation failed: '+str(error))
