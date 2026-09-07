"""Small, Python-version-independent helpers for Ollama tar archives."""

import os
import shutil
import tarfile
from pathlib import Path


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def consume_member(tar: tarfile.TarFile, member: tarfile.TarInfo) -> None:
    """Consume a skipped file in streaming mode so the next tar member is readable."""
    if not member.isfile() or member.size <= 0:
        return
    source = tar.extractfile(member)
    if source is not None:
        while source.read(1 << 16):
            pass


def extract_member(tar: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    """Extract one member without Python 3.12's ``filter`` argument."""
    root = destination.resolve()
    target = (destination / member.name).resolve()
    if not _inside(root, target):
        raise RuntimeError(f"unsafe archive path: {member.name}")

    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return

    if member.isfile():
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tar.extractfile(member)
        if source is None:
            raise RuntimeError(f"could not read archive member: {member.name}")
        with source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=1 << 20)
        os.chmod(target, member.mode & 0o777)
        return

    if member.issym():
        link_target = (target.parent / member.linkname).resolve()
        if not _inside(root, link_target):
            raise RuntimeError(f"unsafe archive link: {member.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(member.linkname)
        return

    raise RuntimeError(f"unsupported archive member: {member.name}")
