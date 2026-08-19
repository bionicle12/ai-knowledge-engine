"""Immutable release snapshots (spec §6.3).

A release is a materialized copy of one skill at one source commit:
``releases/<source-id>/<skill-path>/<commit12>-<hash12>/``. It is
created once via a temporary directory and an atomic rename, and never
edited afterwards — an existing release directory is always trusted
as-is and returned untouched.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .provenance import content_hash


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


def create_release(
    store_root: Path,
    source_id: str,
    skill_path: str,
    skill_dir: Path,
    commit: str,
) -> Path:
    digest = content_hash(skill_dir)
    dest = release_dir(store_root, source_id, skill_path, commit, digest)
    if dest.is_dir():
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.parent / (dest.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(skill_dir, staging, symlinks=True)
    staging.rename(dest)
    return dest
