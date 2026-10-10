"""Undo helpers and rollback of applied operations (spec §18, §19).

``undo_started_operation`` reverses one operation — finished or cut off
half-way — using the intent fields the apply journal recorded before
each effect, and refuses to delete anything it cannot prove the tool
created. ``rollback_apply`` replays an apply record in reverse and saves
its progress after every undo, so a rollback stopped by content that
drifted after the apply can be re-run once that is resolved; drifted
content itself is never touched, only reported for manual recovery.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .filesystem import (
    FilesystemError,
    managed_link_type,
    materialize_directory,
    remove_managed_link,
    remove_tree,
)
from .provenance import content_hash
from .store import store_lock, write_json_atomic

APPLY_ID_RE = re.compile(r"^plan-[0-9a-f]{12}\.apply-\d{8}T\d{6}Z(-\d+)?$")
# Statuses whose effects may still be on disk: finished, interrupted, or
# left over by an earlier undo that could not complete.
UNDOABLE_STATUSES = ("applied", "in-progress", "needs-recovery")


class RollbackError(Exception):
    pass


def _remove_managed(dest: Path, op_result: dict) -> None:
    if managed_link_type(dest) is not None:
        try:
            remove_managed_link(dest)
        except FilesystemError as exc:
            raise RollbackError(str(exc)) from exc
        return
    if dest.is_dir():
        expected = op_result.get("release_hash")
        if not expected or content_hash(dest) != expected:
            raise RollbackError(
                f"{dest} was modified after apply; refusing to delete it"
            )
        remove_tree(dest)


def undo_operation(store_root: Path, op_result: dict) -> None:
    """Reverse one fully applied operation."""
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
        if managed_link_type(dest) is not None:
            try:
                remove_managed_link(dest)
            except FilesystemError as exc:
                raise RollbackError(str(exc)) from exc
        elif dest.exists():
            raise RollbackError(
                f"{dest} is no longer a managed link; refusing to replace it"
            )
        strategy = op_result.get("previous_strategy") or op_result.get("strategy")
        try:
            materialize_directory(Path(previous), dest, strategy)
        except (FilesystemError, OSError) as exc:
            raise RollbackError(str(exc)) from exc
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


def undo_started_operation(store_root: Path, op_result: dict) -> None:
    """Reverse whatever a started operation changed, finished or not.

    The apply journal records an operation's intent before each effect:
    ``release_hash`` before anything is materialized, ``backup_path``
    before content moves, ``previous_target`` before the old link goes.
    An intent without its effect (the move never happened) needs no undo.
    """
    op_type = op_result["type"]
    dest = Path(op_result["destination"])
    if op_type == "install" and not op_result.get("release_hash"):
        return  # failed before creating anything, e.g. destination existed
    if op_type == "update" and not op_result.get("previous_target"):
        return  # the previous link was never touched
    if op_type in ("adopt", "quarantine"):
        backup_rel = op_result.get("backup_path")
        if not backup_rel:
            return
        backup = Path(store_root) / backup_rel
        moved = backup.exists() or backup.is_symlink()
        untouched = (dest.exists() or dest.is_symlink()) and (
            op_type == "quarantine" or managed_link_type(dest) is None
        )
        if not moved and untouched:
            return  # the move to the backup never happened
    if op_type in ("install", "adopt", "update", "quarantine"):
        undo_operation(store_root, op_result)


def rollback_apply(store_root: Path, apply_id: str) -> dict:
    store_root = Path(store_root)
    if not APPLY_ID_RE.match(apply_id or ""):
        raise RollbackError(f"unknown apply id {apply_id!r}")
    record_path = store_root / "state" / "plans" / f"{apply_id}.json"
    if not record_path.is_file():
        raise RollbackError(f"unknown apply id {apply_id!r}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("rolled_back_at"):
        raise RollbackError(f"apply {apply_id!r} is already rolled back")

    with store_lock(store_root):
        for op_result in reversed(record["operations"]):
            if op_result["status"] not in UNDOABLE_STATUSES:
                continue
            try:
                undo_started_operation(store_root, op_result)
            except Exception as exc:  # noqa: BLE001 — saved, then re-raised
                op_result["status"] = "needs-recovery"
                op_result["recovery"] = str(exc)
                record["rollback_error"] = str(exc)
                write_json_atomic(record_path, record)
                raise RollbackError(
                    f"{exc}; progress is saved — resolve it, then run "
                    f"rollback {apply_id} again"
                ) from exc
            op_result["status"] = "rolled-back"
            op_result.pop("recovery", None)
            write_json_atomic(record_path, record)
        record.pop("rollback_error", None)
        record["rolled_back_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        write_json_atomic(record_path, record)
    return record
