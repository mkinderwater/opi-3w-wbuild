#!/usr/bin/env python3
"""Fetch only pinned A733 VIPLite runtime/model assets; no full SDK clone."""
import argparse,hashlib,json,shutil,struct,urllib.request
from pathlib import Path
BASE=Path(__file__).resolve().parent

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def synthetic_seven():
    data=bytearray(784)
    for y in range(6,9):
        for x in range(6,22):data[y*28+x]=255
    for y in range(8,24):
        center=21-round((y-8)*12/16)
        for x in range(center-1,center+2):data[y*28+x]=255
    return bytes(data)

def fetch(url,expected):
    with urllib.request.urlopen(url,timeout=60) as response:data=response.read(expected['bytes']+1)
    if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:raise ValueError('Pinned asset hash/size mismatch: '+expected['source'])
    return data

def prepare(destination,download=fetch):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    pins=json.loads((BASE/'pins.json').read_text());golden=json.loads((BASE/'golden.json').read_text())
    for entry in pins['files']:
        url=pins['repository'].replace('https://github.com/','https://raw.githubusercontent.com/')+'/'+pins['commit']+'/'+entry['source']
        data=download(url,entry)
        if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('Asset mismatch')
        if entry['target'].startswith('lib/'):
            if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=183:raise ValueError('NPU library is not AArch64 ELF')
        target=destination/entry['target'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o644)
    (destination/'bin').mkdir()
    (destination/'model/synthetic-seven.u8').write_bytes(synthetic_seven())
    for case in golden['cases']:
        if digest(destination/'model'/(case['name']+'.u8'))!=case['input_sha256']:raise ValueError('Reference input mismatch')
    shutil.copyfile(BASE/'golden.json',destination/'golden.json')
    (destination/'manifest.json').write_text(json.dumps(dict(schema=1,kernel_abi=pins['kernel_abi'],expected_cid=pins['expected_cid'],sdk_commit=pins['commit'],hardware_validated=False,files={str(p.relative_to(destination)):digest(p) for p in destination.rglob('*') if p.is_file() and p.name!='manifest.json'}),indent=2)+'\n')

def seal(destination):
    destination=Path(destination);m=json.loads((destination/'manifest.json').read_text())
    probe=destination/'bin/npu-probe'
    header=probe.read_bytes()[:20]
    if header[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',header,18)[0]!=183:raise ValueError('Compiled NPU probe is not AArch64 ELF')
    m['files']['bin/npu-probe']=digest(probe)
    (destination/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','seal']);p.add_argument('destination');a=p.parse_args()
    (prepare if a.action=='prepare' else seal)(a.destination)
