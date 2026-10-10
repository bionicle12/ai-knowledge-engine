"""Immutable release snapshots (spec §5.3, §6.3).

A release is a materialized copy of one skill at one source commit:
``releases/<source-id>/<skill-path>/<commit12>-<hash12>/``. It is
created once via a temporary directory and an atomic rename, its files
and (on POSIX) its folders are made read-only, and it is never edited
afterwards. ``.git`` folders are never copied: they are outside the
content hash, and a single-skill source's checkout ``.git`` holds the
clone URL. Immutability is also verified, not assumed: an existing
release is reused only while its content still hashes to the digest in
its name, and a skill with symlinks resolving outside it never becomes
a release (spec §20).
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from .filesystem import remove_tree, unsafe_symlinks
from .provenance import content_hash

_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


class ReleaseError(Exception):
    """A release cannot be created or trusted."""


def release_dir(
    store_root: Path,
    source_id: str,
    skill_path: str,
    commit: str,
    digest: str,
) -> Path:
    return (
        Path(store_root)
        / "releases"
        / source_id
        / skill_path
        / f"{commit[:12]}-{digest[:12]}"
    )


def _make_read_only(root: Path) -> None:
    """Clear write bits on files and folders; links are never followed.

    Folders stay writable on Windows, where the read-only attribute does
    not stop adding or deleting their entries.
    """
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            mode = stat.S_IMODE(path.lstat().st_mode)
            os.chmod(path, mode & ~_WRITE_BITS)
    if os.name == "nt":
        return
    for dirpath, _dirnames, _filenames in os.walk(root, followlinks=False):
        mode = stat.S_IMODE(os.lstat(dirpath).st_mode)
        os.chmod(dirpath, mode & ~_WRITE_BITS)


def _ignore_git(dirpath: str, names: list[str]) -> set[str]:
    """Skip ``.git`` folders exactly as ``content_hash`` does."""
    return {n for n in names if n == ".git" and os.path.isdir(os.path.join(dirpath, n))}


def _has_git_dir(root: Path) -> bool:
    return any(".git" in dirnames for _, dirnames, _ in os.walk(root))


def create_release(
    store_root: Path,
    source_id: str,
    skill_path: str,
    skill_dir: Path,
    commit: str,
) -> Path:
    unsafe = unsafe_symlinks(skill_dir)
    if unsafe:
        raise ReleaseError(
            f"{skill_dir} contains symlinks resolving outside the skill: "
            + ", ".join(unsafe)
        )
    digest = content_hash(skill_dir)
    dest = release_dir(store_root, source_id, skill_path, commit, digest)
    if dest.is_dir():
        if content_hash(dest) != digest or _has_git_dir(dest):
            raise ReleaseError(
                f"release {dest} was modified after it was created; make it "
                "writable (chmod -R u+w), move it aside for inspection, then "
                "run reconcile again to recreate it"
            )
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.parent / (dest.name + ".tmp")
    if staging.exists():
        remove_tree(staging)
    shutil.copytree(skill_dir, staging, symlinks=True, ignore=_ignore_git)
    _make_read_only(staging)
    staging.rename(dest)  # same parent: allowed for a read-only folder
    return dest
