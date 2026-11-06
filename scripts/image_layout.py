#!/usr/bin/env python3
"""Inspect MBR/Allwinner boot images. Regular files only; no physical disks."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import struct

SECTOR=512
MIB=1024*1024
BOOT0_OFFSET=8192
TOC_OFFSET=2050*8192
STAMP=0x5F0A6C39


def regular(path):
    path=Path(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Only regular image files are accepted; block devices are forbidden')
    return path


def sha256(path,offset=0,length=None):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        f.seek(offset)
        while length is None or length>0:
            data=f.read(1024*1024 if length is None else min(1024*1024,length))
            if not data:break
            h.update(data)
            if length is not None:length-=len(data)
    if length is not None and length:raise ValueError('Truncated hash region')
    return h.hexdigest()


def partitions(mbr,total_bytes):
    if len(mbr)!=512 or mbr[510:]!=b'\x55\xaa':raise ValueError('Invalid MBR signature')
    result=[]
    for i in range(4):
        entry=mbr[446+i*16:462+i*16]
        kind=entry[4];start,count=struct.unpack_from('<II',entry,8)
        if not kind and not count:continue
        if kind in (0xEE,0x05,0x0F,0x85):raise ValueError('GPT and extended partitions are not supported in this initial build')
        if not count or start<1 or (start+count)*512>total_bytes:raise ValueError('Partition exceeds donor image')
        result.append(dict(number=i+1,type=kind,start=start,sectors=count))
    ordered=sorted(result,key=lambda p:p['start'])
    if not ordered:raise ValueError('No donor partitions')
    for a,b in zip(ordered,ordered[1:]):
        if a['start']+a['sectors']>b['start']:raise ValueError('Overlapping donor partitions')
    return result


def boot_header(path,offset,kind,limit):
    with open(path,'rb') as f:
        f.seek(offset);header=f.read(64)
        if len(header)!=64:raise ValueError('Missing boot header')
        if kind=='boot0':
            if header[4:12]!=b'eGON.BT0':raise ValueError('Missing unencrypted eGON Boot0 at 8 KiB')
            length=struct.unpack_from('<I',header,16)[0];checksum_offset=12
        else:
            if not header[:16].startswith(b'sunxi-package') or struct.unpack_from('<I',header,16)[0]!=0x89119800:
                raise ValueError('Missing sunxi-package TOC1 at the supported A733 offset')
            length=struct.unpack_from('<I',header,36)[0];checksum_offset=20
        if length<64 or length%4 or offset+length>limit:
            raise ValueError(f'{kind} length is invalid or overlaps donor partitions')
        f.seek(offset);data=bytearray(f.read(length))
    expected=struct.unpack_from('<I',data,checksum_offset)[0]
    struct.pack_into('<I',data,checksum_offset,STAMP)
    actual=sum(struct.unpack('<'+str(length//4)+'I',data))&0xFFFFFFFF
    if actual!=expected:raise ValueError(f'{kind} checksum mismatch')
    return dict(offset=offset,length=length,sha256=sha256(path,offset,length))


def inspect(path):
    path=regular(path)
    with path.open('rb') as f:mbr=f.read(512)
    parts=partitions(mbr,path.stat().st_size)
    first=min(p['start'] for p in parts)*512
    if first>256*MIB:raise ValueError('Unusually large boot gap; inspect donor manually')
    boot0=boot_header(path,BOOT0_OFFSET,'boot0',first)
    toc=boot_header(path,TOC_OFFSET,'toc1',first)
    if boot0['offset']+boot0['length']>toc['offset']:raise ValueError('Boot payload overlap')
    return dict(donor_bytes=path.stat().st_size,partitions=parts,boot_prefix_bytes=first,
                boot0=boot0,boot_package=toc)



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('inspect',))
    parser.add_argument('image')
    args=parser.parse_args()
    print(json.dumps(inspect(args.image),indent=2))

if __name__=='__main__':main()
