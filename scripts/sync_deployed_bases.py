#!/usr/bin/env python3
"""sync_deployed_bases — bring already-deployed knowledge bases up to date.

This is a one-shot maintenance helper for **already finalized** knowledge bases
(the flat layout: scripts/, shell/, kb.config.yml, AGENTS.md, … at the base
root). It is safe and idempotent: it only touches the mechanical layer
(reference scripts + launchers) and additively patches kb.config.yml. It never
touches knowledge/, raw/, assets/, processed/, review/, examples/, or any
role-specific content.

What it does per base:
  1. Copies the canonical reference scripts (knowledge-base/scripts/kb_*.py)
     into <base>/scripts/, adding the new ones (kb_stt, kb_ocr, kb_reindex).
  2. Copies requirements-media.txt into the base root.
  3. Adds a `media:` section to kb.config.yml if missing (STT/OCR/archives).
  4. Bumps `instructions_version` to the repo VERSION.
  5. Refreshes reindex.bat (now delegates to kb_reindex.py on Windows).

Usage:
  python3 scripts/sync_deployed_bases.py <target-root> [--dry-run]
  python3 scripts/sync_deployed_bases.py            # defaults to the path below
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_SCRIPTS = REPO_ROOT / "knowledge-base" / "scripts"
SRC_TEMPLATES = REPO_ROOT / "knowledge-base" / "templates"
SRC_SHELL = REPO_ROOT / "knowledge-base" / "shell"
VERSION_FILE = REPO_ROOT / "VERSION"

DEFAULT_TARGET = Path(r"C:\OSPanel\domains\main\brain-my-ai")

MEDIA_BLOCK = """\
# Media processing — transcription (STT), OCR, archive unpacking.
# Added by sync_deployed_bases. Requires: pip install -r requirements-media.txt
media:
  stt:
    enabled: true
    backends: ["faster-whisper", "openai-whisper"]
    model: "small"
    language: "auto"
    device: "auto"
    compute_type: "int8"
    timestamps: true
    allow_cloud: false
  ocr:
    enabled: true
    backends: ["rapidocr", "tesseract"]
    language: "auto"
  archives:
    enabled: true
    max_files: 200

"""


def repo_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.is_file() else "0.0.0"


def find_bases(target_root: Path) -> list[Path]:
    """Every immediate subdirectory that contains a kb.config.yml."""
    bases: list[Path] = []
    if (target_root / "kb.config.yml").is_file():
        bases.append(target_root)
    for child in sorted(target_root.iterdir()):
        if child.is_dir() and (child / "kb.config.yml").is_file():
            bases.append(child)
    return bases


def sync_scripts(base: Path, *, dry_run: bool) -> list[str]:
    notes: list[str] = []
    dst_dir = base / "scripts"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(SRC_SCRIPTS.glob("kb_*.py")):
        dst = dst_dir / src.name
        existed = dst.is_file()
        same = existed and dst.read_bytes() == src.read_bytes()
        if same:
            continue
        action = "update" if existed else "add"
        if not dry_run:
            shutil.copy2(src, dst)
        notes.append(f"  scripts/{src.name}: {action}")
    return notes


def sync_requirements_media(base: Path, *, dry_run: bool) -> list[str]:
    src = SRC_TEMPLATES / "requirements-media.txt"
    if not src.is_file():
        return []
    dst = base / "requirements-media.txt"
    existed = dst.is_file()
    same = existed and dst.read_bytes() == src.read_bytes()
    if same:
        return []
    if not dry_run:
        shutil.copy2(src, dst)
    return [f"  requirements-media.txt: {'update' if existed else 'add'}"]


def sync_reindex_bat(base: Path, *, dry_run: bool) -> list[str]:
    src = SRC_SHELL / "reindex.bat"
    dst = base / "reindex.bat"
    if not src.is_file() or not dst.is_file():
        return []
    if dst.read_bytes() == src.read_bytes():
        return []
    if not dry_run:
        shutil.copy2(src, dst)
    return ["  reindex.bat: update (delegates to kb_reindex.py)"]


def patch_config(base: Path, version: str, *, dry_run: bool) -> list[str]:
    notes: list[str] = []
    cfg = base / "kb.config.yml"
    if not cfg.is_file():
        return notes
    text = cfg.read_text(encoding="utf-8")
    original = text

    # 1) bump instructions_version
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.lstrip().startswith("instructions_version:"):
            indent = line[: len(line) - len(line.lstrip())]
            new_line = f'{indent}instructions_version: "{version}"\n'
            if line != new_line:
                lines[i] = new_line
                notes.append(f"  kb.config.yml: instructions_version -> {version}")
            break
    text = "".join(lines)

    # 2) insert media: block before the autorun: section if not present
    if "\nmedia:" not in ("\n" + text) and not text.startswith("media:"):
        lines = text.splitlines(keepends=True)
        out: list[str] = []
        inserted = False
        for line in lines:
            if not inserted and line.startswith("autorun:"):
                out.append(MEDIA_BLOCK)
                inserted = True
            out.append(line)
        if not inserted:
            # no autorun anchor — append at end
            if not text.endswith("\n"):
                out.append("\n")
            out.append("\n" + MEDIA_BLOCK)
            inserted = True
        text = "".join(out)
        notes.append("  kb.config.yml: added media: section")

    if text != original and not dry_run:
        cfg.write_text(text, encoding="utf-8")
    return notes


def sync_base(base: Path, version: str, *, dry_run: bool) -> None:
    print(f"\n=== {base.name} ===")
    notes: list[str] = []
    notes += sync_scripts(base, dry_run=dry_run)
    notes += sync_requirements_media(base, dry_run=dry_run)
    notes += sync_reindex_bat(base, dry_run=dry_run)
    notes += patch_config(base, version, dry_run=dry_run)
    if notes:
        for n in notes:
            print(n)
    else:
        print("  already up to date")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync deployed knowledge bases to the latest engine")
    parser.add_argument("target", nargs="?", type=Path, default=DEFAULT_TARGET,
                        help="Folder containing one or more deployed bases")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    target: Path = args.target
    if not target.is_dir():
        print(f"target not found: {target}", file=sys.stderr)
        return 2

    version = repo_version()
    bases = find_bases(target)
    if not bases:
        print(f"no deployed bases (kb.config.yml) found under {target}", file=sys.stderr)
        return 2

    print(f"Repo version: {version}")
    print(f"Target:       {target}")
    print(f"Bases found:  {len(bases)} ({', '.join(b.name for b in bases)})")
    if args.dry_run:
        print("(dry-run: no files will be written)")

    for base in bases:
        sync_base(base, version, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
