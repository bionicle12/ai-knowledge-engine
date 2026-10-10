#!/usr/bin/env python3
"""Generate deterministic navigation pages for knowledge sections.

Creates or refreshes:
  * ``knowledge/routing/<section>.md`` for each non-empty top-level section
  * an auto-managed routing block inside ``knowledge/routing-table.md``

Manual content outside the managed root-table block is preserved. Pages are
rewritten only when their content changes (dates and access counters stay
put otherwise), so a reindex that changes nothing writes nothing — the
watcher does not see its own writes as edits.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

GENERATOR = "kb_route.py"
AUTOGEN_BEGIN = "<!-- AUTO-ROUTING:BEGIN -->"
AUTOGEN_END = "<!-- AUTO-ROUTING:END -->"
SKIP_SECTIONS = {"routing", "_archive"}
SECTION_ORDER = tuple(
    section for section in kbc.KNOWLEDGE_DIRS if section not in SKIP_SECTIONS
)
SECTION_DESCRIPTIONS = {
    "profile": "role and operating context",
    "principles": "durable decision and working principles",
    "voice": "messaging and tone rules",
    "domain": "market, product, and strategic knowledge",
    "projects": "active project context, roadmap, and validation",
    "decisions": "decision records and historical choices",
    "playbooks": "repeatable processes and operating recipes",
    "insights": "higher-level synthesis pages",
    "opinions": "subjective takes worth preserving",
    "timelines": "time-based snapshots and chronology",
    "open-questions": "unresolved questions and research gaps",
}


@dataclass(frozen=True)
class PageEntry:
    path: Path
    target: str
    title: str
    subgroup: str | None


def _today() -> str:
    return dt.date.today().isoformat()


def _label(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").title()


def _knowledge_pages(root: Path) -> list[Path]:
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return []
    pages: list[Path] = []
    for page in sorted(knowledge.rglob("*.md")):
        rel = page.relative_to(knowledge)
        if rel.name == "routing-table.md":
            continue
        if rel.parts and rel.parts[0] in SKIP_SECTIONS:
            continue
        if kbc.is_archived(rel.as_posix()):
            continue
        pages.append(page)
    return pages


def _page_title(page: Path) -> str:
    try:
        _meta, body = kbc.read_frontmatter_file(page)
    except OSError:
        return _label(page.stem)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return _label(page.stem)


def _group_pages(root: Path) -> dict[str, list[PageEntry]]:
    knowledge = root / "knowledge"
    grouped: dict[str, list[PageEntry]] = defaultdict(list)
    for page in _knowledge_pages(root):
        rel = page.relative_to(knowledge)
        section = rel.parts[0] if len(rel.parts) > 1 else "_root"
        subgroup = rel.parts[1] if len(rel.parts) > 2 else None
        grouped[section].append(
            PageEntry(
                path=page,
                target=kbc.posix_relpath(
                    page,
                    knowledge,
                    without_suffix=True,
                ),
                title=_page_title(page),
                subgroup=subgroup,
            )
        )
    for entries in grouped.values():
        entries.sort(key=lambda item: item.target)
    return grouped


def _routing_meta(*, importance: int = 6) -> dict:
    today = _today()
    return {
        "source": f"system: {GENERATOR}",
        "generated_by": GENERATOR,
        "extracted_at": today,
        "last_verified": today,
        "confidence": "high",
        "verification_method": "deterministic-generator",
        "lifecycle": "evolving",
        "importance": importance,
        "valid_from": today,
        "valid_until": None,
        "last_accessed": today,
        "access_count": 0,
        "tags": ["routing", "navigation", "knowledge-base"],
        "supersedes": None,
    }


# Keys kb_route decides on its section pages. Everything else — the dates,
# access counters, keys an agent added — is kept from the existing page.
OWNED_KEYS = (
    "source",
    "generated_by",
    "confidence",
    "verification_method",
    "lifecycle",
    "importance",
    "valid_until",
    "tags",
    "supersedes",
)


def _write_section_page(page: Path, body: str) -> bool:
    """Write a generated section page only when its content changed (D9)."""
    fresh = _routing_meta()
    if not page.exists():
        return kbc.write_frontmatter_file(page, fresh, body)
    meta, old_body = kbc.read_frontmatter_file(page)
    if old_body.strip() == body.strip() and all(
        meta.get(key) == fresh[key] for key in OWNED_KEYS
    ):
        return False
    merged = dict(fresh)
    merged.update((key, value) for key, value in meta.items() if key not in OWNED_KEYS)
    merged["last_verified"] = fresh["last_verified"]
    return kbc.write_frontmatter_file(page, merged, body, only_if_changed=True)


def _render_section_page(section: str, entries: list[PageEntry]) -> str:
    lines = [
        f"# {_label(section)} Routing",
        "",
        f"Navigation for `knowledge/{section}/`.",
        "",
    ]
    ungrouped = [entry for entry in entries if not entry.subgroup]
    if ungrouped:
        lines.extend(["## Pages", ""])
        for entry in ungrouped:
            lines.append(f"- [[{entry.target}]] - {entry.title}")
        lines.append("")

    grouped: dict[str, list[PageEntry]] = defaultdict(list)
    for entry in entries:
        if entry.subgroup:
            grouped[entry.subgroup].append(entry)
    for subgroup in sorted(grouped):
        lines.extend([f"## {_label(subgroup)}", ""])
        for entry in grouped[subgroup]:
            lines.append(f"- [[{entry.target}]] - {entry.title}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_root_block(sections: list[str]) -> str:
    lines = [AUTOGEN_BEGIN, "## Section Routing", ""]
    for section in sections:
        description = SECTION_DESCRIPTIONS.get(section, "section overview")
        lines.append(f"- [[routing/{section}]] - {description}.")
    lines.extend(["", AUTOGEN_END])
    return "\n".join(lines)


def _upsert_root_table(root: Path, sections: list[str]) -> tuple[bool, str | None]:
    """Refresh the managed block of routing-table.md.

    Returns ``(written, warning)``. A page whose frontmatter does not parse is
    left alone: rewriting it would stack a second frontmatter on top.
    """
    root_table = root / "knowledge" / "routing-table.md"
    block = _render_root_block(sections)
    if root_table.exists():
        text, _encoding = kbc.read_text_auto(root_table)
        error = kbc.frontmatter_error(text)
        if error:
            return False, (
                f"{kbc.posix_relpath(root_table, root)} left unchanged: {error}; "
                "fix its frontmatter and rerun kb_route.py"
            )
        meta, body = kbc.parse_frontmatter(text)
    else:
        meta = _routing_meta(importance=8)
        body = "# Routing Table\n"

    if AUTOGEN_BEGIN in body and AUTOGEN_END in body:
        pattern = rf"{re.escape(AUTOGEN_BEGIN)}.*?{re.escape(AUTOGEN_END)}"
        new_body = re.sub(pattern, lambda _match: block, body, flags=re.S)
    else:
        new_body = body.rstrip() + "\n\n" + block + "\n"

    if root_table.exists() and new_body.strip() == body.strip() and meta.get("generated_by"):
        return False, None
    meta.setdefault("generated_by", GENERATOR)
    return kbc.write_frontmatter_file(
        root_table, meta, new_body.rstrip() + "\n", only_if_changed=True
    ), None


def _cleanup_stale_pages(root: Path, active_sections: set[str]) -> list[Path]:
    removed: list[Path] = []
    routing_dir = root / "knowledge" / "routing"
    if not routing_dir.is_dir():
        return removed
    for page in routing_dir.glob("*.md"):
        if page.stem in active_sections:
            continue
        try:
            meta, _body = kbc.read_frontmatter_file(page)
        except Exception:  # noqa: BLE001
            continue
        if meta.get("generated_by") != GENERATOR:
            continue
        page.unlink()
        removed.append(page)
    return removed


def generate_routes(root: Path) -> dict[str, Any]:
    grouped = _group_pages(root)
    ordered_sections = [
        section for section in SECTION_ORDER if grouped.get(section)
    ]
    ordered_sections.extend(
        sorted(section for section in grouped if section not in SECTION_ORDER)
    )

    routing_dir = root / "knowledge" / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    unchanged: list[str] = []
    for section in ordered_sections:
        page = routing_dir / f"{section}.md"
        changed = _write_section_page(page, _render_section_page(section, grouped[section]))
        (written if changed else unchanged).append(kbc.posix_relpath(page, root))

    removed = [
        kbc.posix_relpath(page, root)
        for page in _cleanup_stale_pages(root, set(ordered_sections))
    ]
    root_written, warning = _upsert_root_table(root, ordered_sections)
    return {
        "root_table": "knowledge/routing-table.md",
        "root_table_written": root_written,
        "written": written,
        "unchanged": unchanged,
        "removed": removed,
        "warnings": [warning] if warning else [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine - generate routing pages"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = (args.root or kbc.find_kb_root()).resolve()
    if not kbc.kb_config_path(root).is_file():
        kbc.print_err(
            f"❌ [route] {root} is not a knowledge base (no kb.config.yml); "
            "pass --root <base>"
        )
        return 2
    result = generate_routes(root)
    for warning in result["warnings"]:
        kbc.print_err(f"⚠️  [route] {warning}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        state = "updated" if result["root_table_written"] else "unchanged"
        print(f"{result['root_table']}: {state}")
        for page in result["written"]:
            print(f"- updated {page}")
        for page in result["removed"]:
            print(f"- removed {page}")
        if result["unchanged"]:
            print(f"- {len(result['unchanged'])} routing page(s) unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
