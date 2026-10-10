#!/usr/bin/env python3
"""sync_translations — bump source_commit in i18n/<lang>/ files.

When the canonical EN sources change but the translations have already been
updated to match (or are confirmed still accurate), the recorded
`source_commit` in each translation's frontmatter falls behind. This script
re-stamps `source_commit` — and, on the files where it moves, `source_version`
and `translated_at` — to record that the translations are verified against
the current EN text.

Use this *after* you have manually verified that translations are in sync.
The script does NOT translate anything; it only updates metadata, and only
inside the leading frontmatter block (the body is never touched; a key that
is not in the frontmatter is left out).

Which commit to stamp
---------------------
`check_translations.py` compares the EN source as it is now with its text at
the recorded `source_commit`. `--to-source` stamps, per file, the commit that
last touched that EN source (resolved from `translation_of:`), so the history
shows which revision the translation follows; a file whose source has
uncommitted edits is skipped — commit the EN change first. A recorded sha is
kept when the source changed since then only in ways the checker ignores
(line endings, a badge version), so a release bump never re-dates an
untouched translation. `--to-commit` takes one explicit revision for the whole
batch; `--to-head` is the same with HEAD.

What gets stamped
-----------------
- `source_commit` — only with `--to-source`, `--to-commit` or `--to-head`.
- `source_version` / `translated_at` — the explicit `--to-version` /
  `--to-date` on every target; otherwise the repo VERSION / today, and only
  on files whose `source_commit` this run changes. Without any `--to-*` flag
  the script stamps nothing and exits 1.
- A key the file's frontmatter lacks is never added: the file's line says
  which keys are missing (add them by hand).

Usage:
    python3 scripts/sync_translations.py --to-source          # per-file source commit (usual)
    python3 scripts/sync_translations.py --to-source --lang ru
    python3 scripts/sync_translations.py --to-commit e497375  # one explicit revision
    python3 scripts/sync_translations.py --to-head            # use current HEAD sha
    python3 scripts/sync_translations.py --to-version 0.7.0
    python3 scripts/sync_translations.py --to-source --files i18n/ru/README.md i18n/ru/knowledge-base/00_OVERVIEW.md
    python3 scripts/sync_translations.py --to-source --dry-run

Exit codes:
    0 — files updated (or none needed)
    1 — error (unknown revision, bad --to-date, nothing to stamp)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

import check_translations as ct

REPO_ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = REPO_ROOT / "i18n"
VERSION_FILE = REPO_ROOT / "VERSION"


def _git(*args: str) -> str | None:
    """Run git in the repo. None when git is absent or the command fails."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def head_sha() -> str:
    return _git("rev-parse", "HEAD") or ""


def resolve_rev(rev: str) -> str | None:
    """Full sha for any revision (sha, tag, HEAD~2). None if git cannot."""
    return _git("rev-parse", "--verify", f"{rev}^{{commit}}")


def source_commit_for(translation: Path, text: str) -> tuple[str | None, str]:
    """Commit that last touched this file's EN source.

    Returns ``(sha, note)``; ``sha`` is None when the source cannot be
    resolved (or has uncommitted edits the stamp would not cover), and
    ``note`` says why so the caller can report it.
    """
    source_rel = ct.parse_frontmatter(text).get("translation_of", "")
    if not source_rel:
        return None, "no translation_of in frontmatter"
    source = REPO_ROOT / source_rel
    if not source.is_file():
        return None, f"source not found: {source_rel}"
    sha = _git("log", "-n", "1", "--format=%H", "--", str(source))
    if not sha:
        return None, f"no git history for {source_rel}"
    if _git("diff", "--quiet", "HEAD", "--", str(source)) is None:
        return None, f"{source_rel} has uncommitted edits; commit it first"
    return sha, ""


def recorded_without_drift(text: str, sha: str) -> str | None:
    """The recorded ``source_commit`` when the EN source differs between it
    and *sha* only in ways check_translations ignores (line endings, a badge
    version); else None. A release bump then never re-dates a translation."""
    fm = ct.parse_frontmatter(text)
    recorded = str(fm.get("source_commit", "")).strip()
    source_rel = fm.get("translation_of", "")
    if recorded == sha or not source_rel or not ct._SHA_RE.fullmatch(recorded):
        return None
    before = _drift_text_at(recorded, source_rel)
    if before is None or before != _drift_text_at(sha, source_rel):
        return None
    return recorded


def _drift_text_at(commit: str, source_rel: str) -> str | None:
    """The source at *commit* as the checker compares it; None if absent."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:./{source_rel}"],
            capture_output=True,
            cwd=str(REPO_ROOT),
            check=False,
        )
    except OSError:
        return None
    return ct.drift_text(result.stdout) if result.returncode == 0 else None


def repo_version() -> str | None:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text(encoding="utf-8").strip() or None
    return None


def patch_field(text: str, key: str, value: str) -> tuple[str, bool]:
    """Set top-level `key` inside the leading frontmatter; never the body.

    Returns ``(text, found)``. No frontmatter or no such key → text unchanged.
    An empty value is filled in; a trailing ``# comment`` is kept.
    """
    span = ct.frontmatter_span(text)
    if span is None:
        return text, False
    start, end = span
    block = text[start:end]
    m = re.search(rf"^{re.escape(key)}:(?P<rest>[^\r\n]*)", block, re.MULTILINE)
    if not m:
        return text, False
    comment = re.search(r"[ \t]+#.*$", m.group("rest"))
    line = f"{key}: {value}{comment.group(0) if comment else ''}"
    block = block[:m.start()] + line + block[m.end():]
    return text[:start] + block + text[end:], True


def collect_files(args) -> list[Path]:
    if args.files:
        return [REPO_ROOT / f for f in args.files]
    if not I18N_DIR.is_dir():
        return []
    out: list[Path] = []
    for lang_dir in sorted(I18N_DIR.iterdir()):
        if not lang_dir.is_dir():
            continue
        if args.lang and lang_dir.name != args.lang:
            continue
        for p in lang_dir.rglob("*.md"):
            if p.name == "TRANSLATION_STATUS.md":
                continue
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bump translation frontmatter")
    parser.add_argument("--lang", help="Only this language (e.g., ru)")
    parser.add_argument("--files", nargs="+", help="Specific relative paths")
    commit_source = parser.add_mutually_exclusive_group()
    commit_source.add_argument(
        "--to-source", action="store_true",
        help="Set source_commit per file to the commit that last touched its "
             "EN source (skips a source with uncommitted edits)")
    commit_source.add_argument(
        "--to-commit", metavar="REV",
        help="Set source_commit to this revision (sha, tag, HEAD~2)")
    commit_source.add_argument(
        "--to-head", action="store_true",
        help="Set source_commit to current HEAD")
    parser.add_argument(
        "--to-version",
        help="Set source_version on every target (default: repo VERSION, "
             "only where source_commit changes)")
    parser.add_argument(
        "--to-date",
        help="Set translated_at on every target, YYYY-MM-DD (default: today, "
             "only where source_commit changes)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    stamps_commit = bool(args.to_source or args.to_commit or args.to_head)
    if not (stamps_commit or args.to_version or args.to_date):
        print("[ERROR] nothing to stamp: pass --to-source (the usual choice), "
              "--to-commit, --to-head, --to-version or --to-date",
              file=sys.stderr)
        return 1
    if args.to_date:
        try:
            _dt.date.fromisoformat(args.to_date)
        except ValueError:
            print(f"[ERROR] --to-date is not a YYYY-MM-DD date: {args.to_date}",
                  file=sys.stderr)
            return 1

    new_commit = None
    if args.to_head:
        new_commit = head_sha()
        if not new_commit:
            print("[ERROR] no HEAD commit (not a git checkout?)", file=sys.stderr)
            return 1
    elif args.to_commit:
        new_commit = resolve_rev(args.to_commit)
        if not new_commit:
            print(f"[ERROR] not a revision in this repo: {args.to_commit}",
                  file=sys.stderr)
            return 1
    default_version = repo_version()
    default_date = _dt.date.today().isoformat()

    files = collect_files(args)
    if not files:
        print("No translation files found.")
        return 0

    print(f"Targets: {len(files)} files")
    if new_commit:
        print(f"  source_commit → {new_commit[:8]}...")
    elif args.to_source:
        print("  source_commit → per file, from translation_of")
    moved = "where source_commit changes"
    if args.to_version:
        print(f"  source_version → {args.to_version}")
    elif stamps_commit and default_version:
        print(f"  source_version → {default_version} ({moved})")
    if args.to_date:
        print(f"  translated_at  → {args.to_date}")
    elif stamps_commit:
        print(f"  translated_at  → {default_date} ({moved})")
    print()

    i18n_root = I18N_DIR.resolve()
    changed = 0
    for p in files:
        shown = p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p
        if not p.is_file():
            print(f"SKIP {shown} (not found)")
            continue
        if not p.resolve().is_relative_to(i18n_root):
            print(f"SKIP {shown} (not under i18n/)")
            continue
        # bytes in/out: CRLF files keep their line endings
        text = p.read_bytes().decode("utf-8")
        original = text
        commit = new_commit
        note = ""
        if args.to_source:
            commit, note = source_commit_for(p, text)
            if commit is None:
                print(f"SKIP {shown} ({note})")
                continue
            kept = recorded_without_drift(text, commit)
            if kept:
                commit, note = kept, "no drift since source_commit"
        missing = []
        if commit:
            text, found = patch_field(text, "source_commit", commit)
            if not found:
                missing.append("source_commit")
        restamped = text != original
        version = args.to_version or (default_version if restamped else None)
        date = args.to_date or (default_date if restamped else None)
        for key, value in (("source_version", version), ("translated_at", date)):
            if value:
                text, found = patch_field(text, key, value)
                if not found:
                    missing.append(key)
        notes = [note] if note else []
        if missing:
            notes.append(f"no {', '.join(missing)} in the frontmatter; add by hand")
        suffix = f" ({'; '.join(notes)})" if notes else ""
        if text == original:
            print(f"NOOP {shown}{suffix}")
            continue
        changed += 1
        if args.dry_run:
            print(f"WOULD {shown}{suffix}")
        else:
            p.write_bytes(text.encode("utf-8"))
            print(f"OK   {shown}{suffix}")

    if args.dry_run:
        print(f"\nDry-run: would update {changed} file(s)")
    else:
        print(f"\nUpdated {changed} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
