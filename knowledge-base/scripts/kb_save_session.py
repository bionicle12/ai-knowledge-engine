#!/usr/bin/env python3
"""kb_save_session - save a chat/session summary into interactions/sessions/."""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402


def _build_body(
    *,
    summary: str,
    decisions: list[str],
    processed: list[str],
    open_questions: list[str],
) -> str:
    lines = [
        "# Session Summary",
        "",
        "## Summary",
        "",
        summary.strip(),
        "",
    ]
    if decisions:
        lines.extend(["## Decisions", ""])
        lines.extend(f"- {item}" for item in decisions)
        lines.append("")
    if processed:
        lines.extend(["## Processed Materials", ""])
        lines.extend(f"- {item}" for item in processed)
        lines.append("")
    if open_questions:
        lines.extend(["## Open Questions", ""])
        lines.extend(f"- {item}" for item in open_questions)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def save_session(
    *,
    root: Path,
    title: str,
    summary: str,
    decisions: list[str],
    processed: list[str],
    open_questions: list[str],
    tags: list[str],
    source: str,
) -> Path:
    cfg = kbc.load_config(root)
    session_dir = root / "interactions" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)

    today = _dt.date.today()
    filename = kbc.stable_filename(original_name=title, date=today, ext=".md")
    target = session_dir / filename

    meta = {
        "title": title,
        "source": source,
        "saved_at": kbc.now_iso(),
        "session_date": today.isoformat(),
        "language": cfg.primary_language,
        "redacted": bool(cfg.raw.get("privacy", {}).get("require_redaction_for_chats", False)),
        "tags": tags,
    }
    body = _build_body(
        summary=summary,
        decisions=decisions,
        processed=processed,
        open_questions=open_questions,
    )
    kbc.write_frontmatter_file(target, meta, body)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine - save a session summary"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--source", default="manual")
    parser.add_argument("--decision", action="append", default=[])
    parser.add_argument("--processed", action="append", default=[])
    parser.add_argument("--open-question", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    args = parser.parse_args(argv)

    root = args.root or kbc.find_kb_root()
    target = save_session(
        root=root,
        title=args.title,
        summary=args.summary,
        decisions=args.decision,
        processed=args.processed,
        open_questions=args.open_question,
        tags=args.tag,
        source=args.source,
    )
    print(f"Saved session summary to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
