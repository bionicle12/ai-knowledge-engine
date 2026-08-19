"""Canonical content hashing and provenance matching (spec §6.3, §9).

The hash of a skill artifact is the SHA-256 of a canonical manifest: one
``<relative-path>\\n<file-sha256>\\n`` entry per file, entries sorted
bytewise by path, paths using forward slashes, ``.git`` excluded. A
symlink contributes the SHA-256 of its literal target string instead of
file contents, so links hash identically on every platform without
following them.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_entries(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        base = Path(dirpath)
        symlink_dirs = [d for d in dirnames if (base / d).is_symlink()]
        for d in symlink_dirs:
            dirnames.remove(d)
            yield base / d
        for name in filenames:
            yield base / name


def content_hash(root: Path) -> str:
    root = Path(root)
    entries: list[tuple[str, str]] = []
    for path in _iter_entries(root):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            digest = hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
        else:
            digest = _file_digest(path)
        entries.append((rel, digest))
    entries.sort(key=lambda item: item[0].encode("utf-8"))
    manifest = "".join(f"{rel}\n{digest}\n" for rel, digest in entries)
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()
