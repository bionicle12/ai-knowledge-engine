"""Undo helpers and rollback of applied operations (spec §18, §19).

``undo_operation`` reverses exactly one applied operation and refuses
to delete anything it cannot prove the tool created; ``rollback_apply``
replays an apply record in reverse. Both never touch content that
drifted after the apply — that is reported for manual recovery instead.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .provenance import content_hash
from .store import store_lock


class RollbackError(Exception):
    pass


def _remove_managed(dest: Path, op_result: dict) -> None:
    if dest.is_symlink():
        dest.unlink()
        return
    if dest.is_dir():
        expected = op_result.get("release_hash")
        if expected and content_hash(dest) != expected:
            raise RollbackError(
                f"{dest} was modified after apply; refusing to delete it"
            )
        shutil.rmtree(dest)


def undo_operation(store_root: Path, op_result: dict) -> None:
    op_type = op_result["type"]
    dest = Path(op_result["destination"])
    backup_rel = op_result.get("backup_path")
    backup = Path(store_root) / backup_rel if backup_rel else None

    if op_type == "install":
        _remove_managed(dest, op_result)
    elif op_type == "adopt":
        if backup is None or not backup.is_dir():
            raise RollbackError(
                f"backup missing for adopt of {dest}; manual recovery required"
            )
        _remove_managed(dest, op_result)
        shutil.move(str(backup), str(dest))
    elif op_type == "update":
        previous = op_result.get("previous_target")
        if not previous:
            raise RollbackError(
                f"no previous link target recorded for update of {dest}"
            )
        if dest.is_symlink():
            dest.unlink()
        elif dest.exists():
            raise RollbackError(
                f"{dest} is no longer a managed link; refusing to replace it"
            )
        dest.symlink_to(previous)
    elif op_type == "quarantine":
        if backup is None or not backup.is_dir():
            raise RollbackError(
                f"backup missing for quarantine of {dest}; manual recovery required"
            )
        if dest.exists() or dest.is_symlink():
            raise RollbackError(
                f"{dest} reappeared after quarantine; refusing to overwrite"
            )
        shutil.move(str(backup), str(dest))


def rollback_apply(store_root: Path, apply_id: str) -> dict:
    store_root = Path(store_root)
    record_path = store_root / "state" / "plans" / f"{apply_id}.json"
    if not record_path.is_file():
        raise RollbackError(f"unknown apply id {apply_id!r}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("rolled_back_at"):
        raise RollbackError(f"apply {apply_id!r} is already rolled back")

    with store_lock(store_root):
        for op_result in reversed(record["operations"]):
            if op_result["status"] == "applied":
                undo_operation(store_root, op_result)
                op_result["status"] = "rolled-back"
        record["rolled_back_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return record
