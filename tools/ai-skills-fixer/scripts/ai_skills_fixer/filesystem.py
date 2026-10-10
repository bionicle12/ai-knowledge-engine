"""Cross-platform managed-directory installation primitives."""
from __future__ import annotations

import os
import re
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
        # Releases have read-only folders; a host copy must stay movable
        # (quarantine, rollback), so its folders get their write bit back.
        for dirpath, _dirnames, _filenames in os.walk(dest, followlinks=False):
            _add_write_bit(dirpath)
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


_MAX_LINK_HOPS = 40  # the Linux per-lookup limit; loops count as unsafe


def _link_parts(target: str) -> list[str]:
    separators = r"[\\/]" if os.name == "nt" else "/"
    return [part for part in re.split(separators, target) if part]


def _resolves_beneath(root: str, rel: str) -> bool:
    """Resolve *rel* like the OS would, with *root* acting as ``/``.

    Every component is looked up in the real tree and links are expanded
    as they are met, so ``..`` after a link climbs from where that link
    really points. Resolution fails (returns False) as soon as it would
    step above *root*, meets an absolute target or a junction, or needs
    more than ``_MAX_LINK_HOPS`` links. Because nothing above *root* is
    ever consulted, the verdict holds wherever the tree is copied.
    """
    pending = list(reversed(_link_parts(rel)))
    resolved: list[str] = []
    hops = 0
    while pending:
        part = pending.pop()
        if part == ".":
            continue
        if part == "..":
            if not resolved:
                return False
            resolved.pop()
            continue
        candidate = os.path.join(root, *resolved, part)
        if is_junction(Path(candidate)):
            return False
        if not os.path.islink(candidate):
            resolved.append(part)
            continue
        hops += 1
        target = os.readlink(candidate)
        if hops > _MAX_LINK_HOPS or os.path.isabs(target) or Path(target).drive:
            return False
        pending.extend(reversed(_link_parts(target)))
    return True


def unsafe_symlinks(root: Path) -> list[str]:
    """List links under *root* that resolve outside it, as ``rel -> target``.

    A skill is supply-chain content: a link such as ``reference.md ->
    ~/.ssh/id_ed25519`` would expose a local file to the agent once the
    skill is installed. Each link is resolved component by component
    (see ``_resolves_beneath``), so chains that only escape once another
    link is followed (``x -> .``, ``up -> x/..``) are caught as well as
    absolute targets and plain ``..`` escapes. ``.git`` directories are
    skipped: they never become part of a release.
    """
    root = Path(root)
    base_dir = str(root)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        base = Path(dirpath)
        for name in [*dirnames, *filenames]:
            path = base / name
            rel = path.relative_to(root).as_posix()
            if is_junction(path):
                found.append(f"{rel} -> {os.readlink(path)} (junction)")
            elif path.is_symlink() and not _resolves_beneath(base_dir, rel):
                found.append(f"{rel} -> {os.readlink(path)}")
    return sorted(found)


def _add_write_bit(path: str) -> None:
    os.chmod(path, stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IWRITE)


def remove_tree(path: Path) -> None:
    """Remove a directory tree, even one with read-only files or folders.

    On a failure the entry and its parent folder get their write bit back
    and the step is retried; links are never followed, so nothing outside
    the tree changes mode.
    """

    def retry_writable(function, name, _error) -> None:
        for target in (os.path.dirname(name), name):
            if not os.path.islink(target):
                _add_write_bit(target)
        function(name)

    shutil.rmtree(Path(path), onerror=retry_writable)
