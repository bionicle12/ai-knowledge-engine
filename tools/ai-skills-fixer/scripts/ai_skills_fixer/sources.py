"""Source repository scanning: collections, single-skill repos, path IDs.

Skill identity is path-based (spec §7.1): for a collection the ID is
``<source-id>:<path relative to the declared root>``; for a single-skill
repository the ID is the bare source ID. A directory is a skill only if
it directly contains a readable ``SKILL.md``; skill directories are not
scanned inside, and duplicate relative paths across declared roots stop
the catalog with an error.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import gitops
from .frontmatter import read_skill_file


class CatalogError(Exception):
    """A source layout declaration cannot be trusted; stop processing."""


@dataclass
class SourceSkill:
    source_id: str
    skill_id: str
    repo_path: Path
    rel_path: str
    name: str | None = None
    description: str | None = None
    error: str | None = None


def _find_skill_dirs(base: Path):
    if (base / "SKILL.md").is_file():
        yield base
        return
    if not base.is_dir():
        return
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if child.is_dir() and child.name != ".git":
            yield from _find_skill_dirs(child)


def _make_skill(source_id: str, skill_id: str, repo_root: Path, skill_dir: Path) -> SourceSkill:
    doc = read_skill_file(skill_dir / "SKILL.md")
    name = doc.frontmatter.get("name")
    description = doc.frontmatter.get("description")
    return SourceSkill(
        source_id=source_id,
        skill_id=skill_id,
        repo_path=skill_dir,
        rel_path=skill_dir.relative_to(repo_root).as_posix(),
        name=name if isinstance(name, str) else None,
        description=description if isinstance(description, str) else None,
        error=doc.error,
    )


def scan_source(source_id: str, repo_root: Path, layout: dict) -> list[SourceSkill]:
    repo_root = Path(repo_root)
    layout_type = layout.get("type")

    if layout_type == "single":
        skill_dir = (repo_root / layout.get("skill_path", ".")).resolve()
        if not (skill_dir / "SKILL.md").is_file():
            raise CatalogError(
                f"source {source_id!r}: no SKILL.md at declared skill_path"
            )
        return [_make_skill(source_id, source_id, repo_root.resolve(), skill_dir)]

    if layout_type != "collection":
        raise CatalogError(f"source {source_id!r}: unknown layout type {layout_type!r}")

    found: dict[str, SourceSkill] = {}
    for root_rel in layout.get("roots", []):
        base = repo_root / root_rel
        if not base.is_dir():
            raise CatalogError(
                f"source {source_id!r}: declared root {root_rel!r} does not exist"
            )
        for skill_dir in _find_skill_dirs(base):
            rel_to_root = skill_dir.relative_to(base).as_posix()
            skill_id = f"{source_id}:{rel_to_root}"
            if skill_id in found:
                raise CatalogError(
                    f"source {source_id!r}: duplicate skill path {rel_to_root!r} "
                    "across declared roots"
                )
            found[skill_id] = _make_skill(source_id, skill_id, repo_root, skill_dir)

    return sorted(found.values(), key=lambda s: s.skill_id)


@dataclass
class SourceSpec:
    source_id: str
    url: str
    ref: str
    layout: dict


def detect_layout(repo: Path) -> dict:
    repo = Path(repo)
    if not repo.is_dir():
        raise CatalogError(f"source repository {repo} does not exist")
    if (repo / "skills").is_dir():
        return {"type": "collection", "roots": ["skills"]}
    if (repo / "SKILL.md").is_file():
        return {"type": "single", "skill_path": "."}
    raise CatalogError(
        f"source repository {repo} has neither a skills/ root nor a top-level SKILL.md"
    )


def _registry_path(store_root: Path) -> Path:
    return Path(store_root) / "registry" / "repositories.yml"


def load_registry(store_root: Path) -> dict[str, SourceSpec]:
    path = _registry_path(store_root)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogError(f"store not initialized: cannot read {path}") from exc
    except yaml.YAMLError as exc:
        raise CatalogError(f"registry {path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CatalogError(f"registry {path}: unsupported schema_version")
    repositories = data.get("repositories") or {}
    if not isinstance(repositories, dict):
        raise CatalogError(f"registry {path}: repositories must be a mapping")
    specs: dict[str, SourceSpec] = {}
    for source_id, entry in repositories.items():
        if not isinstance(entry, dict) or not entry.get("url") or not entry.get("ref"):
            raise CatalogError(f"registry entry {source_id!r}: url and ref required")
        layout = entry.get("layout")
        if not isinstance(layout, dict) or "type" not in layout:
            raise CatalogError(f"registry entry {source_id!r}: layout.type required")
        specs[source_id] = SourceSpec(
            source_id=source_id, url=entry["url"], ref=entry["ref"], layout=layout
        )
    return specs


def save_registry(store_root: Path, specs: dict[str, SourceSpec]) -> None:
    data = {
        "schema_version": 1,
        "repositories": {
            spec.source_id: {"url": spec.url, "ref": spec.ref, "layout": spec.layout}
            for spec in sorted(specs.values(), key=lambda s: s.source_id)
        },
    }
    _registry_path(store_root).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _default_source_id(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    return tail[:-4] if tail.endswith(".git") else tail


def source_checkout(store_root: Path, source_id: str) -> Path:
    return Path(store_root) / "sources" / source_id


def add_source(
    store_root: Path,
    url: str,
    source_id: str | None = None,
    ref: str | None = None,
) -> SourceSpec:
    registry = load_registry(store_root)
    source_id = source_id or _default_source_id(url)
    if source_id in registry:
        raise CatalogError(f"source {source_id!r} is already registered")

    dest = source_checkout(store_root, source_id)
    if dest.exists():
        raise CatalogError(f"source checkout already exists at {dest}")

    gitops.clone(url, dest)
    try:
        if ref:
            gitops.checkout(dest, ref)
        else:
            ref = gitops.current_branch(dest)
        layout = detect_layout(dest)
        scan_source(source_id, dest, layout)  # validate before registering
    except (CatalogError, gitops.GitError):
        shutil.rmtree(dest, ignore_errors=True)
        raise

    spec = SourceSpec(source_id=source_id, url=url, ref=ref, layout=layout)
    registry[source_id] = spec
    save_registry(store_root, registry)
    return spec


def refresh_source(store_root: Path, source_id: str) -> dict:
    registry = load_registry(store_root)
    if source_id not in registry:
        raise CatalogError(f"source {source_id!r} is not registered")
    spec = registry[source_id]
    repo = source_checkout(store_root, source_id)
    if not repo.is_dir():
        raise CatalogError(f"source checkout missing at {repo}; re-add the source")

    gitops.fetch(repo)
    try:
        candidate_commit = gitops.rev_parse(repo, f"origin/{spec.ref}")
    except gitops.GitError:
        candidate_commit = gitops.rev_parse(repo, spec.ref)
    current = gitops.current_commit(repo)

    candidate = {
        "source_id": source_id,
        "requested_ref": spec.ref,
        "current_commit": current,
        "candidate_commit": candidate_commit,
        "changed": candidate_commit != current,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    out = Path(store_root) / "state" / "candidates" / f"{source_id}.json"
    out.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return candidate
