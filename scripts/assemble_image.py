#!/usr/bin/env python3
"""Assemble a compact fresh filesystem with the extracted vendor boot path."""
import argparse,json,os,struct,subprocess
from pathlib import Path
from hardware_bundle import validate,filesystem
from image_layout import inspect,sha256,MIB
from boot_manifest import verify as verify_boot
from boot_allocation import normalize_filesystem

FEATURES='none,has_journal,ext_attr,resize_inode,dir_index,filetype,extent,flex_bg,sparse_super,large_file,huge_file,dir_nlink,extra_isize'

def plan(bundle,image_mib=2048):
    m=validate(bundle);fs=m['filesystem']
    if fs['feature_masks']!=[60,578,107] or fs['block_size']!=4096 or fs['inode_size']!=256:
        raise ValueError('Unsupported vendor ext4 profile; refusing host mkfs defaults')
    if not 512<=image_mib<=32768:raise ValueError('Image size outside supported limits')
    config_start=((m['donor_layout']['boot_prefix_bytes']+MIB-1)//MIB)*MIB
    root_start=config_start+64*MIB
    return dict(image_bytes=image_mib*MIB,root_start=root_start,root_bytes=image_mib*MIB-root_start,
                config_start=config_start,config_bytes=64*MIB,filesystem=fs)

def verify(bundle,output,layout):
    m=validate(bundle);prefix=Path(bundle)/'boot-prefix.bin';result=inspect(output)
    for key in ('boot0','boot_package'):
        if result[key]!=m['donor_layout'][key]:raise ValueError('Vendor boot payload changed')
    length=prefix.stat().st_size-512
    if sha256(prefix,512,length)!=sha256(output,512,length):raise ValueError('Reserved boot data changed')
    with prefix.open('rb') as f:before=f.read(512)
    with open(output,'rb') as f:after=f.read(512)
    allowed=set(range(454,478))
    if any(a!=b for i,(a,b) in enumerate(zip(before,after)) if i not in allowed):raise ValueError('Unexpected MBR change')
    expected=[(1,0x83,layout['root_start']//512,layout['root_bytes']//512),(2,0x0c,layout['config_start']//512,layout['config_bytes']//512)]
    if [(p['number'],p['type'],p['start'],p['sectors']) for p in result['partitions']]!=expected:raise ValueError('Unexpected partition geometry')
    if filesystem(output,layout['root_start'])!=layout['filesystem']:raise ValueError('Filesystem profile changed')

def build(bundle,root,fat,rootfs,output,layout,normalizer=normalize_filesystem):
    if plan(bundle,layout['image_bytes']//MIB)!=layout:raise ValueError('Stale assembly plan')
    m=validate(bundle);verify_boot(root,m['vendor_boot'])
    fat=Path(fat)
    with fat.open('rb') as f:h=f.read(512)
    if fat.stat().st_size!=layout['config_bytes'] or h[82:90]!=b'FAT32   ' or h[510:]!=b'\x55\xaa' or struct.unpack_from('<I',h,32)[0]!=layout['config_bytes']//512:
        raise ValueError('Invalid FAT32 configuration payload')
    with open(rootfs,'xb') as f:f.truncate(layout['root_bytes'])
    subprocess.run(['mkfs.ext4','-F','-b','4096','-I','256','-O',FEATURES,'-U',layout['filesystem']['uuid'],'-m','2','-L','opi-3w-wbuild','-d',str(root),str(rootfs)],check=True)
    if filesystem(rootfs,0)!=layout['filesystem']:raise ValueError('mkfs did not preserve the vendor profile')
    # mkfs -d may introduce holes in zero-filled parts of kernel/DTB files.
    # Normal file writes on the actual ext4 volume avoid that boot-reader path.
    normalizer(rootfs,m['vendor_boot'])
    if filesystem(rootfs,0)!=layout['filesystem']:raise ValueError('Boot allocation changed the filesystem profile')
    subprocess.run(['e2fsck','-fn',str(rootfs)],check=True)
    output=Path(output);fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb') as target:
            target.truncate(layout['image_bytes'])
            for source,offset in [(Path(bundle)/'boot-prefix.bin',0),(fat,layout['config_start']),(Path(rootfs),layout['root_start'])]:
                target.seek(offset)
                with source.open('rb') as incoming:
                    while block:=incoming.read(MIB):
                        if block.count(0)==len(block):target.seek(len(block),1)
                        else:target.write(block)
            with (Path(bundle)/'boot-prefix.bin').open('rb') as f:mbr=bytearray(f.read(512))
            struct.pack_into('<II',mbr,454,layout['root_start']//512,layout['root_bytes']//512)
            mbr[462:478]=struct.pack('<B3sB3sII',0,b'\xfe\xff\xff',0x0c,b'\xfe\xff\xff',layout['config_start']//512,layout['config_bytes']//512)
            target.seek(0);target.write(mbr);target.flush();os.fsync(target.fileno())
        verify(bundle,output,layout)
    except BaseException:
        output.unlink(missing_ok=True);raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('plan');a.add_argument('bundle');a.add_argument('image_mib',type=int)
    a=s.add_parser('build')
    for name in ('bundle','root','fat','rootfs','output','layout'):a.add_argument(name)
    a=p.parse_args()
    if a.command=='plan':print(json.dumps(plan(a.bundle,a.image_mib),indent=2))
    else:build(a.bundle,a.root,a.fat,a.rootfs,a.output,json.loads(Path(a.layout).read_text()))
