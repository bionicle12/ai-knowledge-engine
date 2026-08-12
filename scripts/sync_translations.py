#!/usr/bin/env python3
"""sync_translations — bump source_commit in i18n/<lang>/ files.

When the canonical EN files in `knowledge-base/` change but the translations
have already been updated to match (or are confirmed still accurate), the
recorded `source_commit` in each translation's frontmatter falls behind the
actual git history. This script bumps `source_commit` (and optionally
`source_version` / `translated_at`) to reflect that the translations are
verified against the current state.

Use this *after* you have manually verified that translations are in sync.
The script does NOT translate anything; it only updates metadata.

Usage:
    python3 scripts/sync_translations.py                      # all i18n langs
    python3 scripts/sync_translations.py --lang ru
    python3 scripts/sync_translations.py --to-head            # use current HEAD sha
    python3 scripts/sync_translations.py --to-version 0.7.0
    python3 scripts/sync_translations.py --files i18n/ru/README.md i18n/ru/knowledge-base/00_OVERVIEW.md
    python3 scripts/sync_translations.py --dry-run

Exit codes:
    0 — files updated (or none needed)
    1 — error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = REPO_ROOT / "i18n"
VERSION_FILE = REPO_ROOT / "VERSION"


def head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def repo_version() -> str:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text().strip()
    return "unknown"


def patch_field(text: str, key: str, value: str) -> tuple[str, bool]:
    pattern = re.compile(rf"^({re.escape(key)}:\s*)\S+", re.MULTILINE)
    new_text, count = pattern.subn(rf"\g<1>{value}", text, count=1)
    return new_text, count > 0


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
    parser.add_argument("--to-head", action="store_true",
                        help="Set source_commit to current HEAD")
    parser.add_argument("--to-version", help="Set source_version to this value")
    parser.add_argument("--to-date", help="Set translated_at (default: today)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

    new_commit = head_sha() if args.to_head else None
    new_version = args.to_version or repo_version()
    new_date = args.to_date or _dt.date.today().isoformat()

    files = collect_files(args)
    if not files:
        print("No translation files found.")
        return 0

    print(f"Targets: {len(files)} files")
    if new_commit:
        print(f"  source_commit → {new_commit[:8]}...")
    print(f"  source_version → {new_version}")
    print(f"  translated_at  → {new_date}")
    print()

    updated = 0
    for p in files:
        if not p.is_file():
            print(f"SKIP {p.relative_to(REPO_ROOT)} (not found)")
            continue
        text = p.read_text(encoding="utf-8")
        original = text
        if new_commit:
            text, _ = patch_field(text, "source_commit", new_commit)
        text, _ = patch_field(text, "source_version", new_version)
        text, _ = patch_field(text, "translated_at", new_date)
        if text == original:
            print(f"NOOP {p.relative_to(REPO_ROOT)}")
            continue
        if args.dry_run:
            print(f"WOULD {p.relative_to(REPO_ROOT)}")
        else:
            p.write_text(text, encoding="utf-8")
            print(f"OK   {p.relative_to(REPO_ROOT)}")
            updated += 1

    if args.dry_run:
        print(f"\nDry-run: would update {sum(1 for p in files if p.is_file())} files")
    else:
        print(f"\nUpdated {updated} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
