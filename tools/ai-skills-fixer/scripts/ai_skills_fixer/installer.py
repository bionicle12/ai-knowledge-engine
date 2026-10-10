"""Plan application with drift protection (spec §17, §18, §19).

Applying requires an immutable saved plan ID. The saved plan must still
hash to that ID (an edit after approval is refused), and every operation
that changes something must target a direct child of the host's user
skill root recorded in the plan — which in turn must be the user skill
root discovery finds on this machine now (a plan cannot bring its own
roots). Before any operation the tool verifies
that configuration hashes and source commits still match the plan; every
operation re-checks its own precondition at execution time.

The apply record is also the journal (write-ahead): it is written before
the first operation, when each operation starts, before each of its
effects (recording where content is about to go), and once more at the
end — so even an interrupted run leaves a record ``rollback`` can replay.
On any failure the failing operation's partial effects are undone first,
then already completed operations are rolled back in reverse; whatever
cannot be undone is marked ``needs-recovery`` with the reason. Drift
surfaces as DriftError (exit code 3), any other failure as ApplyError
(exit code 1).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import gitops
from .discovery import discover_roots
from .filesystem import (
    FilesystemError,
    managed_link_type,
    materialize_directory,
    remove_managed_link,
)
from .planner import PLAN_ID_RE, ValidationError, _skill_suffix, plan_id_for
from .provenance import content_hash
from .releases import ReleaseError, create_release
from .rollback import undo_started_operation
from .sources import source_checkout
from .store import LockError, store_lock, write_json_atomic

__all__ = ["ApplyError", "DriftError", "LockError", "apply_plan"]

MUTATING_OPS = ("install", "adopt", "update", "quarantine")


class DriftError(Exception):
    """The world no longer matches the approved plan."""


class ApplyError(Exception):
    """An operation failed for a reason other than drift."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_plan(store_root: Path, plan_id: str) -> dict:
    if not PLAN_ID_RE.match(plan_id or ""):
        raise ValidationError(f"invalid plan id {plan_id!r}")
    path = Path(store_root) / "state" / "plans" / f"{plan_id}.json"
    if not path.is_file():
        raise ValidationError(f"unknown plan {plan_id!r}; run reconcile first")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("plan_id") != plan_id or plan_id_for(plan) != plan_id:
        raise ValidationError(
            f"plan {plan_id} was edited after reconcile created it (its content "
            "no longer hashes to its ID); run reconcile again and approve the "
            "new plan"
        )
    _check_destinations(plan)
    return plan


def _check_destinations(plan: dict) -> None:
    roots = plan.get("user_roots")
    if not isinstance(roots, dict):
        raise ValidationError(
            f"plan {plan['plan_id']} predates destination checks; run "
            "reconcile again"
        )
    for op in plan["operations"]:
        if op["type"] not in MUTATING_OPS:
            continue
        root = roots.get(op["host"])
        dest = Path(op["destination"])
        if root is None or dest.parent != Path(root) or dest.name in ("", ".", ".."):
            raise ValidationError(
                f"{op['type']} of {op['skill_id']!r}: destination {dest} is not "
                f"a direct child of the {op['host']} user skill root; refusing"
            )


def _check_user_roots(plan: dict, home: Path | None) -> None:
    """Recorded user roots must be the ones discovered here and now."""
    current = {
        root.host: root.path
        for root in discover_roots(home=home)
        if root.kind == "user"
    }
    for op in plan["operations"]:
        if op["type"] not in MUTATING_OPS:
            continue
        recorded = Path(plan["user_roots"][op["host"]])
        actual = current.get(op["host"])
        if actual is None or recorded.resolve() != actual.resolve():
            raise ValidationError(
                f"plan {plan['plan_id']} targets {recorded} as the {op['host']} "
                f"user skill root, but discovery finds {actual} here; apply "
                "with the same --home (and environment) as reconcile, or run "
                "reconcile again"
            )


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
    try:
        release = create_release(
            store_root,
            lock_entry["source_id"],
            _skill_suffix(lock_entry["skill_id"]),
            skill_dir,
            lock_entry["resolved_commit"],
        )
    except ReleaseError as exc:
        raise DriftError(str(exc)) from exc
    if str(release.relative_to(store_root)) != lock_entry["release"]:
        raise DriftError(
            f"release path for {lock_entry['skill_id']!r} does not match the plan"
        )
    return release, lock_entry["content_hash"]


def _materialize(release: Path, dest: Path, strategy: str) -> None:
    try:
        materialize_directory(release, dest, strategy)
    except (FilesystemError, OSError) as exc:
        raise DriftError(str(exc)) from exc


def _validate_installed(dest: Path, digest: str) -> None:
    if not (dest / "SKILL.md").is_file() or content_hash(dest) != digest:
        raise DriftError(f"post-install validation failed at {dest}")


def _backup_dest(
    store_root: Path, apply_id: str, op: dict, dest: Path, result: dict, journal
) -> None:
    backup_rel = f"state/backups/{apply_id}/{op['host']}/{dest.name}"
    result["backup_path"] = backup_rel
    journal()  # intent first: a failed or interrupted move stays traceable
    backup = Path(store_root) / backup_rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dest), str(backup))


def _new_result(op: dict) -> dict:
    return {
        "type": op["type"],
        "skill_id": op["skill_id"],
        "host": op["host"],
        "destination": op["destination"],
        "strategy": op.get("strategy"),
        "backup_path": None,
        "release_hash": None,
        "previous_target": None,
        "previous_strategy": None,
        "status": "in-progress",
    }


def _apply_op(
    store_root: Path, op: dict, lock_by_id: dict, apply_id: str,
    result: dict, journal,
) -> None:
    """Run one operation, journaling each effect into *result* before it.

    ``release_hash`` is recorded before anything is materialized,
    ``backup_path`` before content moves to the backup, and
    ``previous_target`` before the old link is removed — exactly what
    ``undo_started_operation`` needs to reverse a half-done operation.
    """
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
        result["release_hash"] = digest
        journal()
        _materialize(release, dest, op["strategy"])
        _validate_installed(dest, digest)
        result["status"] = "applied"
    elif op_type == "adopt":
        expected = op["precondition"]["content_hash"]
        if not dest.is_dir() or content_hash(dest) != expected:
            raise DriftError(
                f"{dest} no longer matches the planned content hash"
            )
        release, digest = _ensure_release(store_root, lock_by_id[op["skill_id"]])
        result["release_hash"] = digest
        _backup_dest(store_root, apply_id, op, dest, result, journal)
        _materialize(release, dest, op["strategy"])
        _validate_installed(dest, digest)
        result["status"] = "applied"
    elif op_type == "update":
        expected_target = op["precondition"]["target"]
        previous_strategy = managed_link_type(dest)
        if previous_strategy is None or str(dest.resolve()) != str(
            Path(expected_target).resolve()
        ):
            raise DriftError(
                f"{dest} is no longer the managed link the plan expected"
            )
        release, digest = _ensure_release(store_root, lock_by_id[op["skill_id"]])
        result.update(
            release_hash=digest,
            previous_target=expected_target,
            previous_strategy=previous_strategy,
        )
        journal()
        try:
            remove_managed_link(dest)
        except FilesystemError as exc:
            raise DriftError(str(exc)) from exc
        _materialize(release, dest, op["strategy"])
        _validate_installed(dest, digest)
        result["status"] = "applied"
    elif op_type == "quarantine":
        expected = op["precondition"]["content_hash"]
        if not dest.is_dir() or content_hash(dest) != expected:
            raise DriftError(
                f"{dest} no longer matches the planned content hash"
            )
        _backup_dest(store_root, apply_id, op, dest, result, journal)
        result["status"] = "applied"
    else:
        raise DriftError(f"unknown operation type {op_type!r}")


def _undo(store_root: Path, result: dict, done_status: str) -> bool:
    """Reverse a started operation; on failure mark it for manual recovery."""
    try:
        undo_started_operation(store_root, result)
    except Exception as exc:  # noqa: BLE001 — recorded, never swallowed silently
        result["status"] = "needs-recovery"
        result["recovery"] = str(exc)
        return False
    result["status"] = done_status
    return True


def _new_apply_id(store_root: Path, plan_id: str, started: datetime) -> str:
    base = f"{plan_id}.apply-{started.strftime('%Y%m%dT%H%M%SZ')}"
    apply_id, n = base, 1
    while (store_root / "state" / "plans" / f"{apply_id}.json").exists():
        n += 1
        apply_id = f"{base}-{n}"
    return apply_id


def apply_plan(store_root: Path, plan_id: str, home: Path | None = None) -> dict:
    """Apply a saved plan; *home* must be the one reconcile discovered with."""
    store_root = Path(store_root)
    plan = _load_plan(store_root, plan_id)
    _check_user_roots(plan, home)

    with store_lock(store_root):
        _check_config_drift(store_root, plan)
        _check_source_drift(store_root, plan)

        lock_by_id = {
            entry["skill_id"]: entry
            for entry in plan["lock_proposal"]["skills"]
        }
        started = datetime.now(timezone.utc)
        apply_id = _new_apply_id(store_root, plan_id, started)
        record_path = store_root / "state" / "plans" / f"{apply_id}.json"

        results: list[dict] = []
        record = {
            "apply_id": apply_id,
            "plan_id": plan_id,
            "machine": plan["machine"],
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": None,
            "success": False,
            "error": None,
            "operations": results,
        }

        def journal() -> None:
            write_json_atomic(record_path, record)

        journal()
        try:
            for op in plan["operations"]:
                result = _new_result(op)
                results.append(result)
                journal()
                try:
                    _apply_op(store_root, op, lock_by_id, apply_id, result, journal)
                except Exception:
                    _undo(store_root, result, "failed")
                    raise
                journal()
        except Exception as exc:
            record["error"] = str(exc)
            for result in reversed(results):
                if result["status"] == "applied":
                    _undo(store_root, result, "rolled-back")
                    journal()
            recovered = all(r["status"] != "needs-recovery" for r in results)
            outcome = (
                "completed operations were rolled back" if recovered else
                "some operations need manual recovery (status needs-recovery); "
                f"fix them, then run: rollback {apply_id}"
            )
            message = f"{exc} [apply {apply_id}: {outcome}]"
            if isinstance(exc, DriftError):
                raise DriftError(message) from exc
            raise ApplyError(message) from exc
        else:
            record["success"] = True
        finally:
            record["finished_at"] = datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            )
            journal()
    return record
