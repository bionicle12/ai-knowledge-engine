#!/usr/bin/env python3
"""kb_save_session - save a chat/session summary into interactions/sessions/.

Layout (07_INTERACTION_LOOP.md, "Layout in interactions/sessions/"): one
folder per dialogue, one timestamped file per save::

    interactions/sessions/2026-05-06__competitor-analysis/
        2026-05-06T10-30__initial-findings.md
        2026-05-06T12-00__final-summary.md

An existing file is never overwritten: a second save in the same minute gets
``.v02`` before ``.md`` (then ``.v03``, ...). ``.md`` < ``.v02.md`` both
byte-wise and in locale collations that skip punctuation (``m`` < ``v``), so
a sorted listing keeps the order of the saves.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

SESSIONS_REL = Path("interactions") / "sessions"
_DIALOGUE_DIR_RE = re.compile(r"\d{4}-\d{2}-\d{2}__[a-z0-9][a-z0-9-]*")


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


class SessionPathError(ValueError):
    """The dialogue folder would lead outside ``interactions/sessions/``."""


def dialogue_dir(sessions_dir: Path, dialogue: str, day: _dt.date) -> Path:
    """Folder of one dialogue under ``interactions/sessions/``.

    An existing folder name (``2026-05-06__competitor-analysis``) is reused
    as is; anything else becomes ``<day>__<slug>``. Whichever it is, a
    folder that already exists (or is a symlink) must stay inside
    ``sessions_dir`` after following links, else :class:`SessionPathError`.
    """
    name = dialogue.strip()
    if (
        name
        and Path(name).name == name
        and name not in (".", "..")
        and (_DIALOGUE_DIR_RE.fullmatch(name) or (sessions_dir / name).is_dir())
    ):
        folder = sessions_dir / name
    else:
        folder = sessions_dir / f"{day.isoformat()}__{kbc.slugify(name)}"
    if (folder.exists() or folder.is_symlink()) and kbc.resolve_under(
        sessions_dir, folder
    ) is None:
        raise SessionPathError(
            f"{folder} points outside {sessions_dir}; remove the link "
            "or pass another --session"
        )
    return folder


def _write_new_file(folder: Path, stem: str, text: str) -> Path:
    """Create ``<stem>.md`` (or ``<stem>.v02.md``, ...) without replacing a file."""
    n = 1
    while True:
        target = folder / (f"{stem}.md" if n == 1 else f"{stem}.v{n:02d}.md")
        try:
            fh = target.open("x", encoding="utf-8", newline="\n")
        except FileExistsError:
            n += 1
            continue
        try:
            with fh:
                fh.write(text)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target


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
    session: str | None = None,
    now: _dt.datetime | None = None,
) -> Path:
    cfg = kbc.load_config(root)
    stamp = (now or _dt.datetime.now()).astimezone().replace(microsecond=0)
    today = stamp.date()
    sessions_dir = root / SESSIONS_REL
    folder = dialogue_dir(sessions_dir, session or title, today)
    folder.mkdir(parents=True, exist_ok=True)

    meta = {
        "title": title,
        "source": source,
        "saved_at": stamp.isoformat(),
        "session_date": today.isoformat(),
        "language": cfg.primary_language,
        # Nothing here redacts: the flag tells the reader a redaction pass
        # is still owed (privacy.require_redaction_for_chats).
        "redaction_required": cfg.privacy_require_redaction_for_chats,
        "meta_reviewed": False,
        "tags": tags,
    }
    body = _build_body(
        summary=summary,
        decisions=decisions,
        processed=processed,
        open_questions=open_questions,
    )
    stem = f"{stamp:%Y-%m-%dT%H-%M}__{kbc.slugify(title)}"
    target = _write_new_file(folder, stem, kbc.render_frontmatter(meta, body))
    kbc.append_log(
        operation="session-capture",
        title=title,
        details=[f"File: {target.relative_to(root).as_posix()}"],
        root=root,
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine - save a session summary"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument(
        "--session",
        default=None,
        help="Dialogue folder under interactions/sessions/: an existing folder "
        "name, or a topic that becomes <today>__<slug> (default: the title)",
    )
    parser.add_argument("--source", default="manual")
    parser.add_argument("--decision", action="append", default=[])
    parser.add_argument("--processed", action="append", default=[])
    parser.add_argument("--open-question", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    args = parser.parse_args(argv)

    root = (args.root or kbc.find_kb_root()).resolve()
    if not kbc.kb_config_path(root).is_file():
        print(
            f"❌ {root} is not a knowledge base (no {kbc.DEFAULT_CONFIG_FILENAME}); "
            "pass --root <base>",
            file=sys.stderr,
        )
        return 2
    try:
        target = save_session(
            root=root,
            title=args.title,
            summary=args.summary,
            decisions=args.decision,
            processed=args.processed,
            open_questions=args.open_question,
            tags=args.tag,
            source=args.source,
            session=args.session,
        )
    except SessionPathError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    print(f"Saved session summary to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
