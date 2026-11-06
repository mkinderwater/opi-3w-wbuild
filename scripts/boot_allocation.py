#!/usr/bin/env python3
"""Allocate boot files densely after mkfs population, preserving payloads and links."""
import contextlib,json,os,shutil,stat,subprocess,tempfile
from pathlib import Path
from image_layout import regular,sha256,MIB
from boot_manifest import verify as verify_boot

def snapshot(root):
    boot=Path(root)/'boot'
    if boot.is_symlink() or not boot.is_dir():raise ValueError('Expected a real boot directory')
    entries={}
    for p in sorted(boot.rglob('*')):
        s=p.lstat();name=str(p.relative_to(root));e=dict(mode=stat.S_IMODE(s.st_mode),uid=s.st_uid,gid=s.st_gid)
        if p.is_symlink():e['link']=os.readlink(p)
        elif p.is_file():e.update(bytes=s.st_size,sha256=sha256(p))
        elif p.is_dir():e['directory']=True
        else:raise ValueError('Special file in boot directory')
        entries[name]=e
    return entries


def dense_boot(root):
    root=Path(root);before=snapshot(root);groups={};results={}
    for p in sorted((root/'boot').rglob('*')):
        if p.is_symlink() or not p.is_file():continue
        s=p.stat();groups.setdefault((s.st_dev,s.st_ino),[]).append(p)
    # Preserve hardlinks within /boot; refuse to sever unknown links outside it.
    for paths in groups.values():
        if paths[0].stat().st_nlink!=len(paths):raise ValueError('Boot file has hardlinks outside /boot')
    for paths in groups.values():
        source=paths[0];s=source.stat();name=str(source.relative_to(root))
        with source.open('rb') as incoming:
            fd,temp=tempfile.mkstemp(prefix='.opi-3w-wbuild-dense-',dir=source.parent)
            temp=Path(temp)
            try:
                with os.fdopen(fd,'wb') as target:
                    if s.st_size:os.posix_fallocate(target.fileno(),0,s.st_size)
                    while block:=incoming.read(MIB):target.write(block)
                    target.flush();os.fsync(target.fileno())
                    hole=os.lseek(target.fileno(),0,os.SEEK_HOLE) if s.st_size else 0
                    if hole!=s.st_size:raise ValueError('Boot file still contains a hole: '+name)
                shutil.copystat(source,temp,follow_symlinks=False)
                os.chown(temp,s.st_uid,s.st_gid);os.chmod(temp,stat.S_IMODE(s.st_mode))
                if sha256(temp)!=before[name]['sha256']:raise ValueError('Copied boot payload changed')
                os.replace(temp,source)
                for alias in paths[1:]:alias.unlink();os.link(source,alias)
                results[name]=dict(bytes=s.st_size,first_hole=hole,aliases=[str(p.relative_to(root)) for p in paths])
            finally:temp.unlink(missing_ok=True)
    if snapshot(root)!=before:raise ValueError('Boot data, links, ownership or modes changed')
    return results



def normalize_filesystem(rootfs,expected_boot):
    rootfs=regular(rootfs)
    # This is the newly created standalone filesystem, never a disk device.
    loop=subprocess.check_output(['losetup','--find','--show',str(rootfs)],text=True).strip()
    directory=Path(tempfile.mkdtemp(prefix='opi-3w-wbuild-boot-allocation-'))
    did_mount=False
    try:
        subprocess.run(['mount','-t','ext4','-o','rw',loop,str(directory)],check=True)
        did_mount=True
        verify_boot(directory,expected_boot)
        before=subprocess.check_output(['debugfs','-R','stat /boot/uImage',str(rootfs)],text=True,stderr=subprocess.STDOUT)
        files=dense_boot(directory)
        verify_boot(directory,expected_boot)
        result=dict(schema=1,boot_payloads_verified=True,all_regular_boot_files_dense=True,files=files,kernel_before=before)
        audit=directory/'usr/share/opi-3w-wbuild/boot-allocation.json'
        audit.parent.mkdir(parents=True,exist_ok=True)
        audit.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        try:
            if did_mount:subprocess.run(['umount',str(directory)],check=True)
        finally:
            subprocess.run(['losetup','-d',loop],check=True)
            try:directory.rmdir()
            except OSError:pass
    # Read the committed inode mapping after the filesystem is unmounted.
    result['kernel_after']=subprocess.check_output(['debugfs','-R','stat /boot/uImage',str(rootfs)],text=True,stderr=subprocess.STDOUT)
    rootfs.with_suffix('.boot-allocation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
