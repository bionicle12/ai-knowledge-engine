#!/usr/bin/env python3
"""Generate deterministic navigation pages for knowledge sections.

Creates or refreshes:
  * ``knowledge/routing/<section>.md`` for each non-empty top-level section
  * an auto-managed routing block inside ``knowledge/routing-table.md``

Manual content outside the managed root-table block is preserved.
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

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

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
        pages.append(page)
    return pages


def _page_title(page: Path) -> str:
    _meta, body = kbc.read_frontmatter_file(page)
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
        "source": "system: kb_route.py",
        "generated_by": "kb_route.py",
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


def _upsert_root_table(root: Path, sections: list[str]) -> Path:
    root_table = root / "knowledge" / "routing-table.md"
    if root_table.exists():
        meta, body = kbc.read_frontmatter_file(root_table)
    else:
        meta = _routing_meta(importance=8)
        body = "# Routing Table\n"

    block = _render_root_block(sections)
    if AUTOGEN_BEGIN in body and AUTOGEN_END in body:
        pattern = rf"{re.escape(AUTOGEN_BEGIN)}.*?{re.escape(AUTOGEN_END)}"
        body = re.sub(pattern, block, body, flags=re.S)
    else:
        body = body.rstrip() + "\n\n" + block + "\n"

    meta.setdefault("generated_by", "kb_route.py")
    kbc.write_frontmatter_file(root_table, meta, body.rstrip() + "\n")
    return root_table


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
        if meta.get("generated_by") != "kb_route.py":
            continue
        page.unlink()
        removed.append(page)
    return removed


def generate_routes(root: Path) -> dict[str, list[str] | str]:
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
    for section in ordered_sections:
        page = routing_dir / f"{section}.md"
        kbc.write_frontmatter_file(
            page,
            _routing_meta(),
            _render_section_page(section, grouped[section]),
        )
        written.append(kbc.posix_relpath(page, root))

    removed = [
        kbc.posix_relpath(page, root)
        for page in _cleanup_stale_pages(root, set(ordered_sections))
    ]
    root_table = _upsert_root_table(root, ordered_sections)
    return {
        "root_table": kbc.posix_relpath(root_table, root),
        "written": written,
        "removed": removed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine - generate routing pages"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    result = generate_routes(root)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Updated {result['root_table']}")
        for page in result["written"]:
            print(f"- {page}")
        for page in result["removed"]:
            print(f"- removed {page}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
