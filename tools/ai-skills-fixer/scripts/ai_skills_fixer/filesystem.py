"""Cross-platform managed-directory installation primitives."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


class FilesystemError(Exception):
    """A requested managed-directory operation could not be completed."""


def is_junction(path: Path) -> bool:
    """Return whether *path* is a Windows directory junction."""
    if os.name != "nt":
        return False
    try:
        tag = Path(path).lstat().st_reparse_tag
    except (AttributeError, OSError):
        return False
    return tag == stat.IO_REPARSE_TAG_MOUNT_POINT


def managed_link_type(path: Path) -> str | None:
    """Return ``symlink``/``junction`` for a managed directory link."""
    path = Path(path)
    if path.is_symlink():
        return "symlink"
    if is_junction(path):
        return "junction"
    return None


def default_install_strategy() -> str:
    """Select the privilege-free managed-link strategy for this platform."""
    return "junction" if os.name == "nt" else "symlink"


def _create_junction(target: Path, dest: Path) -> None:
    if os.name != "nt":
        raise FilesystemError("directory junctions are supported only on Windows")
    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(dest), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise FilesystemError(
            f"cannot execute cmd.exe to create junction: {exc}"
        ) from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise FilesystemError(f"cannot create junction {dest} -> {target}: {detail}")


def materialize_directory(source: Path, dest: Path, strategy: str) -> None:
    """Expose *source* at *dest* using an approved plan strategy."""
    source = Path(source).resolve()
    dest = Path(dest).absolute()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if strategy == "symlink":
        dest.symlink_to(source, target_is_directory=True)
    elif strategy == "junction":
        _create_junction(source, dest)
    elif strategy == "copy":
        shutil.copytree(source, dest, symlinks=True)
    else:
        raise FilesystemError(f"unsupported installation strategy {strategy!r}")


def remove_managed_link(path: Path) -> None:
    """Remove a symlink or junction without touching its target directory."""
    path = Path(path)
    kind = managed_link_type(path)
    if kind == "symlink":
        path.unlink()
    elif kind == "junction":
        path.rmdir()
    else:
        raise FilesystemError(f"{path} is not a managed directory link")


def remove_tree(path: Path) -> None:
    """Remove a directory tree, clearing Windows read-only bits if required."""

    def retry_read_only(function, name, _error) -> None:
        os.chmod(name, stat.S_IWRITE)
        function(name)

    shutil.rmtree(Path(path), onerror=retry_read_only)
