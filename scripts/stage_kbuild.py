#!/usr/bin/env python3
"""Materialize C-source links before invoking Linux Kbuild with the vendor DDK."""
import argparse
import os
from pathlib import Path
import re
import shutil

TARGET='kbuild: kbuild_check $(TARGET_PRIMARY_OUT)/kbuild/Makefile bridges\n'
HOOK='\t@python3 "$(TOP)/opi-3w-wbuild-stage-kbuild.py" "$(TOP)" "$(abspath $(TARGET_PRIMARY_OUT)/kbuild)" "$(abspath $(BRIDGE_SOURCE_ROOT))" "$(PVR_ARCH)" "$(KERNELDIR)"\n'


def patch(source):
    source=Path(source)
    rule=source/'build/linux/kbuild/kbuild.mk'
    text=rule.read_text()
    if text.count(TARGET)!=1:raise ValueError('Pinned PowerVR Kbuild entry changed; refusing an uncertain patch')
    if HOOK not in text:
        rule.write_text(text.replace(TARGET,TARGET+HOOK))
    for name in ('kbuild/Makefile.template','toplevel.mk','defs.mk'):
        p=source/'build/linux'/name
        p.write_text(re.sub(r'^[ \t]*\.SECONDARY[ \t]*:[^\n]*(?:\n|$)','',p.read_text(),flags=re.M))
    shutil.copyfile(__file__,source/'opi-3w-wbuild-stage-kbuild.py')


def stage(source,output,bridges,architecture,kernel):
    source=Path(source).resolve(strict=True)
    output=Path(output).resolve()
    bridges=Path(bridges).resolve(strict=True)
    kernel=Path(kernel).resolve(strict=True)
    if not output.is_relative_to(source):raise ValueError('Kbuild output must be inside its private source tree')
    if not re.fullmatch('[A-Za-z0-9_-]+',architecture):raise ValueError('Invalid PVR architecture')
    output.mkdir(parents=True,exist_ok=True)
    count=0
    def link_tree(origin,destination,exclude_outputs=False):
        nonlocal count
        for directory,dirs,files in os.walk(origin,followlinks=False):
            relative=Path(directory).relative_to(origin)
            if exclude_outputs:
                dirs[:]=[name for name in dirs if not name.startswith('binary_') and name!='.git']
            for name in files:
                if not name.endswith('.c'):continue
                candidate=Path(directory)/name
                physical=candidate.resolve(strict=True)
                if not physical.is_relative_to(origin):raise ValueError('C source link leaves its source tree: '+str(candidate))
                if not physical.is_file():raise ValueError('Expected a regular C source: '+str(candidate))
                target=destination/relative/name
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.is_symlink():
                    if target.resolve()==physical:continue
                    target.unlink()
                elif target.exists():
                    raise ValueError('Refusing to overwrite a generated regular file: '+str(target))
                target.symlink_to(os.path.relpath(physical,target.parent))
                count+=1
    # Run after the vendor 'bridges' prerequisite, so generated bridges exist.
    link_tree(source,output,exclude_outputs=True)
    link_tree(bridges,output/'generated'/architecture)
    link_tree(kernel,output/'external')
    required=output/'services/server/env/linux/dkf_server.c'
    if not required.is_file():raise ValueError('Required dkf_server.c was not staged')
    return count


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('patch');p.add_argument('source')
    p=sub.add_parser('stage')
    for name in ('source','output','bridges','architecture','kernel'):p.add_argument(name)
    args=parser.parse_args()
    if args.command=='patch':patch(args.source)
    else:print('Staged PowerVR C-source links:',stage(args.source,args.output,args.bridges,args.architecture,args.kernel))

if __name__=='__main__':
    # The make hook uses positional paths to keep its generated command short.
    import sys
    if len(sys.argv)>1 and sys.argv[1] not in ('patch','stage','-h','--help'):
        sys.argv.insert(1,'stage')
    main()
