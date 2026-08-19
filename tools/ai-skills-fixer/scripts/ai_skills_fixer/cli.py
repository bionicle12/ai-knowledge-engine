"""Phase 1 CLI: read-only inventory with --json and the exit-code contract.

Exit codes (spec §17): 0 success, 2 safe stop on a §19 condition,
3 drift/precondition failure (unused in Phase 1), 1 any other error.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from . import __version__
from .discovery import discover_roots
from .gitops import GitError
from .installer import DriftError, apply_plan
from .inventory import find_duplicates, match_provenance, scan_installed_root
from .linting import lint_skill_dir
from .planner import ValidationError, build_plan, load_profile, set_profile_state
from .rollback import RollbackError, rollback_apply
from .store import LockError
from .sources import (
    CatalogError,
    add_source,
    detect_layout,
    load_registry,
    refresh_source,
    scan_source,
    source_checkout,
)
from .store import init_store, machine_id, resolve_store_root

TOKEN_NOTE = (
    "Token counts are size-based estimates (chars/4), not measured tokenizer output."
)


def _as_dict(obj) -> dict:
    data = dataclasses.asdict(obj)
    for key, value in data.items():
        if isinstance(value, Path):
            data[key] = str(value)
    return data


def build_inventory(
    home: Path | None,
    project_dir: Path | None,
    source_repos: list[Path],
) -> dict:
    roots = discover_roots(home=home, project_dir=project_dir)

    skills = []
    for root in roots:
        if root.exists:
            skills.extend(scan_installed_root(root))

    catalog = []
    sources_meta = []
    for repo in source_repos:
        repo = Path(repo).resolve()
        layout = detect_layout(repo)
        source_id = repo.name
        found = scan_source(source_id, repo, layout)
        catalog.extend(found)
        sources_meta.append(
            {"source_id": source_id, "path": str(repo), "layout": layout,
             "skills_found": len(found)}
        )

    match_provenance(skills, catalog)
    duplicates = find_duplicates(skills)

    findings = []
    for skill in skills:
        if not skill.has_skill_md:
            continue
        for finding in lint_skill_dir(skill.path):
            record = _as_dict(finding)
            record["host"] = skill.host
            record["path"] = str(skill.path)
            findings.append(record)

    provenance_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    real_skills = [s for s in skills if s.has_skill_md]
    for skill in real_skills:
        level = (skill.provenance or {}).get("level", "unknown")
        provenance_counts[level] = provenance_counts.get(level, 0) + 1
    for finding in findings:
        severity_counts[finding["severity"]] = (
            severity_counts.get(finding["severity"], 0) + 1
        )

    return {
        "generated_by": f"ai-skills-fixer {__version__}",
        "token_note": TOKEN_NOTE,
        "roots": [_as_dict(r) for r in roots],
        "sources": sources_meta,
        "skills": [_as_dict(s) for s in skills],
        "duplicates": {
            name: [{"host": s.host, "root_kind": s.root_kind, "path": str(s.path)}
                   for s in group]
            for name, group in sorted(duplicates.items())
        },
        "findings": findings,
        "summary": {
            "skills_total": len(real_skills),
            "unknown_artifacts": len(skills) - len(real_skills),
            "hosts": sorted({s.host for s in skills}),
            "provenance": dict(sorted(provenance_counts.items())),
            "duplicate_names": len(duplicates),
            "findings_by_severity": dict(sorted(severity_counts.items())),
            "size_bytes_total": sum(s.size_bytes for s in real_skills),
            "token_estimate_total": sum(s.token_estimate for s in real_skills),
        },
    }


def _print_human(payload: dict) -> None:
    summary = payload["summary"]
    print(f"ai-skills-fixer inventory ({payload['generated_by']})")
    print()
    print(f"Skills found: {summary['skills_total']} "
          f"(+{summary['unknown_artifacts']} non-skill artifacts) "
          f"across hosts: {', '.join(summary['hosts']) or 'none'}")
    print(f"Provenance: " + ", ".join(
        f"{level}={count}" for level, count in summary["provenance"].items()
    ))
    print(f"Estimated SKILL.md tokens (total): {summary['token_estimate_total']}")
    print(f"  note: {payload['token_note']}")
    print()

    if payload["duplicates"]:
        print(f"Duplicate skill names ({summary['duplicate_names']}):")
        for name, group in payload["duplicates"].items():
            hosts = ", ".join(f"{g['host']}:{g['root_kind']}" for g in group)
            print(f"  {name}  [{hosts}]")
        print()

    print("Per-skill provenance:")
    for skill in payload["skills"]:
        if not skill["has_skill_md"]:
            continue
        level = (skill["provenance"] or {}).get("level", "unknown")
        print(f"  {skill['host']:<12} {skill['directory']:<40} {level}")
    print()

    if payload["findings"]:
        print(f"Lint findings ({len(payload['findings'])}):")
        for finding in payload["findings"][:40]:
            print(f"  [{finding['severity']}] {finding['host']}:{finding['skill']} "
                  f"{finding['check']}: {finding['message']}")
        if len(payload["findings"]) > 40:
            print(f"  ... and {len(payload['findings']) - 40} more (use --json)")


def _emit(payload: dict, as_json: bool, human_lines: list[str]) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for line in human_lines:
            print(line)


def _cmd_init(args) -> int:
    store = resolve_store_root(args.store_root)
    machine = args.machine_id or machine_id()
    created = init_store(store, machine)
    _emit(
        {"store": str(store), "machine": machine, "created": created},
        args.json,
        [f"store: {store}",
         f"machine: {machine}",
         "created" if created else "already initialized"],
    )
    return 0


def _cmd_doctor(args) -> int:
    import platform
    import subprocess

    store = resolve_store_root(args.store_root)
    machine = args.machine_id or machine_id()
    try:
        git_version = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, check=True
        ).stdout.strip()
        git_ok = True
    except (OSError, subprocess.CalledProcessError):
        git_version, git_ok = None, False

    initialized = (store / "registry" / "repositories.yml").is_file()
    sources = []
    if initialized:
        try:
            sources = sorted(load_registry(store))
        except CatalogError:
            initialized = False

    payload = {
        "python": {"version": platform.python_version()},
        "git": {"available": git_ok, "version": git_version},
        "store": {
            "root": str(store),
            "initialized": initialized,
            "machine": machine,
            "machine_file": (store / "machines" / f"{machine}.local.yml").is_file(),
            "sources": sources,
        },
    }
    _emit(payload, args.json, [
        f"python {payload['python']['version']}",
        f"git: {git_version or 'MISSING'}",
        f"store: {store} ({'initialized' if initialized else 'NOT initialized'})",
        f"machine: {machine}",
        f"sources: {', '.join(sources) or 'none'}",
    ])
    return 0


def _cmd_source_add(args) -> int:
    store = resolve_store_root(args.store_root)
    spec = add_source(store, args.url, source_id=args.id, ref=args.ref)
    skills = scan_source(
        spec.source_id, source_checkout(store, spec.source_id), spec.layout
    )
    _emit(
        {"source_id": spec.source_id, "url": spec.url, "ref": spec.ref,
         "layout": spec.layout, "skills_found": len(skills)},
        args.json,
        [f"registered {spec.source_id} at ref {spec.ref} "
         f"({len(skills)} skills, layout {spec.layout['type']})"],
    )
    return 0


def _cmd_source_refresh(args) -> int:
    store = resolve_store_root(args.store_root)
    ids = [args.source_id] if args.source_id else sorted(load_registry(store))
    candidates = [refresh_source(store, source_id) for source_id in ids]
    lines = []
    for cand in candidates:
        status = "update available" if cand["changed"] else "up to date"
        lines.append(
            f"{cand['source_id']}: {status} "
            f"(current {cand['current_commit'][:12]}, "
            f"candidate {cand['candidate_commit'][:12]})"
        )
    _emit({"candidates": candidates}, args.json, lines)
    return 0


def _cmd_catalog(args) -> int:
    store = resolve_store_root(args.store_root)
    registry = load_registry(store)
    ids = [args.source_id] if args.source_id else sorted(registry)
    skills = []
    for source_id in ids:
        if source_id not in registry:
            raise CatalogError(f"source {source_id!r} is not registered")
        spec = registry[source_id]
        for s in scan_source(source_id, source_checkout(store, source_id), spec.layout):
            skills.append({
                "skill_id": s.skill_id,
                "name": s.name,
                "description": s.description,
                "rel_path": s.rel_path,
                "error": s.error,
            })
    lines = [f"{len(skills)} skills:"]
    for s in skills:
        desc = (s["description"] or "")[:80]
        lines.append(f"  {s['skill_id']:<50} {desc}")
    _emit({"skills": skills}, args.json, lines)
    return 0


def _cmd_profile_show(args) -> int:
    store = resolve_store_root(args.store_root)
    skills = load_profile(store)
    payload = {
        "schema_version": 1,
        "skills": [
            {"id": s.skill_id, "state": s.state, "targets": s.targets}
            for s in skills
        ],
    }
    lines = [f"{len(skills)} profile entries:"]
    for s in skills:
        targets = f" -> {', '.join(s.targets)}" if s.targets else ""
        lines.append(f"  {s.skill_id:<50} {s.state}{targets}")
    _emit(payload, args.json, lines)
    return 0


def _cmd_profile_set(args) -> int:
    store = resolve_store_root(args.store_root)
    entry = set_profile_state(
        store, args.skill_id, args.state, targets=args.targets
    )
    _emit(
        {"id": entry.skill_id, "state": entry.state, "targets": entry.targets},
        args.json,
        [f"{entry.skill_id}: {entry.state}"
         + (f" -> {', '.join(entry.targets)}" if entry.targets else "")],
    )
    return 0


def _cmd_reconcile(args) -> int:
    store = resolve_store_root(args.store_root)

    if args.apply:
        record = apply_plan(store, args.apply)
        lines = [f"applied plan {record['plan_id']} as {record['apply_id']}"]
        for result in record["operations"]:
            lines.append(
                f"  [{result['status']:<22}] {result['type']} "
                f"{result['skill_id']} -> {result['host']}"
            )
        lines.append(f"rollback with: rollback {record['apply_id']}")
        _emit(record, args.json, lines)
        return 0

    machine = args.machine_id or machine_id()
    plan = build_plan(store, machine, home=args.home, project_dir=args.project_dir)

    lines = [
        f"plan {plan['plan_id']} (dry run, machine {plan['machine']})",
        f"operations: {plan['summary']['operations_by_type'] or 'none'}",
    ]
    for op in plan["operations"]:
        lines.append(
            f"  [{op['type']:<10}] {op['skill_id']} -> {op['host']} "
            f"(risk {op['risk']}) {op['destination']}"
        )
    for skill_id, note in plan["notes"]["occasional_fallbacks"].items():
        lines.append(f"  note: {skill_id}: {note}")
    lines.append(
        "dry run only; nothing was changed. Apply with: "
        f"reconcile --apply {plan['plan_id']}"
    )
    _emit(plan, args.json, lines)
    return 0


def _cmd_rollback(args) -> int:
    store = resolve_store_root(args.store_root)
    record = rollback_apply(store, args.apply_id)
    lines = [f"rolled back {record['apply_id']} at {record['rolled_back_at']}"]
    for result in record["operations"]:
        lines.append(
            f"  [{result['status']:<22}] {result['type']} "
            f"{result['skill_id']} -> {result['host']}"
        )
    _emit(record, args.json, lines)
    return 0


def _cmd_inventory(args) -> int:
    payload = build_inventory(args.home, args.project_dir, args.source_repo)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0


def _add_store_opts(parser) -> None:
    parser.add_argument("--store-root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai-skills-fixer")
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="read-only skill inventory")
    inv.add_argument("--json", action="store_true", help="machine-readable output")
    inv.add_argument("--home", type=Path, default=None,
                     help="override home directory (tests/fixtures)")
    inv.add_argument("--project-dir", type=Path, default=None,
                     help="project directory to check for project-local skills")
    inv.add_argument("--source-repo", type=Path, action="append", default=[],
                     help="path to a source skill repository (repeatable)")
    inv.set_defaults(handler=_cmd_inventory)

    init_p = sub.add_parser("init", help="initialize the managed store")
    _add_store_opts(init_p)
    init_p.add_argument("--machine-id", default=None)
    init_p.set_defaults(handler=_cmd_init)

    doctor_p = sub.add_parser("doctor", help="environment and store checks")
    _add_store_opts(doctor_p)
    doctor_p.add_argument("--machine-id", default=None)
    doctor_p.set_defaults(handler=_cmd_doctor)

    source_p = sub.add_parser("source", help="manage skill sources")
    ssub = source_p.add_subparsers(dest="source_command", required=True)
    add_p = ssub.add_parser("add", help="clone and register a source")
    add_p.add_argument("url")
    add_p.add_argument("--id", default=None)
    add_p.add_argument("--ref", default=None)
    _add_store_opts(add_p)
    add_p.set_defaults(handler=_cmd_source_add)
    refresh_p = ssub.add_parser("refresh", help="fetch and record update candidates")
    refresh_p.add_argument("source_id", nargs="?", default=None)
    _add_store_opts(refresh_p)
    refresh_p.set_defaults(handler=_cmd_source_refresh)

    catalog_p = sub.add_parser("catalog", help="list skills in registered sources")
    catalog_p.add_argument("source_id", nargs="?", default=None)
    _add_store_opts(catalog_p)
    catalog_p.set_defaults(handler=_cmd_catalog)

    profile_p = sub.add_parser("profile", help="show or edit the shared profile")
    psub = profile_p.add_subparsers(dest="profile_command", required=True)
    show_p = psub.add_parser("show")
    _add_store_opts(show_p)
    show_p.set_defaults(handler=_cmd_profile_show)
    set_p = psub.add_parser("set")
    set_p.add_argument("skill_id")
    set_p.add_argument("state")
    set_p.add_argument("--targets", nargs="*", default=None)
    _add_store_opts(set_p)
    set_p.set_defaults(handler=_cmd_profile_set)

    reconcile_p = sub.add_parser("reconcile", help="dry-run reconciliation plan")
    _add_store_opts(reconcile_p)
    reconcile_p.add_argument("--machine-id", default=None)
    reconcile_p.add_argument("--home", type=Path, default=None)
    reconcile_p.add_argument("--project-dir", type=Path, default=None)
    reconcile_p.add_argument("--apply", metavar="PLAN_ID", default=None,
                             help="apply a saved approved plan (checks drift)")
    reconcile_p.set_defaults(handler=_cmd_reconcile)

    rollback_p = sub.add_parser("rollback", help="roll back an applied plan")
    rollback_p.add_argument("apply_id")
    _add_store_opts(rollback_p)
    rollback_p.set_defaults(handler=_cmd_rollback)

    args = parser.parse_args(argv)

    try:
        return args.handler(args)
    except DriftError as exc:
        print(f"drift: {exc}", file=sys.stderr)
        return 3
    except (CatalogError, ValidationError, LockError, RollbackError) as exc:
        print(f"safe stop: {exc}", file=sys.stderr)
        return 2
    except GitError as exc:
        print(f"git error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — contract: 1 = unexpected error
        print(f"error: {exc}", file=sys.stderr)
        return 1
