"""Installed-skill inventory: physical facts, duplicates, provenance (spec §9).

Reads everything offline — git metadata comes from parsing ``.git``
files directly, never from executing repository content. Token counts
are size-based estimates and are labeled as such in reports.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import SkillRoot
from .filesystem import managed_link_type
from .frontmatter import read_skill_file
from .provenance import content_hash
from .sources import SourceSkill

TOKEN_CHARS_PER_TOKEN = 4  # coarse estimate; always labeled as an estimate


@dataclass
class InstalledSkill:
    host: str
    root_kind: str
    root: Path
    directory: str  # path relative to the discovery root (posix)
    path: Path
    real_path: Path
    entry_type: str  # directory | symlink | junction
    has_skill_md: bool
    name: str | None = None
    description: str | None = None
    frontmatter_error: str | None = None
    content_hash: str | None = None
    size_bytes: int = 0
    file_count: int = 0
    skill_md_chars: int = 0
    skill_md_words: int = 0
    token_estimate: int = 0
    git: dict | None = None
    provenance: dict | None = None


def _measure_tree(path: Path) -> tuple[int, int]:
    size = 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                size += p.lstat().st_size
            except OSError:
                continue
            count += 1
    return size, count


def _parse_git_head(git_dir: Path) -> str | None:
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head.startswith("ref: "):
        ref = head[len("ref: "):].strip()
        try:
            return (git_dir / ref).read_text(encoding="utf-8").strip()
        except OSError:
            packed = git_dir / "packed-refs"
            try:
                for line in packed.read_text(encoding="utf-8").splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0]
            except OSError:
                return None
            return None
    return head or None


def _parse_git_remote(git_dir: Path) -> str | None:
    try:
        lines = (git_dir / "config").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    in_origin = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped.replace(" ", "") in ('[remote"origin"]',)
        elif in_origin and stripped.startswith("url"):
            _, _, value = stripped.partition("=")
            return value.strip()
    return None


def _git_facts(path: Path) -> dict | None:
    current = path.resolve()
    for candidate in [current, *current.parents]:
        git_dir = candidate / ".git"
        if git_dir.is_dir():
            return {
                "root": str(candidate),
                "commit": _parse_git_head(git_dir),
                "remote": _parse_git_remote(git_dir),
            }
    return None


def _make_record(root: SkillRoot, skill_dir: Path, entry: Path) -> InstalledSkill:
    directory = skill_dir.relative_to(root.path).as_posix()
    entry_type = managed_link_type(entry) or "directory"
    skill_md = skill_dir / "SKILL.md"
    has_skill_md = skill_md.is_file()

    root_kind = root.kind
    if root.host == "codex" and directory.startswith(".system/"):
        # Codex bundles its own skills under ~/.codex/skills/.system/.
        root_kind = "system"

    record = InstalledSkill(
        host=root.host,
        root_kind=root_kind,
        root=root.path,
        directory=directory,
        path=skill_dir,
        real_path=skill_dir.resolve(),
        entry_type=entry_type,
        has_skill_md=has_skill_md,
    )

    record.size_bytes, record.file_count = _measure_tree(record.real_path)
    record.content_hash = content_hash(record.real_path)
    record.git = _git_facts(record.real_path)

    if has_skill_md:
        doc = read_skill_file(skill_md)
        record.frontmatter_error = doc.error
        name = doc.frontmatter.get("name")
        description = doc.frontmatter.get("description")
        record.name = name if isinstance(name, str) else None
        record.description = description if isinstance(description, str) else None
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        record.skill_md_chars = len(text)
        record.skill_md_words = len(text.split())
        record.token_estimate = max(1, record.skill_md_chars // TOKEN_CHARS_PER_TOKEN)
    return record


def _nested_skill_dirs(base: Path):
    if (base / "SKILL.md").is_file():
        yield base
        return
    if not base.is_dir():
        return
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if child.is_dir() and child.name != ".git":
            yield from _nested_skill_dirs(child)


def scan_installed_root(root: SkillRoot) -> list[InstalledSkill]:
    if not root.path.is_dir():
        return []
    records: list[InstalledSkill] = []
    for child in sorted(root.path.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        nested = list(_nested_skill_dirs(child))
        if nested:
            for skill_dir in nested:
                records.append(_make_record(root, skill_dir, child))
        else:
            records.append(_make_record(root, child, child))
    return records


def find_duplicates(skills: list[InstalledSkill]) -> dict[str, list[InstalledSkill]]:
    groups: dict[str, list[InstalledSkill]] = {}
    for skill in skills:
        if not skill.has_skill_md:
            continue
        key = Path(skill.directory).name
        groups.setdefault(key, []).append(skill)
    return {key: group for key, group in groups.items() if len(group) > 1}


def match_provenance(
    skills: list[InstalledSkill], catalog: list[SourceSkill]
) -> None:
    by_hash: dict[str, list[SourceSkill]] = {}
    by_name: dict[str, list[SourceSkill]] = {}
    for source_skill in catalog:
        digest = content_hash(source_skill.repo_path)
        by_hash.setdefault(digest, []).append(source_skill)
        by_name.setdefault(Path(source_skill.rel_path).name, []).append(source_skill)
        if source_skill.name:
            by_name.setdefault(source_skill.name, []).append(source_skill)

    for skill in skills:
        if not skill.has_skill_md or skill.content_hash is None:
            continue
        basename = Path(skill.directory).name
        hash_matches = by_hash.get(skill.content_hash, [])
        if hash_matches:
            same_name = [
                s for s in hash_matches if Path(s.rel_path).name == basename
            ]
            chosen = same_name[0] if same_name else hash_matches[0]
            level = "exact" if same_name else "probable"
            skill.provenance = {
                "level": level,
                "skill_id": chosen.skill_id,
                "source_id": chosen.source_id,
                "detail": "content hash matches source checkout",
            }
            continue
        if skill.root_kind in ("plugin", "system"):
            # Plugin- and system-managed skills are owned by their client;
            # a name collision with an unrelated source is not provenance.
            skill.provenance = {"level": "unknown"}
            continue
        name_matches = by_name.get(basename) or (
            by_name.get(skill.name) if skill.name else None
        )
        if name_matches:
            chosen = name_matches[0]
            skill.provenance = {
                "level": "modified-copy",
                "skill_id": chosen.skill_id,
                "source_id": chosen.source_id,
                "detail": "name matches a source skill but content differs",
            }
            continue
        skill.provenance = {"level": "unknown"}
