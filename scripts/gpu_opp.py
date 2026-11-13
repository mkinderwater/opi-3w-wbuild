#!/usr/bin/env python3
"""Apply and audit the image's GPU 1008 MHz / 960 mV operating point."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from boot_manifest import verify
from donor_files import Donor

GPU='/soc@3000000/gpu@1800000'
REG='/soc@3000000/twi@7083000/pmu@36/regulators@0/dcdc4'
OPP='/soc@3000000/gpu-opp-table'
CHANGES={(GPU,'clk_rate'):1008000000,(REG,'regulator-min-microvolt'):960000,(REG,'regulator-max-microvolt'):960000}


def tree(blob):
    """Compare every property, node and memory reservation, independent of packing."""
    if len(blob)<40:raise ValueError('Truncated DTB')
    h=struct.unpack('>10I',blob[:40])
    if h[0]!=0xd00dfeed or h[1]>len(blob):raise ValueError('Invalid DTB')
    end=h[1];p=h[2];strings=h[3];stack=[];properties={};nodes=set()
    def read(offset,count):
        if offset<0 or offset+count>end:raise ValueError('DTB range outside file')
        return blob[offset:offset+count]
    def word(offset):return int.from_bytes(read(offset,4),'big')
    def cstring(offset):
        stop=blob.find(b'\0',offset,end)
        if stop<0:raise ValueError('Unterminated DTB string')
        return read(offset,stop-offset).decode(),stop+1
    while True:
        token=word(p);p+=4
        if token==1:
            name,p=cstring(p);stack.append(name);p=(p+3)&~3
            nodes.add('/'+'/'.join(stack[1:]))
        elif token==2:
            if not stack:raise ValueError('Invalid DTB nesting')
            stack.pop()
        elif token==3:
            size=word(p);nameoff=word(p+4);p+=8
            name,_=cstring(strings+nameoff);key=('/'+'/'.join(stack[1:]),name)
            if key in properties:raise ValueError('Duplicate DTB property')
            properties[key]=read(p,size);p=(p+size+3)&~3
        elif token==4:pass
        elif token==9:
            if stack:raise ValueError('Unclosed DTB node')
            break
        else:raise ValueError('Invalid DTB token')
    p=h[4];reservations=[]
    while True:
        pair=struct.unpack('>QQ',read(p,16));p+=16
        if pair==(0,0):break
        reservations.append(pair)
    return properties,nodes,reservations


def number(properties,node,name):
    value=properties[(node,name)]
    if len(value)!=4:raise ValueError('Expected one DT cell: '+node+'/'+name)
    return int.from_bytes(value,'big')


def check_change(before,after):
    old,nodes,reservations=tree(before);new,newnodes,newreservations=tree(after)
    wanted=dict(old)
    wanted.update({key:struct.pack('>I',value) for key,value in CHANGES.items()})
    if new!=wanted or nodes!=newnodes or reservations!=newreservations:
        raise ValueError('GPU configuration changed unrelated device-tree content')


def apply(root,vendor_boot,profile):
    root=Path(root);verify(root,vendor_boot)
    selected=Donor(root).resolve('boot/dtb/'+profile['dtb'])
    logical=selected.relative_to(root.resolve()).as_posix()
    before=selected.read_bytes();old_hash=hashlib.sha256(before).hexdigest()
    if old_hash!=profile['dtb_sha256'] or vendor_boot.get(logical)!={'sha256':old_hash}:
        raise ValueError('Selected DTB does not match donor provenance')
    properties,_,_=tree(before)
    if properties[(GPU,'compatible')]!=b'img,gpu\0' or properties[(REG,'regulator-name')]!=b'axp8191-dcdc4\0':
        raise ValueError('GPU or GPU regulator identity differs')
    if number(properties,GPU,'gpu-supply')!=number(properties,REG,'phandle'):
        raise ValueError('GPU supply does not point to dcdc4')
    if number(properties,GPU,'operating-points-v2')!=number(properties,OPP,'phandle'):
        raise ValueError('Unexpected GPU operating-point table')
    supply=properties[(REG,'phandle')]
    virtual='/soc@3000000/twi@7083000/pmu@36/virtual-dcdc4'
    for (node,name),value in properties.items():
        if name.endswith('-supply') and value==supply and (node,name)!=(GPU,'gpu-supply'):
            if node!=virtual or name!='dcdc4-supply' or properties.get((node,'compatible'))!=b'xpower-vregulator,dcdc4\0':
                raise ValueError('GPU regulator has an unexpected consumer')
    top=OPP+'/opp@1008000000'
    if properties[(top,'opp-hz')]!=struct.pack('>Q',1008000000) or number(properties,top,'opp-microvolt')!=960000 or number(properties,top,'opp-microvolt-vfdefault')!=960000:
        raise ValueError('Donor lacks the expected 1008 MHz / 960 mV GPU point')
    if not number(properties,REG,'regulator-min-microvolt')<=960000<=number(properties,REG,'regulator-max-microvolt'):
        raise ValueError('960 mV is outside donor regulator constraints')
    data=root/'usr/share/opi-3w-wbuild';data.mkdir(parents=True,exist_ok=True)
    original=data/'gpu-opp-original.dtb'
    if original.exists():raise ValueError('GPU image configuration already applied')
    with tempfile.NamedTemporaryFile(dir=selected.parent,prefix='.gpu-opp-',delete=False) as f:
        temporary=Path(f.name);f.write(before)
    try:
        for (node,name),value in CHANGES.items():
            subprocess.run(['fdtput','-t','u',str(temporary),node,name,str(value)],check=True)
        after=temporary.read_bytes();check_change(before,after)
        new_hash=hashlib.sha256(after).hexdigest()
        configured=dict(vendor_boot);configured[logical]={'sha256':new_hash}
        original.write_bytes(before)
        shutil.copystat(selected,temporary);os.replace(temporary,selected)
        verify(root,configured)
        updated=dict(profile,dtb_sha256=new_hash,vendor_dtb_sha256=old_hash)
        metadata={'frequency_hz':1008000000,'voltage_uv':960000,'gpu_path':GPU,'regulator_path':REG,
                  'dtb_path':logical,'vendor_dtb_sha256':old_hash,'configured_dtb_sha256':new_hash,
                  'changes': [{'node':node,'property':name,'value':value} for (node,name),value in CHANGES.items()]}
        for name,value in [('configured-boot.json',configured),('board-profile.json',updated),('gpu-opp.json',metadata)]:
            (data/name).write_text(json.dumps(value,indent=2)+'\n')
        return configured
    finally:temporary.unlink(missing_ok=True)


def authorized_boot(root,vendor_boot):
    """Recheck the only permitted donor-to-image boot delta before assembly."""
    root=Path(root);data=root/'usr/share/opi-3w-wbuild'
    metadata=json.loads((data/'gpu-opp.json').read_text())
    original=(data/'gpu-opp-original.dtb').read_bytes()
    selected=Donor(root).resolve(metadata['dtb_path'])
    if selected.relative_to(root.resolve()).as_posix()!=metadata['dtb_path']:
        raise ValueError('GPU DTB path must be canonical within image root')
    old_hash=hashlib.sha256(original).hexdigest()
    if vendor_boot.get(metadata['dtb_path'])!={'sha256':old_hash}:raise ValueError('Original GPU DTB does not match donor')
    check_change(original,selected.read_bytes())
    wanted=dict(vendor_boot);wanted[metadata['dtb_path']]={'sha256':hashlib.sha256(selected.read_bytes()).hexdigest()}
    configured=json.loads((data/'configured-boot.json').read_text())
    if configured!=wanted:raise ValueError('Unexpected configured boot-manifest delta')
    verify(root,wanted);return wanted


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');p.add_argument('vendor_manifest');p.add_argument('profile')
    a=p.parse_args();apply(a.root,json.loads(Path(a.vendor_manifest).read_text()),json.loads(Path(a.profile).read_text()))
