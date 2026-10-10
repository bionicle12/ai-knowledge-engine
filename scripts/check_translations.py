#!/usr/bin/env python3
"""check_translations — drift report for translated docs.

For every file under `i18n/<lang>/`, parses its `translation_of:` frontmatter
field and compares the EN source as it is now (working tree, uncommitted edits
included) with the same file at the recorded `source_commit`. Emits status:

  ✅ in sync   — the source text is unchanged since `source_commit`
  ⚠️ stale     — the source text changed; translation may need update
  ❔ unknown   — drift cannot be measured (no git history for the source,
                 or `source_commit` is missing from this clone)
  ❌ missing   — an EN source has no translation in this language yet
  ℹ️ orphan    — translation exists but `translation_of` target is missing

Line endings and the version number on a shields.io badge line do not count
as drift: a release rewrites the README badge, the translation keeps its own.

Usage:
    python3 scripts/check_translations.py
    python3 scripts/check_translations.py --update-status   # write i18n/TRANSLATION_STATUS.md
    python3 scripts/check_translations.py --json
    python3 scripts/check_translations.py --strict          # exit 1 unless every file is in sync
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
I18N_DIR = REPO_ROOT / "i18n"
STATUS_FILE = I18N_DIR / "TRANSLATION_STATUS.md"

# EN sources every language is expected to translate. Recursive, so a new
# folder of docs is covered; code, fixtures and templates are not prose to
# translate. scripts/hooks/pre-commit-translation-drift.sh mirrors this set.
CANONICAL_GLOBS = ("README.md", "knowledge-base/**/*.md", "quick-start/**/*.md")
NON_DOC_DIRS = frozenset({"scripts", "templates", "tests", "vendor"})


def _enable_utf8_stdout() -> None:
    """Windows consoles default to a legacy codepage that cannot encode the
    status emoji; switch to UTF-8 where the runtime allows it."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # pragma: no cover
            pass

# The leading `---` block only; `[ \t]` so a fence never swallows a newline.
FRONTMATTER_RE = re.compile(
    r"\A\ufeff?---[ \t]*\r?\n(?P<block>.*?)^---[ \t]*\r?$",
    re.DOTALL | re.MULTILINE,
)
_SHA_RE = re.compile(r"[0-9a-f]{7,40}")
_BADGE_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


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
    state: str = "unknown"   # in_sync | stale | unknown | missing | orphan
    note: str = ""


def frontmatter_span(text: str) -> tuple[int, int] | None:
    """Start/end offsets of the leading frontmatter block (between the fences)."""
    m = FRONTMATTER_RE.match(text)
    return m.span("block") if m else None


def parse_frontmatter(text: str) -> dict:
    span = frontmatter_span(text)
    if span is None:
        return {}
    out: dict = {}
    for line in text[span[0]:span[1]].splitlines():
        if not line.strip() or ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = v.strip()
        if not v.startswith(("'", '"')):
            v = re.split(r"\s+#", v, maxsplit=1)[0]
        out[k.strip()] = v.strip('"').strip("'")
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


def _git(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, cwd=str(REPO_ROOT), check=False
        )
    except OSError:
        return None


def git_resolve_commit(rev: str) -> str | None:
    result = _git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    if result is None or result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip() or None


def git_file_at(commit: str, source_rel: str) -> bytes | None:
    """Bytes of `source_rel` (repo-relative) at `commit`; None if absent."""
    result = _git("show", f"{commit}:./{source_rel}")
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def git_has_uncommitted_changes(path: Path) -> bool:
    result = _git("diff", "--quiet", "HEAD", "--", str(path))
    return result is not None and result.returncode == 1


def drift_text(data: bytes) -> str:
    """Source text as drift sees it: line endings and badge versions do not count."""
    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    return "\n".join(
        _BADGE_VERSION_RE.sub("X.Y.Z", line) if "img.shields.io/badge/" in line else line
        for line in text.split("\n")
    )


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
    if not actual:
        status.state = "unknown"
        status.note = (
            "no git history for the source (not a git checkout, "
            "or the file is not committed yet)"
        )
        return status
    if not _SHA_RE.fullmatch(source_commit):
        # A placeholder, or a name that moves (`HEAD`, a branch): resolving
        # it would compare the source with its own tip — "in sync" forever.
        status.state = "stale"
        status.note = f"source_commit {source_commit!r} is not a commit sha"
        return status
    commit = git_resolve_commit(source_commit)
    if commit is None:
        status.state = "unknown"
        status.note = f"source_commit {source_commit[:12]} is not in this clone"
        return status
    baseline = git_file_at(commit, source_rel)
    if baseline is None:
        status.state = "stale"
        status.note = f"source did not exist at {source_commit[:12]} (moved?)"
        return status
    if drift_text(baseline) == drift_text(source_path.read_bytes()):
        status.state = "in_sync"
        return status
    drift = git_count_commits_since(source_path, commit)
    status.drift_commits = drift if drift is not None else -1
    status.state = "stale"
    changes = []
    if drift:
        changes.append(f"{drift} commit{'' if drift == 1 else 's'}")
    elif drift is None:
        changes.append("commits not counted")
    if git_has_uncommitted_changes(source_path):
        changes.append("uncommitted edits")
    status.note = "source updated since translation" + (
        f" ({' + '.join(changes)})" if changes else ""
    )
    return status


def canonical_sources(repo_root: Path) -> list[Path]:
    """EN files matched by CANONICAL_GLOBS, outside NON_DOC_DIRS and dot-folders."""
    found: set[Path] = set()
    for pattern in CANONICAL_GLOBS:
        for p in repo_root.glob(pattern):
            folders = p.relative_to(repo_root).parts[:-1]
            if not p.is_file() or NON_DOC_DIRS.intersection(folders):
                continue
            if any(part.startswith(".") for part in folders):
                continue
            found.add(p)
    return sorted(found)


def find_missing(i18n_dir: Path, statuses: list[TranslationStatus]) -> list[TranslationStatus]:
    """For each known language, list canonical files that have no translation yet."""
    if not i18n_dir.is_dir():
        return []
    languages = [d.name for d in i18n_dir.iterdir() if d.is_dir()]
    canonical = canonical_sources(REPO_ROOT)
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
    # No HEAD sha or date: the committed report changes only when drift does.
    icon = {"in_sync": "✅", "stale": "⚠️", "unknown": "❔", "orphan": "ℹ️", "missing": "❌"}
    by_lang: dict[str, list[TranslationStatus]] = {}
    for s in statuses:
        by_lang.setdefault(s.lang, []).append(s)
    lines = [
        "# Translation Status",
        "",
        "> Generated by `python3 scripts/check_translations.py --update-status`.",
        "> Drift compares each EN source (working tree) with its text at the",
        "> translation's `source_commit`.",
        "",
    ]
    for lang in sorted(by_lang):
        rows = sorted(by_lang[lang], key=lambda s: s.translation_path)
        lines.append(f"## {lang}")
        lines.append("")
        lines.append("| File | State | Source commit | Drift |")
        lines.append("|------|-------|---------------|-------|")
        for s in rows:
            state_str = f"{icon.get(s.state, '?')} {s.state.replace('_', ' ')}"
            commit = s.source_commit[:7] if s.source_commit else "—"
            drift = "—" if s.state == "in_sync" else (s.note or "—")
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
                        help="Exit 1 if any file is stale/unknown/missing/orphan")
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
            current = (
                STATUS_FILE.read_text(encoding="utf-8") if STATUS_FILE.is_file() else None
            )
            if current == report:
                print(f"Up to date: {STATUS_FILE}")
            else:
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
