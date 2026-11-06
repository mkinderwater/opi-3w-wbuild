#!/usr/bin/env python3
"""Prepare private extracted vendor headers, replacing package post-install tool builds."""
import argparse
import hashlib
import os
from pathlib import Path
import struct
import subprocess


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean_tools(headers):
    headers=Path(headers)
    removed=[]
    # Match the vendor post-install cleanup of prebuilt object files.
    for path in headers.rglob('*.o'):
        if path.is_file() or path.is_symlink():
            path.unlink();removed.append(str(path.relative_to(headers)))
    scripts=headers/'scripts'
    # Header packages can carry x86 build-host executables. In an ARM64 chroot
    # their missing ELF interpreter can be reported as "not found".
    for directory,dirs,files in os.walk(scripts,followlinks=False):
        for name in files:
            path=Path(directory)/name
            if path.is_symlink():
                if name in ('fixdep','modpost','mk_elfconfig','conf','genksyms'):
                    path.unlink();removed.append(str(path.relative_to(headers)))
                continue
            with path.open('rb') as stream:magic=stream.read(4)
            if magic==b'\x7fELF':
                path.unlink();removed.append(str(path.relative_to(headers)))
    return removed


def check_tool(path,machine=183):
    path=Path(path)
    with path.open('rb') as stream:header=stream.read(20)
    if len(header)!=20 or header[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',header,18)[0]!=machine:
        raise ValueError('Kernel build helper has wrong ELF architecture: '+str(path))
    if not os.access(path,os.X_OK):raise ValueError('Kernel build helper is not executable: '+str(path))


def prepare(headers,abi,machine=183):
    headers=Path(headers).resolve(strict=True)
    release=headers/'include/config/kernel.release'
    symvers=headers/'Module.symvers'
    if release.read_text().strip()!=abi:raise ValueError('Header kernel.release does not match '+abi)
    original_symvers=digest(symvers)
    removed=clean_tools(headers)
    print('Preparing vendor kernel headers; removed prebuilt files:',len(removed),flush=True)
    # The pinned vendor package's postinst does oldconfig, scripts and M=scripts/mod/.
    # olddefconfig supplies defaults without an interactive yes pipeline.
    common=['make','-C',str(headers),'ARCH=arm64','HOSTCC=gcc','HOSTCXX=g++','CC=gcc']
    for target in (['olddefconfig'],['-j2','scripts'],['-j2','M=scripts/mod/']):
        subprocess.run(common+target,check=True)
    if release.read_text().strip()!=abi:raise ValueError('Header preparation changed kernel.release')
    if digest(symvers)!=original_symvers:raise ValueError('Header preparation changed donor Module.symvers')
    for relative in ('scripts/basic/fixdep','scripts/mod/modpost'):
        tool=headers/relative
        check_tool(tool,machine)
        try:
            result=subprocess.run([str(tool),'--help'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=10,cwd=headers)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise ValueError('Kernel helper cannot run: '+relative+': '+str(error)) from error
        # These Linux helpers may reject --help with usage; that is valid execution.
        if result.returncode not in (0,1):raise ValueError('Kernel helper failed to start: '+relative+': '+result.stdout)
    print('ARM64 fixdep and modpost prepared and executable',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('headers');parser.add_argument('abi')
    args=parser.parse_args()
    prepare(args.headers,args.abi)
