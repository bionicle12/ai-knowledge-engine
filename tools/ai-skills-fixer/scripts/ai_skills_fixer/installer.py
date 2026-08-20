"""Plan application with drift protection (spec §17, §18, §19).

Applying requires an immutable saved plan ID. Before any operation the
tool verifies that configuration hashes and source commits still match
the plan; every operation re-checks its own precondition at execution
time. Any drift aborts the apply, rolls back already completed
operations, and surfaces as DriftError (exit code 3).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import gitops
from .planner import ValidationError, _skill_suffix
from .provenance import content_hash
from .releases import create_release
from .rollback import undo_operation
from .sources import source_checkout
from .store import LockError, store_lock

__all__ = ["DriftError", "LockError", "apply_plan"]


class DriftError(Exception):
    """The world no longer matches the approved plan."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_plan(store_root: Path, plan_id: str) -> dict:
    path = Path(store_root) / "state" / "plans" / f"{plan_id}.json"
    if not path.is_file():
        raise ValidationError(f"unknown plan {plan_id!r}; run reconcile first")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_config_drift(store_root: Path, plan: dict) -> None:
    current = {
        "registry": _sha256_file(store_root / "registry" / "repositories.yml"),
        "profile": _sha256_file(store_root / "profiles" / "default.yml"),
        "machine": _sha256_file(
            store_root / "machines" / f"{plan['machine']}.local.yml"
        ),
    }
    for key, digest in plan["config_hashes"].items():
        if current.get(key) != digest:
            raise DriftError(
                f"{key} configuration changed since the plan was created; "
                "run reconcile again"
            )


def _check_source_drift(store_root: Path, plan: dict) -> None:
    for source_id, commit in sorted(plan["sources"].items()):
        checkout = source_checkout(store_root, source_id)
        if not checkout.is_dir():
            raise DriftError(f"source checkout {source_id!r} is missing")
        if gitops.is_dirty(checkout):
            raise DriftError(f"source checkout {source_id!r} is dirty")
        if gitops.current_commit(checkout) != commit:
            raise DriftError(
                f"source {source_id!r} moved off the planned commit; "
                "run reconcile again"
            )


def _ensure_release(store_root: Path, lock_entry: dict) -> tuple[Path, str]:
    checkout = source_checkout(store_root, lock_entry["source_id"])
    skill_dir = checkout / lock_entry["skill_path"]
    if content_hash(skill_dir) != lock_entry["content_hash"]:
        raise DriftError(
            f"source content for {lock_entry['skill_id']!r} no longer matches "
            "the planned hash"
        )
    release = create_release(
        store_root,
        lock_entry["source_id"],
        _skill_suffix(lock_entry["skill_id"]),
        skill_dir,
        lock_entry["resolved_commit"],
    )
    if str(release.relative_to(store_root)) != lock_entry["release"]:
        raise DriftError(
            f"release path for {lock_entry['skill_id']!r} does not match the plan"
        )
    return release, lock_entry["content_hash"]


def _materialize(release: Path, dest: Path, strategy: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if strategy == "symlink":
        dest.symlink_to(release, target_is_directory=True)
    elif strategy == "copy":
        shutil.copytree(release, dest, symlinks=True)
    else:
        raise DriftError(f"unsupported installation strategy {strategy!r}")


def _validate_installed(dest: Path, digest: str) -> None:
    if not (dest / "SKILL.md").is_file() or content_hash(dest) != digest:
        raise DriftError(f"post-install validation failed at {dest}")


def _backup_dest(store_root: Path, apply_id: str, op: dict, dest: Path) -> str:
    backup_rel = f"state/backups/{apply_id}/{op['host']}/{dest.name}"
    backup = Path(store_root) / backup_rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dest), str(backup))
    return backup_rel


def _apply_op(
    store_root: Path, op: dict, lock_by_id: dict, apply_id: str
) -> dict:
    result = {
        "type": op["type"],
        "skill_id": op["skill_id"],
        "host": op["host"],
        "destination": op["destination"],
        "strategy": op.get("strategy"),
        "backup_path": None,
        "release_hash": None,
        "previous_target": None,
        "status": None,
    }
    dest = Path(op["destination"])
    op_type = op["type"]

    if op_type == "noop":
        result["status"] = "noop"
    elif op_type == "review":
        result["status"] = "skipped-manual-review"
    elif op_type == "install":
        if dest.exists() or dest.is_symlink():
            raise DriftError(f"{dest} exists but the plan expected it absent")
        release, digest = _ensure_release(store_root, lock_by_id[op["skill_id"]])
        _materialize(release, dest, op["strategy"])
        _validate_installed(dest, digest)
        result.update(status="applied", release_hash=digest)
    elif op_type == "adopt":
        expected = op["precondition"]["content_hash"]
        if not dest.is_dir() or content_hash(dest) != expected:
            raise DriftError(
                f"{dest} no longer matches the planned content hash"
            )
        release, digest = _ensure_release(store_root, lock_by_id[op["skill_id"]])
        backup_rel = _backup_dest(store_root, apply_id, op, dest)
        result["backup_path"] = backup_rel
        _materialize(release, dest, op["strategy"])
        _validate_installed(dest, digest)
        result.update(status="applied", release_hash=digest)
    elif op_type == "update":
        expected_target = op["precondition"]["target"]
        if not dest.is_symlink() or str(dest.resolve()) != str(
            Path(expected_target).resolve()
        ):
            raise DriftError(
                f"{dest} is no longer the managed link the plan expected"
            )
        release, digest = _ensure_release(store_root, lock_by_id[op["skill_id"]])
        dest.unlink()
        _materialize(release, dest, op["strategy"])
        _validate_installed(dest, digest)
        result.update(
            status="applied", release_hash=digest, previous_target=expected_target
        )
    elif op_type == "quarantine":
        expected = op["precondition"]["content_hash"]
        if not dest.is_dir() or content_hash(dest) != expected:
            raise DriftError(
                f"{dest} no longer matches the planned content hash"
            )
        result["backup_path"] = _backup_dest(store_root, apply_id, op, dest)
        result["status"] = "applied"
    else:
        raise DriftError(f"unknown operation type {op_type!r}")
    return result


def apply_plan(store_root: Path, plan_id: str) -> dict:
    store_root = Path(store_root)
    plan = _load_plan(store_root, plan_id)

    with store_lock(store_root):
        _check_config_drift(store_root, plan)
        _check_source_drift(store_root, plan)

        lock_by_id = {
            entry["skill_id"]: entry
            for entry in plan["lock_proposal"]["skills"]
        }
        started = datetime.now(timezone.utc)
        apply_id = f"{plan_id}.apply-{started.strftime('%Y%m%dT%H%M%SZ')}"
        record_path = store_root / "state" / "plans" / f"{apply_id}.json"

        results: list[dict] = []
        error: str | None = None
        try:
            for op in plan["operations"]:
                results.append(_apply_op(store_root, op, lock_by_id, apply_id))
        except DriftError as exc:
            error = str(exc)
            for result in reversed(results):
                if result["status"] == "applied":
                    undo_operation(store_root, result)
                    result["status"] = "rolled-back"
            record = {
                "apply_id": apply_id,
                "plan_id": plan_id,
                "machine": plan["machine"],
                "started_at": started.isoformat(timespec="seconds"),
                "finished_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "success": False,
                "error": error,
                "operations": results,
            }
            record_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            raise

        record = {
            "apply_id": apply_id,
            "plan_id": plan_id,
            "machine": plan["machine"],
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "success": True,
            "error": None,
            "operations": results,
        }
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return record
