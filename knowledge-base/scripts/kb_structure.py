#!/usr/bin/env python3
"""kb_structure — four init-time structure sketches + blind-spot list.

No LLM. Reads a role YAML and emits four radically different
``knowledge/`` layouts (projects / artifacts / time / decisions) plus
the blind-spot interview order. The agent shows the sketches; the owner
reacts. See ``02_INIT.md`` (iteration E).

Usage:
    python3 scripts/kb_structure.py --role fiction-writer --dry-run
    python3 scripts/kb_structure.py --role fiction-writer --write --kb-root .
    python3 scripts/kb_structure.py --role fiction-writer --json
    python3 scripts/kb_structure.py --role fiction-writer --blind-spots
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_populate  # noqa: E402

AXES = ("projects", "artifacts", "time", "decisions")
OUTPUT_REL = Path("interactions") / "init" / "STRUCTURE_VARIANTS.md"


def _safe(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def enabled_entities(role_data: dict[str, Any]) -> list[dict[str, Any]]:
    entities = role_data.get("entities") or {}
    if not isinstance(entities, dict):
        return []
    out: list[dict[str, Any]] = []
    for key, spec in entities.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("enabled", True) is False:
            continue
        paths = [
            _safe(p)
            for p in (spec.get("knowledge_paths") or [])
            if _safe(p)
        ]
        out.append(
            {
                "key": str(key),
                "why": _safe(spec.get("why")),
                "paths": paths,
            }
        )
    return out


def artifacts(role_data: dict[str, Any]) -> list[dict[str, str]]:
    pe = role_data.get("placement_examples") or {}
    if not isinstance(pe, dict):
        return []
    rows = pe.get("by_artifact") or []
    out: list[dict[str, str]] = []
    if not isinstance(rows, list):
        return out
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        name = _safe(entry.get("artifact"))
        if not name:
            continue
        out.append(
            {
                "artifact": name,
                "destination": _safe(entry.get("destination")),
                "knowledge_target": _safe(entry.get("knowledge_target")),
            }
        )
    return out


def _normalize_blind_spots(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            text = _safe(item.get("ask") or item.get("text") or item.get("q"))
            if text:
                out.append(text)
    return out


def default_blind_spots(role_data: dict[str, Any]) -> list[str]:
    """Structure-changing questions first; content gaps after."""
    role = _safe(role_data.get("role")) or "this role"
    ents = [e["key"].replace("_", " ") for e in enabled_entities(role_data)]
    entity_hint = ", ".join(ents[:4]) if ents else "the usual role entities"
    arts = [a["artifact"] for a in artifacts(role_data)]
    art_hint = arts[0] if arts else "incoming files"
    return [
        f"Where do paused or abandoned {role} efforts live so they do not mix with current work? (changes knowledge/ layout)",
        f"Does each kind of artefact ({art_hint}) earn its own knowledge/ folder, or does everything stay in raw/ until promoted?",
        "How should something from two years ago be found — by date, by project, or by the decision it produced? (changes knowledge/ layout)",
        "Which records must stay immutable (log-style) versus pages you expect to edit?",
        f"What do people in the {role} role usually forget to capture until it is already gone? (think: {entity_hint})",
        "What would be expensive if the AI invented it because the base is silent?",
    ]


def blind_spots(role_data: dict[str, Any]) -> list[str]:
    custom = _normalize_blind_spots(role_data.get("blind_spots"))
    return custom or default_blind_spots(role_data)


def _entity_slugs(ents: list[dict[str, Any]], limit: int = 5) -> list[str]:
    return [e["key"].replace("_", "-") for e in ents[:limit]]


def _tree(lines: list[str]) -> str:
    return "\n".join(lines)


def variants(role_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Four sketches. Owner reacts; they do not pick a number from a form."""
    role = _safe(role_data.get("role")) or "this role"
    ents = enabled_entities(role_data)
    slugs = _entity_slugs(ents)
    arts = artifacts(role_data)
    art_dirs = []
    for art in arts[:6]:
        target = art["knowledge_target"] or "knowledge/domain/"
        folder = target.rstrip("/")
        if folder.startswith("knowledge/"):
            folder = folder[len("knowledge/") :]
        art_dirs.append(folder.split("/")[0] or "domain")
    if not art_dirs:
        art_dirs = ["drafts", "references", "notes"]
    # de-dupe, keep order
    seen: set[str] = set()
    art_unique: list[str] = []
    for name in art_dirs:
        if name not in seen:
            seen.add(name)
            art_unique.append(name)

    project_children = slugs or ["current", "parked"]
    return [
        {
            "id": "projects",
            "axis": "projects",
            "title": "By project",
            "who": f"Fits {role} work that is already organized as named efforts.",
            "loses": "Harder to find a craft rule or a voice note that is not tied to one project.",
            "folders": [
                "knowledge/projects/<slug>/",
                "knowledge/_shared/profile/",
                "knowledge/_shared/principles/",
                "knowledge/_shared/voice/",
                "knowledge/decisions/",
            ],
            "tree": _tree(
                [
                    "knowledge/",
                    "  projects/",
                    *[f"    {slug}/" for slug in project_children],
                    "  _shared/",
                    "    profile/",
                    "    principles/",
                    "    voice/",
                    "  decisions/          # only cross-project ADRs",
                    "  open-questions/",
                ]
            ),
        },
        {
            "id": "artifacts",
            "axis": "artifacts",
            "title": "By artefact type",
            "who": "Fits a drop-box workflow: each incoming type has a forever home.",
            "loses": "A single project is split across many folders; timelines are weak.",
            "folders": [f"knowledge/{name}/" for name in art_unique]
            + ["knowledge/profile/"],
            "tree": _tree(
                [
                    "knowledge/",
                    *[f"  {name}/" for name in art_unique],
                    "  profile/",
                    "  _inbox-promoted/",
                ]
            ),
        },
        {
            "id": "time",
            "axis": "time",
            "title": "By time",
            "who": "Fits a journal / season / cohort rhythm.",
            "loses": "Same project across years is split; decisions hide inside dated folders.",
            "folders": [
                "knowledge/current/",
                "knowledge/timelines/",
                "knowledge/profile/",
                "knowledge/_archive/",
            ],
            "tree": _tree(
                [
                    "knowledge/",
                    "  current/            # this season only",
                    "  timelines/",
                    "    2026/",
                    "    2025/",
                    "  profile/            # permanent",
                    "  principles/         # permanent",
                    "  _archive/",
                ]
            ),
        },
        {
            "id": "decisions",
            "axis": "decisions",
            "title": "By decision",
            "who": "Fits a role where the valuable residue is 'what we chose and why'.",
            "loses": "Drafts and references have no natural shelf until they attach to a decision.",
            "folders": [
                "knowledge/decisions/",
                "knowledge/consequences/",
                "knowledge/profile/",
                "knowledge/principles/",
            ],
            "tree": _tree(
                [
                    "knowledge/",
                    "  decisions/",
                    "    2026-08__example.md",
                    "  consequences/       # what followed",
                    "  profile/",
                    "  principles/",
                    "  open-questions/",
                ]
            ),
        },
    ]


def render_markdown(role_data: dict[str, Any], *, source_path: Path) -> str:
    role = _safe(role_data.get("role")) or "Unknown role"
    spots = blind_spots(role_data)
    sketches = variants(role_data)
    lines = [
        f"# Structure variants — {role}",
        "",
        f"Generated from `{source_path.name}` by `kb_structure.py`.",
        "Not indexed. The owner **reacts** (likes, dislikes, hybrids) —",
        "they do not pick a number from a form.",
        "",
        "Stock 12-folder tree in `KNOWLEDGE_STRUCTURE.md` is the hybrid",
        "default if the reaction is \"a bit of everything\" or \"as is\".",
        "",
        "## Blind spots (ask in this order, before proposing folders)",
        "",
    ]
    for i, spot in enumerate(spots, 1):
        lines.append(f"{i}. {spot}")
    lines.extend(["", "## Four sketches", ""])
    for sketch in sketches:
        lines.extend(
            [
                f"### {sketch['title']} (`{sketch['id']}`)",
                "",
                sketch["who"],
                "",
                f"Loses: {sketch['loses']}",
                "",
                "```",
                sketch["tree"],
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## After the owner reacts",
            "",
            "1. Create the folders the reaction needs (stock dirs may stay",
            "   as empty compatibility shelves — `kb_ingest.py --init-dirs`).",
            "2. Write `KNOWLEDGE_STRUCTURE.md` to match the reaction, not",
            "   the unused sketches.",
            "3. Leave this file in `interactions/init/` as the init record.",
            "",
        ]
    )
    return "\n".join(lines)


def write_variants(kb_root: Path, role_data: dict[str, Any], *, source_path: Path) -> Path:
    dest = kb_root / OUTPUT_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_markdown(role_data, source_path=source_path), encoding="utf-8")
    return dest


def payload(role_data: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    return {
        "role": _safe(role_data.get("role")),
        "source": source_path.as_posix(),
        "blind_spots": blind_spots(role_data),
        "variants": variants(role_data),
        "axes": list(AXES),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Four structure sketches + blind-spot list from a role YAML"
    )
    parser.add_argument("--role", help="Role name (matches examples/<role>.yml)")
    parser.add_argument("--from", dest="from_path", type=Path, help="Path to a custom role YAML")
    parser.add_argument("--kb-root", type=Path, help="Deployed KB root (defaults to cwd)")
    parser.add_argument("--write", action="store_true", help=f"Write {OUTPUT_REL}")
    parser.add_argument("--dry-run", action="store_true", help="Print markdown to stdout")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--blind-spots",
        action="store_true",
        dest="blind_spots_only",
        help="Print only the interview questions, one per line",
    )
    args = parser.parse_args(argv)

    if not args.role and not args.from_path:
        parser.error("Either --role or --from must be specified")
        return 1

    try:
        role_path = kb_populate.resolve_role_path(args.role, args.from_path)
        role_data = kb_populate.load_role_yaml(role_path)
    except (FileNotFoundError, ValueError, SystemExit) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    if role_data.get("easter_egg"):
        print("This role is an easter egg — pick another.", file=sys.stderr)
        return 1

    data = payload(role_data, source_path=role_path)

    if args.blind_spots_only:
        for spot in data["blind_spots"]:
            print(spot)
        return 0

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    text = render_markdown(role_data, source_path=role_path)
    if args.write:
        root = args.kb_root or Path.cwd()
        dest = write_variants(root, role_data, source_path=role_path)
        print(f"Wrote {dest}")
        return 0

    if args.dry_run or not args.write:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
