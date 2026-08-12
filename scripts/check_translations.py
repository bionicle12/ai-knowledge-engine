#!/usr/bin/env python3
"""check_translations — drift report for translated docs.

For every file under `i18n/<lang>/`, parses its `translation_of:` frontmatter
field and checks whether the source file in the repo has been modified since
the recorded `source_commit`. Emits status:

  ✅ in sync   — source has not changed since `source_commit`
  ⚠️ stale     — source changed; translation may need update
  ❌ missing   — translation is referenced in a config but does not exist yet
  ℹ️ orphan    — translation exists but `translation_of` target is missing

Usage:
    python3 scripts/check_translations.py
    python3 scripts/check_translations.py --update-status   # write i18n/TRANSLATION_STATUS.md
    python3 scripts/check_translations.py --json
    python3 scripts/check_translations.py --strict          # exit 1 if any drift
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = REPO_ROOT / "i18n"
STATUS_FILE = I18N_DIR / "TRANSLATION_STATUS.md"


def _enable_utf8_stdout() -> None:
    """Windows consoles default to a legacy codepage that cannot encode the
    status emoji; switch to UTF-8 where the runtime allows it."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class TranslationStatus:
    lang: str
    translation_path: str
    source_path: str
    source_commit: str = ""
    translated_at: str = ""
    translator: str = ""
    actual_source_commit: str = ""
    drift_commits: int = 0
    state: str = "unknown"   # in_sync | stale | missing | orphan
    note: str = ""


def parse_frontmatter(text: str) -> dict:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    out: dict = {}
    for line in block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def git_last_commit_for(path: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "log", "-n", "1", "--format=%H", "--", str(path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=False,
        )
    except FileNotFoundError:
        return None
    sha = result.stdout.strip()
    return sha or None


def git_count_commits_since(path: Path, since_sha: str) -> int | None:
    if not since_sha:
        return None
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"{since_sha}..HEAD", "--", str(path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return len([line for line in result.stdout.splitlines() if line.strip()])


def collect_translations(i18n_dir: Path) -> list[Path]:
    if not i18n_dir.is_dir():
        return []
    out: list[Path] = []
    for lang_dir in sorted(i18n_dir.iterdir()):
        if not lang_dir.is_dir():
            continue
        for p in lang_dir.rglob("*.md"):
            if p.name == "TRANSLATION_STATUS.md":
                continue
            out.append(p)
    return out


def evaluate(path: Path) -> TranslationStatus:
    rel = path.relative_to(REPO_ROOT)
    parts = rel.parts
    lang = parts[1] if len(parts) > 1 else "?"
    text = path.read_text(encoding="utf-8-sig")
    fm = parse_frontmatter(text)
    source_rel = fm.get("translation_of", "")
    source_commit = fm.get("source_commit", "")
    status = TranslationStatus(
        lang=lang,
        # as_posix keeps the generated status file identical across OSes
        translation_path=rel.as_posix(),
        source_path=source_rel,
        source_commit=source_commit,
        translated_at=fm.get("translated_at", ""),
        translator=fm.get("translator", ""),
    )
    if not source_rel:
        status.state = "orphan"
        status.note = "missing 'translation_of' frontmatter"
        return status
    source_path = REPO_ROOT / source_rel
    if not source_path.is_file():
        status.state = "orphan"
        status.note = f"source file not found: {source_rel}"
        return status
    actual = git_last_commit_for(source_path) or ""
    status.actual_source_commit = actual
    if not source_commit:
        status.state = "stale"
        status.note = "no source_commit recorded"
        return status
    if actual.startswith(source_commit) or source_commit.startswith(actual):
        status.state = "in_sync"
        return status
    drift = git_count_commits_since(source_path, source_commit)
    status.drift_commits = drift if drift is not None else -1
    status.state = "stale"
    status.note = (
        f"source updated since translation "
        f"({status.drift_commits} commits)"
        if status.drift_commits >= 0
        else "source-commit mismatch (could not measure drift)"
    )
    return status


def find_missing(i18n_dir: Path, statuses: list[TranslationStatus]) -> list[TranslationStatus]:
    """For each known language, list canonical files that have no translation yet."""
    if not i18n_dir.is_dir():
        return []
    languages = [d.name for d in i18n_dir.iterdir() if d.is_dir()]
    canonical = sorted(
        list((REPO_ROOT / "knowledge-base").glob("*.md"))
        + list((REPO_ROOT / "quick-start").glob("*.md"))
    )
    out: list[TranslationStatus] = []
    for lang in languages:
        translated_sources = {
            s.source_path for s in statuses if s.lang == lang and s.source_path
        }
        for canon in canonical:
            rel = canon.relative_to(REPO_ROOT)
            if rel.as_posix() in translated_sources:
                continue
            expected = REPO_ROOT / "i18n" / lang / rel
            if expected.is_file():
                continue
            out.append(
                TranslationStatus(
                    lang=lang,
                    translation_path=expected.relative_to(REPO_ROOT).as_posix(),
                    source_path=rel.as_posix(),
                    state="missing",
                    note="no translation file present",
                )
            )
    return out


def render_report(statuses: list[TranslationStatus]) -> str:
    icon = {"in_sync": "✅", "stale": "⚠️", "orphan": "ℹ️", "missing": "❌"}
    by_lang: dict[str, list[TranslationStatus]] = {}
    for s in statuses:
        by_lang.setdefault(s.lang, []).append(s)
    lines = ["# Translation Status", ""]
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), text=True
        ).strip()
        lines.append(f"> Source HEAD: `{head}`")
    except Exception:  # noqa: BLE001
        lines.append("> Source HEAD: (git unavailable)")
    lines.append("")
    for lang in sorted(by_lang):
        rows = sorted(by_lang[lang], key=lambda s: s.translation_path)
        lines.append(f"## {lang}")
        lines.append("")
        lines.append("| File | State | Source commit | Drift |")
        lines.append("|------|-------|---------------|-------|")
        for s in rows:
            state_str = f"{icon.get(s.state, '?')} {s.state.replace('_', ' ')}"
            commit = s.source_commit[:7] if s.source_commit else "—"
            drift = (
                f"{s.drift_commits} commits"
                if s.drift_commits and s.drift_commits > 0
                else ("—" if s.state == "in_sync" else s.note)
            )
            lines.append(
                f"| `{s.translation_path}` | {state_str} | `{commit}` | {drift} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translation drift report")
    parser.add_argument("--update-status", action="store_true",
                        help="Write i18n/TRANSLATION_STATUS.md")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true",
                        help="Exit 1 if any file is stale/missing/orphan")
    args = parser.parse_args(argv)

    _enable_utf8_stdout()

    if not I18N_DIR.is_dir():
        print(f"[check_translations] i18n/ directory not found at {I18N_DIR}")
        return 0

    translations = collect_translations(I18N_DIR)
    statuses = [evaluate(p) for p in translations]
    statuses += find_missing(I18N_DIR, statuses)

    if args.json:
        print(
            json.dumps(
                [asdict(s) for s in statuses],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        report = render_report(statuses)
        if args.update_status:
            STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATUS_FILE.write_text(report, encoding="utf-8")
            print(f"Wrote {STATUS_FILE}")
        else:
            print(report)

    if args.strict:
        if any(s.state != "in_sync" for s in statuses):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
