"""Profile/machine configuration and the dry-run reconciliation planner.

Configuration errors raise ValidationError — a §19 safe-stop condition:
an unknown state or target is never silently ignored.

Plans only ever change direct children of a host's user skill root.
Anything the planner cannot prove it may touch — a copy of unknown
origin, a managed release edited in place, a source skill with symlinks
leading outside it, a same-named skill nested in a user folder — becomes
a ``review`` operation (never applied) with its reason in
``notes.review_reasons``.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import gitops
from .filesystem import default_install_strategy, unsafe_symlinks
from .discovery import discover_roots
from .inventory import scan_installed_root
from .provenance import content_hash
from .releases import release_dir
from .sources import (
    CatalogError,
    install_basename,
    load_registry,
    scan_source,
    source_checkout,
)

VALID_STATES = {
    "enabled",
    "occasional",
    "catalog-only",
    "excluded",
    "undecided",
    "protected",
}
CANONICAL_TARGETS = ("claude", "codex", "cursor", "antigravity")
PLAN_ID_RE = re.compile(r"^plan-[0-9a-f]{12}$")


class ValidationError(Exception):
    pass


@dataclass
class ProfileSkill:
    skill_id: str
    state: str
    targets: list[str] = field(default_factory=list)


def _profile_path(store_root: Path, name: str = "default") -> Path:
    return Path(store_root) / "profiles" / f"{name}.yml"


def _read_yaml(path: Path, what: str) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError(f"{what} not readable at {path}") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"{what} {path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{what} {path} must be a mapping")
    if data.get("schema_version") != 1:
        raise ValidationError(f"{what} {path}: unsupported schema_version")
    return data


def _validate_entry(entry: dict, where: str) -> ProfileSkill:
    skill_id = entry.get("id")
    if not isinstance(skill_id, str) or not skill_id:
        raise ValidationError(f"{where}: every skill entry needs an id")
    state = entry.get("state")
    if state not in VALID_STATES:
        raise ValidationError(
            f"{where}: skill {skill_id!r} has unknown state {state!r}; "
            f"valid states: {', '.join(sorted(VALID_STATES))}"
        )
    targets = entry.get("targets", [])
    if targets is None:
        targets = []
    if not isinstance(targets, list):
        raise ValidationError(f"{where}: skill {skill_id!r} targets must be a list")
    for target in targets:
        if target not in CANONICAL_TARGETS:
            raise ValidationError(
                f"{where}: skill {skill_id!r} has unknown target {target!r}; "
                f"canonical targets: {', '.join(CANONICAL_TARGETS)}"
            )
    return ProfileSkill(skill_id=skill_id, state=state, targets=list(targets))


def load_profile(store_root: Path, name: str = "default") -> list[ProfileSkill]:
    path = _profile_path(store_root, name)
    data = _read_yaml(path, "profile")
    entries = data.get("skills") or []
    if not isinstance(entries, list):
        raise ValidationError(f"profile {path}: skills must be a list")
    skills = [_validate_entry(e, f"profile {name}") for e in entries]
    seen: set[str] = set()
    for skill in skills:
        if skill.skill_id in seen:
            raise ValidationError(
                f"profile {name}: duplicate entry for {skill.skill_id!r}"
            )
        seen.add(skill.skill_id)
    return skills


DOMAIN_ANSWERS = {"frequent", "occasional", "interested", "excluded", "unsure"}


def save_profile(
    store_root: Path, skills: list[ProfileSkill], name: str = "default"
) -> None:
    path = _profile_path(store_root, name)
    try:
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    data = dict(existing)  # preserve domains and any future top-level keys
    data["schema_version"] = 1
    data["skills"] = [
        {
            "id": s.skill_id,
            "state": s.state,
            **({"targets": s.targets} if s.targets else {}),
        }
        for s in skills
    ]
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def set_profile_domain(
    store_root: Path, category: str, answer: str, name: str = "default"
) -> dict:
    """Record a category-level questionnaire answer with its date (§10)."""
    from datetime import datetime, timezone

    if answer not in DOMAIN_ANSWERS:
        raise ValidationError(
            f"unknown domain answer {answer!r}; valid: "
            f"{', '.join(sorted(DOMAIN_ANSWERS))}"
        )
    path = _profile_path(store_root, name)
    data = _read_yaml(path, "profile")
    domains = data.get("domains") or {}
    domains[category] = {
        "answer": answer,
        "date": datetime.now(timezone.utc).date().isoformat(),
    }
    data["domains"] = domains
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return domains[category]


def set_profile_state(
    store_root: Path,
    skill_id: str,
    state: str,
    targets: list[str] | None = None,
    name: str = "default",
) -> ProfileSkill:
    entry = _validate_entry(
        {"id": skill_id, "state": state, "targets": targets or []},
        f"profile {name}",
    )
    skills = load_profile(store_root, name)
    for idx, existing in enumerate(skills):
        if existing.skill_id == skill_id:
            if targets is None:
                entry.targets = existing.targets
            skills[idx] = entry
            break
    else:
        skills.append(entry)
    save_profile(store_root, skills, name)
    return entry


def load_machine(store_root: Path, machine: str) -> dict:
    path = Path(store_root) / "machines" / f"{machine}.local.yml"
    data = _read_yaml(path, "machine config")
    if data.get("machine_id") != machine:
        raise ValidationError(
            f"machine config {path}: machine_id must be {machine!r}"
        )
    agents = data.get("agents") or {}
    if not isinstance(agents, dict):
        raise ValidationError(f"machine config {path}: agents must be a mapping")
    for host in agents:
        if host not in CANONICAL_TARGETS:
            raise ValidationError(
                f"machine config {path}: unknown agent {host!r}"
            )
    overrides = data.get("profile_overrides") or {}
    if not isinstance(overrides, dict):
        raise ValidationError(
            f"machine config {path}: profile_overrides must be a mapping"
        )
    overrides.setdefault("disable", [])
    overrides.setdefault("additional_targets", {})
    if not isinstance(overrides["disable"], list):
        raise ValidationError(f"machine config {path}: disable must be a list")
    data["agents"] = agents
    data["profile_overrides"] = overrides
    return data


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _skill_suffix(skill_id: str) -> str:
    return skill_id.split(":", 1)[1] if ":" in skill_id else "skill"


def _within(path: Path, base: Path) -> bool:
    return Path(path).resolve().is_relative_to(Path(base).resolve())


def _under_releases(store_root: Path, path: Path) -> bool:
    return _within(path, Path(store_root) / "releases")


def _install_name(skill_id: str, entry) -> str:
    """Folder name of a profile skill in a host root (see install_basename)."""
    if entry is not None:
        return install_basename(entry[0])
    return Path(_skill_suffix(skill_id) if ":" in skill_id else skill_id).name


def plan_id_for(plan: dict) -> str:
    """Content-hash plan ID (spec §6.3).

    ``plan_id`` and ``created_at`` are metadata outside the hash, so the
    applier can recompute the ID of a saved plan and detect any edit made
    after the user approved it.
    """
    content = {k: v for k, v in plan.items() if k not in ("plan_id", "created_at")}
    canonical = json.dumps(
        content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return "plan-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _review_op(skill_id: str, host: str, source, dest: Path, inst) -> dict:
    precondition = (
        {"destination": "absent"} if inst is None
        else {"destination": "exists", "content_hash": inst.content_hash}
    )
    return {
        "skill_id": skill_id,
        "host": host,
        "type": "review",
        "strategy": None,
        "source": source,
        "destination": str(dest),
        "precondition": precondition,
        "backup": None,
        "validation": None,
        "rollback": None,
        "risk": "high",
        "approval_required": True,
    }


def _quarantine_op(skill_id: str, host: str, inst) -> dict:
    basename = Path(inst.path).name
    return {
        "skill_id": skill_id,
        "host": host,
        "type": "quarantine",
        "strategy": None,
        "source": None,
        "destination": str(inst.path),
        "precondition": {
            "destination": "exists",
            "content_hash": inst.content_hash,
        },
        "backup": f"move to state/backups/<apply-id>/{host}/{basename}",
        "validation": "destination absent after quarantine",
        "rollback": "restore quarantined copy from backup",
        "risk": "medium",
        "approval_required": True,
    }


def build_plan(
    store_root: Path,
    machine: str,
    home: Path | None = None,
    project_dir: Path | None = None,
    prune: bool = False,
) -> dict:
    """Dry-run reconciliation: desired state vs installed state.

    Never mutates installed skills; the only writes are the plan file
    under ``state/plans/``.
    """
    store_root = Path(store_root)
    registry = load_registry(store_root)
    profile = load_profile(store_root)
    machine_cfg = load_machine(store_root, machine)

    catalog: dict[str, tuple] = {}
    source_commits: dict[str, str] = {}
    for source_id, spec in sorted(registry.items()):
        checkout = source_checkout(store_root, source_id)
        if not checkout.is_dir():
            raise CatalogError(
                f"source checkout missing for {source_id!r}; re-add the source"
            )
        if gitops.is_dirty(checkout):
            raise CatalogError(
                f"source checkout {source_id!r} is dirty and cannot be trusted"
            )
        commit = gitops.current_commit(checkout)
        source_commits[source_id] = commit
        for source_skill in scan_source(source_id, checkout, spec.layout):
            catalog[source_skill.skill_id] = (source_skill, spec, commit)

    roots = discover_roots(home=home, project_dir=project_dir)
    user_roots = {r.host: r for r in roots if r.kind == "user"}
    # Only direct children of a user root are reconcile-managed; skills
    # nested inside a user folder are reported, never moved or replaced.
    installed: dict[tuple[str, str], object] = {}
    nested: dict[tuple[str, str], object] = {}
    for root in roots:
        if root.exists and root.kind == "user":
            for skill in scan_installed_root(root):
                key = (root.host, Path(skill.directory).name)
                if "/" in skill.directory:
                    nested.setdefault(key, skill)
                else:
                    installed[key] = skill

    agents = machine_cfg["agents"]
    overrides = machine_cfg["profile_overrides"]
    disabled_skills = set(overrides.get("disable", []))
    additional_targets = overrides.get("additional_targets", {}) or {}
    default_strategy = default_install_strategy()

    operations: list[dict] = []
    occasional_fallbacks: dict[str, str] = {}
    review_reasons: dict[str, str] = {}
    lock_skills: list[dict] = []

    def review(skill_id, host, source, dest, inst, reason) -> None:
        operations.append(_review_op(skill_id, host, source, dest, inst))
        review_reasons[f"{skill_id} -> {host}"] = reason

    for pskill in sorted(profile, key=lambda s: s.skill_id):
        if pskill.skill_id in disabled_skills:
            continue
        if pskill.state in ("undecided", "catalog-only"):
            continue

        entry = catalog.get(pskill.skill_id)

        if pskill.state == "excluded":
            basename = _install_name(pskill.skill_id, entry)
            digest = content_hash(entry[0].repo_path) if entry else None
            source_id = pskill.skill_id.split(":", 1)[0]
            release_root = (
                store_root / "releases" / source_id / _skill_suffix(pskill.skill_id)
            )
            for host in sorted(user_roots):
                inst = installed.get((host, basename))
                if inst is None:
                    other = nested.get((host, basename))
                    if other is not None and other.root_kind == "user":
                        review(
                            pskill.skill_id, host, None, other.path, other,
                            f"excluded, but a same-named skill is nested at "
                            f"{other.path}; reconcile only manages direct "
                            f"children of {user_roots[host].path}",
                        )
                    continue
                managed = (
                    inst.entry_type in ("symlink", "junction")
                    and _under_releases(store_root, inst.real_path)
                    and _within(inst.real_path, release_root)
                )
                if managed or (digest is not None and inst.content_hash == digest):
                    operations.append(_quarantine_op(pskill.skill_id, host, inst))
                else:
                    review(
                        pskill.skill_id, host, None, inst.path, inst,
                        "excluded, but the installed copy is not provably this "
                        "source's skill (unknown origin or local edits); "
                        "left in place",
                    )
            continue

        if entry is None:
            raise ValidationError(
                f"profile references {pskill.skill_id!r}, which no registered "
                "source provides"
            )
        source_skill, spec, commit = entry
        digest = content_hash(source_skill.repo_path)
        suffix = _skill_suffix(pskill.skill_id)
        basename = install_basename(source_skill)
        release_path = release_dir(store_root, spec.source_id, suffix, commit, digest)
        unsafe = unsafe_symlinks(source_skill.repo_path)

        targets = sorted(
            set(pskill.targets) | set(additional_targets.get(pskill.skill_id, []))
        )
        enabled_targets = [
            host for host in targets if (agents.get(host) or {}).get("enabled", False)
        ]

        lock_skills.append({
            "skill_id": pskill.skill_id,
            "source_id": spec.source_id,
            "url": gitops.redact_url(spec.url),
            "requested_ref": spec.ref,
            "resolved_commit": commit,
            "skill_path": source_skill.rel_path,
            "content_hash": digest,
            "name": source_skill.name,
            "description": source_skill.description,
            "release": str(release_path.relative_to(store_root)),
            "audit": {"status": "pending", "checked_at": None},
        })

        if pskill.state == "occasional":
            if enabled_targets:
                occasional_fallbacks[pskill.skill_id] = (
                    "catalog-only (no low-noise exposure on "
                    + ", ".join(enabled_targets)
                    + ")"
                )
            continue

        for host in enabled_targets:
            root = user_roots.get(host)
            if root is None or not root.exists:
                continue
            dest = root.path / basename
            inst = installed.get((host, basename))
            is_link = inst is not None and inst.entry_type in ("symlink", "junction")
            if unsafe:
                review(
                    pskill.skill_id, host, str(release_path), dest, inst,
                    "source skill contains symlinks resolving outside it: "
                    + ", ".join(unsafe),
                )
            elif inst is None and (host, basename) in nested:
                other = nested[(host, basename)]
                review(
                    pskill.skill_id, host, str(release_path), dest, None,
                    f"a same-named skill already exists nested at {other.path}; "
                    "installing would give the host two skills with one name",
                )
            elif inst is None:
                operations.append({
                    "skill_id": pskill.skill_id,
                    "host": host,
                    "type": "install",
                    "strategy": default_strategy,
                    "source": str(release_path),
                    "destination": str(dest),
                    "precondition": {"destination": "absent"},
                    "backup": None,
                    "validation": "post-install discovery check",
                    "rollback": "remove created link or copy",
                    "risk": "low",
                    "approval_required": True,
                })
            elif is_link and inst.real_path == release_path.resolve():
                if inst.content_hash != digest:
                    review(
                        pskill.skill_id, host, str(release_path), dest, inst,
                        f"managed release {release_path} was modified in place; "
                        "its content no longer matches its hash",
                    )
                    continue
                operations.append({
                    "skill_id": pskill.skill_id,
                    "host": host,
                    "type": "noop",
                    "strategy": None,
                    "source": str(release_path),
                    "destination": str(dest),
                    "precondition": {
                        "destination": "managed-link",
                        "target": str(release_path),
                    },
                    "backup": None,
                    "validation": None,
                    "rollback": None,
                    "risk": "none",
                    "approval_required": False,
                })
            elif is_link and _under_releases(store_root, inst.real_path):
                operations.append({
                    "skill_id": pskill.skill_id,
                    "host": host,
                    "type": "update",
                    "strategy": default_strategy,
                    "source": str(release_path),
                    "destination": str(dest),
                    "precondition": {
                        "destination": "managed-link",
                        "target": str(inst.real_path),
                    },
                    "backup": None,
                    "validation": "post-install discovery check",
                    "rollback": "relink the previous release",
                    "risk": "low",
                    "approval_required": True,
                })
            elif inst.content_hash == digest:
                operations.append({
                    "skill_id": pskill.skill_id,
                    "host": host,
                    "type": "adopt",
                    "strategy": default_strategy,
                    "source": str(release_path),
                    "destination": str(dest),
                    "precondition": {
                        "destination": "exists",
                        "content_hash": digest,
                    },
                    "backup": f"move to state/backups/<apply-id>/{host}/{basename}",
                    "validation": "post-install discovery check",
                    "rollback": "restore backup",
                    "risk": "medium",
                    "approval_required": True,
                })
            else:
                review(
                    pskill.skill_id, host, str(release_path), dest, inst,
                    "installed copy differs from the source (local edits or "
                    "another origin)",
                )

    prune_skipped: dict[str, list[str]] = {}
    if prune:
        profiled_states: dict[str, str] = {}
        for pskill in profile:
            basename = _install_name(pskill.skill_id, catalog.get(pskill.skill_id))
            profiled_states[basename] = pskill.state

        planned = {(op["host"], Path(op["destination"]).name) for op in operations}

        hash_to_skill: dict[str, str] = {}
        for skill_id, (source_skill, _spec, _commit) in catalog.items():
            hash_to_skill.setdefault(content_hash(source_skill.repo_path), skill_id)

        for (host, basename), inst in sorted(installed.items()):
            if getattr(inst, "root_kind", "user") != "user":
                continue
            if (host, basename) in planned:
                continue
            state = profiled_states.get(basename)
            if state in ("excluded", "undecided", "protected", "enabled"):
                continue  # excluded handled above; the rest are not prune targets
            matched = hash_to_skill.get(inst.content_hash)
            if matched is None:
                prune_skipped.setdefault(host, []).append(basename)
                continue
            operations.append(_quarantine_op(matched, host, inst))
        for host in prune_skipped:
            prune_skipped[host] = sorted(prune_skipped[host])

    operations.sort(key=lambda op: (op["skill_id"], op["host"], op["type"]))
    op_counts: dict[str, int] = {}
    for op in operations:
        op_counts[op["type"]] = op_counts.get(op["type"], 0) + 1

    content = {
        "schema_version": 1,
        "machine": machine,
        "strategy_default": default_strategy,
        "config_hashes": {
            "registry": _sha256_file(store_root / "registry" / "repositories.yml"),
            "profile": _sha256_file(store_root / "profiles" / "default.yml"),
            "machine": _sha256_file(
                store_root / "machines" / f"{machine}.local.yml"
            ),
        },
        "sources": source_commits,
        "user_roots": {
            host: str(root.path) for host, root in sorted(user_roots.items())
        },
        "operations": operations,
        "notes": {
            "occasional_fallbacks": occasional_fallbacks,
            "prune_skipped": prune_skipped,
            "review_reasons": review_reasons,
        },
        "lock_proposal": {"schema_version": 1, "skills": lock_skills},
        "summary": {"operations_by_type": dict(sorted(op_counts.items()))},
    }
    plan_id = plan_id_for(content)

    plan = dict(content)
    plan["plan_id"] = plan_id
    plan["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out = store_root / "state" / "plans" / f"{plan_id}.json"
    out.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return plan
