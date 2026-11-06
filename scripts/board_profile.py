#!/usr/bin/env python3
"""Record the exact vendor Zero 3W DTB, including its known misleading label."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from donor_files import Donor

DTB='allwinner/sun60i-a733-orangepi-zero3w.dtb'


def record(root):
    donor=Donor(root)
    fields=dict(line.split('=',1) for line in donor.resolve('boot/orangepiEnv.txt').read_text().splitlines()
                if '=' in line and not line.lstrip().startswith('#'))
    if fields.get('fdtfile','').strip()!=DTB:
        raise ValueError('Donor must explicitly select the Zero 3W DTB in orangepiEnv.txt')
    dtb=donor.resolve('boot/dtb/'+DTB)
    model=subprocess.check_output(['fdtget',str(dtb),'/','model'],text=True).strip()
    compatible=subprocess.check_output(['fdtget',str(dtb),'/','compatible'],text=True).split()
    if not any('sun60i' in value or 'a733' in value for value in compatible):
        raise ValueError('Selected Zero 3W DTB is not an A733 vendor profile')
    return dict(board='Orange Pi Zero 3W',dtb=DTB,model=model,compatible=compatible,
                dtb_sha256=hashlib.sha256(dtb.read_bytes()).hexdigest())


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root');p.add_argument('output')
    a=p.parse_args();Path(a.output).write_text(json.dumps(record(a.root),indent=2)+'\n')
