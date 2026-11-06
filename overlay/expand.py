#!/usr/bin/python3
"""Grow the mounted SD root using the proven bpi-zero-wbuild resize sequence."""
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid
sys.path.insert(0,'/usr/local/lib/opi-3w-wbuild')
from boot_status import atomic, write_status


def geometry(mbr, capacity, layout):
    if len(mbr)!=512 or mbr[510:]!=b'\x55\xaa':raise ValueError('Invalid MBR signature')
    if not 0<capacity<=0x100000000:raise ValueError('SD capacity exceeds supported MBR range')
    entries=[]
    for index in range(4):
        raw=mbr[446+16*index:462+16*index]
        start,count=struct.unpack_from('<II',raw,8)
        entries.append((raw[4],start,count))
    root,config=entries[:2]
    if entries[2][0] or entries[2][2] or entries[3][0] or entries[3][2]:
        raise ValueError('Unexpected additional partitions; no resize performed')
    if root[0]!=0x83 or config[0]!=0x0c:raise ValueError('Unexpected root/config partition types')
    if root[1]*512!=layout['root_start'] or config[1]*512!=layout['config_start'] or config[2]*512!=layout['config_bytes']:
        raise ValueError('Partition starts/config size differ from the built image')
    if not config[1] or config[1]+config[2]>root[1]:
        raise ValueError('Configuration partition must be entirely before root')
    if root[2]<layout['root_bytes']//512 or root[1]+root[2]>capacity:
        raise ValueError('Root partition is truncated or exceeds the card')
    sectors=capacity-root[1]
    if not 0<sectors<=0xffffffff:raise ValueError('Expanded root size is invalid')
    return dict(start=root[1],current=root[2],desired=sectors,capacity=capacity)


def filesystem(device):
    with open(device,'rb') as source:
        source.seek(1024);sb=source.read(1024)
    if len(sb)!=1024 or struct.unpack_from('<H',sb,56)[0]!=0xef53:raise ValueError('Root is not ext4')
    block_size=1024<<struct.unpack_from('<I',sb,24)[0]
    flags=struct.unpack_from('<I',sb,96)[0]
    blocks=struct.unpack_from('<I',sb,4)[0]
    if flags&0x80:blocks|=struct.unpack_from('<I',sb,336)[0]<<32
    return dict(uuid=str(uuid.UUID(bytes=sb[104:120])),block_size=block_size,blocks=blocks)


def write_size(device, original, sectors):
    if not 0<sectors<=0xffffffff:raise ValueError('Invalid partition size')
    changed=bytearray(original);struct.pack_into('<I',changed,458,sectors)
    with open(device,'r+b',buffering=0) as target:
        if target.read(512)!=original:raise ValueError('Partition table changed concurrently')
        target.seek(458);target.write(struct.pack('<I',sectors));os.fsync(target.fileno())
        target.seek(0)
        if target.read(512)!=changed:raise ValueError('Partition size write verification failed')


class System:
    root=Path('/')
    def path(self,name):return self.root/name.lstrip('/')
    def run(self,*args,timeout=30):
        return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    def devices(self):
        source=Path(self.run('findmnt','-n','-o','SOURCE','/').stdout.strip()).resolve(strict=True)
        if not re.fullmatch('mmcblk[0-9]+p1',source.name) or not source.is_block_device():
            raise ValueError('Mounted root must be SD/eMMC partition 1')
        sysroot=self.path('/sys/class/block/'+source.name)
        if int((sysroot/'partition').read_text())!=1:raise ValueError('Unexpected root partition number')
        parent=sysroot.resolve(strict=True).parent.name
        if not re.fullmatch('mmcblk[0-9]+',parent):raise ValueError('Unexpected root parent device')
        disk=self.path('/dev/'+parent)
        if not disk.is_block_device():raise ValueError('Root parent is not a block device')
        return source,disk,sysroot,self.path('/sys/class/block/'+parent)
    def status(self,stage,detail=''):write_status(stage,detail,self.root)


def probe(system):
    layout=json.loads(system.path('/usr/share/opi-3w-wbuild/layout.json').read_text())
    root,disk,sysroot,sysdisk=system.devices()
    capacity=int((sysdisk/'size').read_text())
    with disk.open('rb') as source:mbr=source.read(512)
    plan=geometry(mbr,capacity,layout)
    if int((sysroot/'start').read_text())!=plan['start']:
        raise ValueError('Kernel root start disagrees with partition table')
    fs=filesystem(root)
    if fs['uuid']!=layout['filesystem']['uuid']:raise ValueError('Root UUID differs from the built image')
    kernel_sectors=int((sysroot/'size').read_text())
    if fs['blocks']*fs['block_size']>kernel_sectors*512:
        raise ValueError('Filesystem exceeds the current kernel root device')
    return root,disk,sysroot,mbr,plan,fs,kernel_sectors


def check(system):
    root,disk,sysroot,mbr,plan,fs,kernel=probe(system)
    complete=(plan['current']==plan['desired'] and kernel==plan['desired']
              and fs['blocks']==plan['desired']*512//fs['block_size'])
    return dict(complete=complete,card_sectors=plan['capacity'],root_start=plan['start'],
                root_sectors=plan['current'],kernel_root_sectors=kernel,**fs)


def expand(system):
    state=system.path('/var/lib/opi-3w-wbuild')
    state.mkdir(parents=True,exist_ok=True)
    marker=state/'expanded.json'
    try:
        system.status('ROOT_EXPAND_STARTED')
        root,disk,sysroot,mbr,plan,fs,kernel=probe(system)
        if plan['current']!=plan['desired']:
            backup=state/'before-root-expand.mbr'
            if not backup.exists():
                fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as target:target.write(mbr);target.flush();os.fsync(target.fileno())
            # As in bpi-zero-wbuild: modify only the root size field.
            write_size(disk,mbr,plan['desired'])
        if int((sysroot/'size').read_text())!=plan['desired']:
            system.run('partx','--update','--nr','1',str(disk),timeout=30)
            try:system.run('udevadm','settle','--timeout=5',timeout=10)
            except subprocess.SubprocessError:pass
        if int((sysroot/'size').read_text())!=plan['desired']:
            raise RuntimeError('Kernel root size is not refreshed; retry on next boot')
        expected_blocks=plan['desired']*512//fs['block_size']
        if fs['blocks']!=expected_blocks:
            system.status('ROOT_FILESYSTEM_EXPANDING')
            system.run('resize2fs',str(root),timeout=180)
        after=check(system)
        if not after['complete']:
            raise RuntimeError('Filesystem has not reached the full root partition size')
        atomic(marker,json.dumps(after,indent=2)+'\n')
        (state/'resize-error').unlink(missing_ok=True)
        system.status('ROOT_EXPANDED',str(plan['desired']*512)+' root partition bytes')
        return True
    except Exception as error:
        marker.unlink(missing_ok=True)
        detail='Root expansion deferred ('+type(error).__name__+')'
        # Our explicit validation messages contain no credentials or command output.
        if isinstance(error,(ValueError,RuntimeError)):detail+=': '+str(error)
        atomic(state/'resize-error',detail+'\n')
        try:system.status('ROOT_EXPAND_DEFERRED',detail)
        except Exception:pass
        print(detail,flush=True)
        return False


if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Run as root')
    if sys.argv[1:]==['--check']:
        try:
            result=check(System());print(json.dumps(result));raise SystemExit(0 if result['complete'] else 1)
        except (OSError,ValueError,RuntimeError) as error:
            print(json.dumps(dict(complete=False,error=str(error))));raise SystemExit(1)
    elif len(sys.argv)==1:
        # Best effort, matching the established BPI behavior: don't block networking.
        expand(System())
    else:raise SystemExit('Usage: opi-3w-wbuild-expand [--check]')
