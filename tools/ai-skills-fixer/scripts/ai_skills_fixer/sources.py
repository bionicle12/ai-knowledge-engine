"""Source repository scanning: collections, single-skill repos, path IDs.

Skill identity is path-based (spec §7.1): for a collection the ID is
``<source-id>:<path relative to the declared root>``; for a single-skill
repository the ID is the bare source ID. A directory is a skill only if
it directly contains a readable ``SKILL.md``; skill directories are not
scanned inside, and duplicate relative paths across declared roots stop
the catalog with an error.

A source ID names a directory under ``sources/`` and prefixes every skill
ID, so it must be one portable path component without ``:``; declared
skill paths must stay inside the checkout. Linked folders are never
searched; a linked folder that is itself a skill is accepted only while
it resolves inside the checkout (outside ``.git``), otherwise the catalog
stops — a source must never pass off local content as its own.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import gitops
from .filesystem import is_junction, remove_tree
from .frontmatter import read_skill_file


class CatalogError(Exception):
    """A source layout declaration cannot be trusted; stop processing."""


SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
# Before 0.16.0 the default ID was the raw URL tail, so a registry may hold
# capitals; such an ID is still one safe path component and keeps loading.
_REGISTERED_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_source_id(source_id: str, *, registered: bool = False) -> str:
    """Return *source_id* or raise CatalogError when it is not a safe ID.

    New IDs must match ``SOURCE_ID_RE``; ``registered=True`` also accepts
    the capitals older registries may contain.
    """
    pattern = _REGISTERED_SOURCE_ID_RE if registered else SOURCE_ID_RE
    if not isinstance(source_id, str) or not pattern.match(source_id):
        raise CatalogError(
            f"invalid source id {source_id!r}: use lowercase letters, digits, "
            "'.', '_' and '-', starting with a letter or digit"
        )
    return source_id


def _inside(path: Path, base: Path) -> bool:
    return Path(path).resolve().is_relative_to(Path(base).resolve())


def _check_skill_dir(source_id: str, repo_root: Path, skill_dir: Path) -> None:
    """Refuse a skill folder that resolves outside the checkout or into .git."""
    if not _inside(skill_dir, repo_root) or _inside(skill_dir, Path(repo_root) / ".git"):
        raise CatalogError(
            f"source {source_id!r}: skill folder "
            f"{skill_dir.relative_to(repo_root).as_posix()!r} resolves outside "
            f"the checkout (to {skill_dir.resolve()}); refusing the source"
        )


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
        if child.name == ".git" or not child.is_dir():
            continue
        if child.is_symlink() or is_junction(child):
            # Never searched (no loops, no walks outside the checkout);
            # a linked skill folder is yielded for the caller to vet.
            if (child / "SKILL.md").is_file():
                yield child
            continue
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


def install_basename(skill: SourceSkill) -> str:
    """Directory name the skill gets in a host skill root.

    A collection skill keeps its own folder name; a single-skill source
    is installed under its source ID (its path is often just ``.``).
    """
    if skill.skill_id == skill.source_id:
        return skill.source_id
    return Path(skill.rel_path).name


def scan_source(source_id: str, repo_root: Path, layout: dict) -> list[SourceSkill]:
    repo_root = Path(repo_root)
    layout_type = layout.get("type")

    if layout_type == "single":
        skill_dir = (repo_root / layout.get("skill_path", ".")).resolve()
        if not _inside(skill_dir, repo_root) or _inside(skill_dir, repo_root / ".git"):
            raise CatalogError(
                f"source {source_id!r}: skill_path leaves the checkout"
            )
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
        if not _inside(base, repo_root):
            raise CatalogError(
                f"source {source_id!r}: declared root {root_rel!r} leaves the checkout"
            )
        if not base.is_dir():
            raise CatalogError(
                f"source {source_id!r}: declared root {root_rel!r} does not exist"
            )
        for skill_dir in _find_skill_dirs(base):
            _check_skill_dir(source_id, repo_root, skill_dir)
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
        validate_source_id(source_id, registered=True)
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
    tail = url.replace("\\", "/").rstrip("/").split("/")[-1]
    tail = tail[:-4] if tail.endswith(".git") else tail
    tail = tail.rsplit(":", 1)[-1]  # scp-like host:repo without a slash
    return re.sub(r"[^a-z0-9._-]+", "-", tail.lower()).lstrip("._-")


def source_checkout(store_root: Path, source_id: str) -> Path:
    """Checkout directory of a source; refuses IDs that escape ``sources/``."""
    validate_source_id(source_id, registered=True)
    base = Path(store_root) / "sources"
    path = base / source_id
    if not _inside(path, base):
        raise CatalogError(
            f"source checkout for {source_id!r} resolves outside {base}"
        )
    return path


def add_source(
    store_root: Path,
    url: str,
    source_id: str | None = None,
    ref: str | None = None,
) -> SourceSpec:
    registry = load_registry(store_root)
    source_id = validate_source_id(source_id or _default_source_id(url))
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
        try:
            remove_tree(dest)
        except OSError:
            pass
        raise

    # The checkout keeps the URL git was given; the registry (and every
    # plan and lock proposal derived from it) stores it without credentials.
    spec = SourceSpec(
        source_id=source_id, url=gitops.redact_url(url), ref=ref, layout=layout
    )
    registry[source_id] = spec
    save_registry(store_root, registry)
    return spec


def promote_source(store_root: Path, source_id: str) -> dict:
    """Move the source checkout to its update candidate (spec §5.3).

    Promotion only moves the store-internal checkout; installed skills
    change exclusively through an approved reconcile plan.
    """
    registry = load_registry(store_root)
    if source_id not in registry:
        raise CatalogError(f"source {source_id!r} is not registered")
    spec = registry[source_id]
    repo = source_checkout(store_root, source_id)
    if not repo.is_dir():
        raise CatalogError(f"source checkout missing at {repo}; re-add the source")
    if gitops.is_dirty(repo):
        raise CatalogError(f"source checkout {source_id!r} is dirty; refusing")
    try:
        candidate = gitops.rev_parse(repo, f"origin/{spec.ref}")
    except gitops.GitError:
        candidate = gitops.rev_parse(repo, spec.ref)
    gitops.checkout(repo, candidate)
    return {"source_id": source_id, "commit": candidate}


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
