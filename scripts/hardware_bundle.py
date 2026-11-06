#!/usr/bin/env python3
"""Create and verify a reusable hardware-only archive from the mounted donor."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import stat
import subprocess
import tarfile
from board_profile import record
from boot_manifest import snapshot, verify as verify_boot
from donor_files import stage
from image_layout import inspect, regular, sha256, boot_header, BOOT0_OFFSET, TOC_OFFSET

TREES=('root/boot','root/lib/modules','root/usr/lib/firmware','root/vendor/etc/firmware',
       'root/etc/firmware','root/etc/modules-load.d','root/etc/modprobe.d')
FILES=('root/etc/modules',)


def allowed(name):
    return (name=='boot-prefix.bin' or name in FILES or
            any(name==tree or name.startswith(tree+'/') for tree in TREES) or
            (name.startswith('root/opt/linux-headers') and name.endswith('.deb') and name.count('/')==2))


def inventory(root):
    result={}
    for path in sorted(Path(root).rglob('*')):
        name=str(path.relative_to(root));mode=path.lstat().st_mode
        if name=='manifest.json' or stat.S_ISDIR(mode):continue
        if not allowed(name):raise ValueError('Not a hardware bundle path: '+name)
        if stat.S_ISLNK(mode):
            if not name.startswith('root/boot/'):raise ValueError('Only boot symlinks may be retained')
            link=os.readlink(path)
            target=posixpath.normpath('root/'+link.lstrip('/') if link.startswith('/') else posixpath.join(posixpath.dirname(name),link))
            if not target.startswith('root/boot/'):raise ValueError('Boot link requires an external OS artifact: '+name)
            result[name]={'link':link}
        elif stat.S_ISREG(mode):result[name]={'sha256':sha256(path),'bytes':path.stat().st_size}
        else:raise ValueError('Special file in hardware payload: '+name)
    return result


def filesystem(image,offset):
    import struct,uuid
    with open(image,'rb') as source:source.seek(offset+1024);sb=source.read(1024)
    if len(sb)!=1024 or struct.unpack_from('<H',sb,56)[0]!=0xef53:raise ValueError('Donor root is not ext4')
    return dict(uuid=str(uuid.UUID(bytes=sb[104:120])),feature_masks=list(struct.unpack_from('<III',sb,92)),
                block_size=1024<<struct.unpack_from('<I',sb,24)[0],inode_size=struct.unpack_from('<H',sb,88)[0])


def make_payload(image,donor,output,headers=None):
    image=regular(image);donor=Path(donor);output=Path(output)
    if output.exists():raise ValueError('Payload destination already exists')
    info=inspect(image)
    if len(info['partitions'])!=1 or info['partitions'][0]['number']!=1 or info['partitions'][0]['type']!=0x83:
        raise ValueError('Need the original single-root vendor image')
    output.mkdir(mode=0o700)
    stage(donor,output/'root')
    (output/'root/hardware-import.json').unlink()
    (output/'root/boot').mkdir()
    subprocess.run(['rsync','-aH','--numeric-ids','--',str(donor/'boot')+'/',str(output/'root/boot')+'/'],check=True)
    candidates=[Path(headers)] if headers else list((donor/'opt').glob('linux-headers*sun60iw2*.deb'))
    if len(candidates)>1:raise ValueError('Supply one matching kernel header package')
    if candidates:
        if not candidates[0].is_file():raise ValueError('Kernel header package is missing')
        (output/'root/opt').mkdir()
        shutil.copy2(candidates[0],output/'root/opt/linux-headers-opi-3w-wbuild-sun60iw2.deb')
    with image.open('rb') as source,(output/'boot-prefix.bin').open('wb') as target:
        left=info['boot_prefix_bytes']
        while left:
            block=source.read(min(left,1024*1024))
            if not block:raise ValueError('Truncated boot reserve')
            target.write(block);left-=len(block)
    modules=output/'root/lib/modules'
    abis=sorted(p.name for p in modules.iterdir() if p.is_dir())
    if abis!=['6.6.98-sun60iw2']:raise ValueError('Hardware bundle requires the known kernel ABI')
    manifest=dict(schema=1,board='Orange Pi Zero 3W',kernel_abi=abis[0],donor_sha256=sha256(image),
                  donor_layout=info,filesystem=filesystem(image,info['partitions'][0]['start']*512),
                  board_profile=record(donor),vendor_boot=snapshot(donor),entries=inventory(output))
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    validate(output)
    return manifest


def validate(directory):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text())
    if manifest.get('schema')!=1 or manifest.get('board')!='Orange Pi Zero 3W' or manifest.get('kernel_abi')!='6.6.98-sun60iw2':
        raise ValueError('Unsupported hardware bundle profile')
    if inventory(directory)!=manifest.get('entries'):raise ValueError('Hardware bundle file hashes/links do not match')
    prefix=directory/'boot-prefix.bin';info=manifest['donor_layout'];length=info['boot_prefix_bytes']
    if prefix.stat().st_size!=length:raise ValueError('Boot reserve size mismatch')
    if boot_header(prefix,BOOT0_OFFSET,'boot0',length)!=info['boot0'] or boot_header(prefix,TOC_OFFSET,'toc1',length)!=info['boot_package']:
        raise ValueError('Vendor boot payload mismatch')
    verify_boot(directory/'root',manifest['vendor_boot'])
    if record(directory/'root')!=manifest.get('board_profile'):
        raise ValueError('Selected DTB profile differs from the hardware manifest')
    return manifest


def pack(directory,output):
    directory=Path(directory);validate(directory)
    with open(output,'xb') as stream,tarfile.open(fileobj=stream,mode='w:gz',dereference=False) as archive:
        for path in sorted(directory.iterdir()):archive.add(path,arcname=path.name)


def unpack(archive_path,destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('Bundle extraction destination must be new')
    with tarfile.open(archive_path,'r:gz') as archive:
        members=archive.getmembers();names=[m.name for m in members]
        if len(names)!=len(set(names)):raise ValueError('Duplicate archive member')
        if sum(m.size for m in members)>4*1024**3:raise ValueError('Hardware archive exceeds 4 GiB extracted')
        by_name={m.name:m for m in members}
        metadata=by_name.get('manifest.json')
        if not metadata or not metadata.isfile() or metadata.size>8*1024**2:raise ValueError('Missing/invalid bundle manifest')
        manifest=json.load(archive.extractfile(metadata))
        if not isinstance(manifest.get('entries'),dict):raise ValueError('Invalid bundle inventory')
        symlinks={m.name for m in members if m.issym()}
        for member in members:
            name=member.name;parts=PurePosixPath(name).parts
            if not parts or name.startswith('/') or '..' in parts or name!=posixpath.normpath(name):raise ValueError('Unsafe archive path')
            if any(name.startswith(link+'/') for link in symlinks):raise ValueError('Archive member beneath a symlink')
            if member.isdir():
                if name not in ('root','root/lib','root/usr','root/usr/lib','root/etc','root/vendor','root/vendor/etc','root/opt') and not any(name==t or name.startswith(t+'/') for t in TREES):
                    raise ValueError('Unexpected directory in hardware archive')
            elif name!='manifest.json' and (name not in manifest['entries'] or not allowed(name)):
                raise ValueError('Unexpected file in hardware archive')
            if member.issym():
                link=member.linkname
                target=posixpath.normpath('root/'+link.lstrip('/') if link.startswith('/') else posixpath.join(posixpath.dirname(name),link))
                if not name.startswith('root/boot/') or not target.startswith('root/boot/'):
                    raise ValueError('Unsafe boot symlink')
            elif member.islnk():
                target=by_name.get(member.linkname)
                if not target or not target.isfile():raise ValueError('Unsafe archive hardlink')
            elif not (member.isdir() or member.isfile()):raise ValueError('Unsupported archive member type')
        files={m.name for m in members if not m.isdir() and m.name!='manifest.json'}
        if files!=set(manifest['entries']):raise ValueError('Archive inventory mismatch')
        destination.mkdir(mode=0o700)
        # Extract data before boot symlinks, preventing traversal through a link.
        archive.extractall(destination,members=[m for m in members if not m.issym()],filter='data')
        for member in members:
            if member.issym():(destination/member.name).symlink_to(member.linkname)
    return validate(destination)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('create');a.add_argument('image');a.add_argument('donor');a.add_argument('directory');a.add_argument('--headers')
    a=sub.add_parser('pack');a.add_argument('directory');a.add_argument('output')
    a=sub.add_parser('unpack');a.add_argument('archive');a.add_argument('directory')
    a=sub.add_parser('verify');a.add_argument('directory')
    a=p.parse_args()
    if a.command=='create':make_payload(a.image,a.donor,a.directory,a.headers)
    elif a.command=='pack':pack(a.directory,a.output)
    elif a.command=='unpack':unpack(a.archive,a.directory)
    else:validate(a.directory)
