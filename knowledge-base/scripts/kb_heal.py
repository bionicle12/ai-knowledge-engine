#!/usr/bin/env python3
"""kb_heal — catch-up repair after an upgrade. No LLM.

``--plan`` runs one detector per ``MIGRATIONS.md`` step and collects hanging
``.new`` sidecars, config problems, lint L1 errors and doctor errors into
``review/needs-heal/HEAL_PLAN.md`` (first line: a ``heal-summary`` comment
that ``kb_status.py`` reads). ``--apply auto`` applies only the auto bucket;
it is idempotent and copies every file it changes into ``.kb-backups/``
first. Assisted and human items are never applied here — they are the
``!heal`` queue. Content hygiene (stale and orphan pages) belongs to kb_lint.

See ``kb-docs/18_HEAL.md``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402
import kb_doctor  # noqa: E402
import kb_lint  # noqa: E402


HEAL_PLAN_NAME = "HEAL_PLAN.md"
BACKUP_ROOT = ".kb-backups"
BACKUP_MANIFEST = "MANIFEST.json"
# Heal backups written before 0.16 carry only this file with this line.
LEGACY_MANIFEST, LEGACY_MARKER = "MANIFEST.txt", "kb_heal backup"
DEFAULT_ASSISTED_BATCH = 20
STAGE_NAMES = {1: "safe", 2: "hygiene", 3: "measure", 4: "trim", 5: "content"}
SUMMARY_RE = re.compile(r"<!--\s*heal-summary:(?P<fields>[^>]*?)-->")

DEFAULT_INSTRUCTIONS_LINT = """\
instructions_lint:
  agents_max_bytes: 10240
  absolute_max_outside_invariants: 8
  review_stale_days: 90
  work_ordering_phrases:
    - "максимально тщательно"
    - "рассмотри все варианты"
    - "перепроверь несколько раз"
    - "добейся полной уверенности"
    - "thoroughly"
    - "consider all"
    - "be maximally"
"""

DEFAULT_HEAL = """\
heal:
  auto_apply: true
  stage: 1
  assisted_batch: 20
"""

DEFAULT_INSTRUCTIONS_REVIEW = """\
instructions_review:
  reviewed_at: ""
  reviewed_model: ""
  clean_run_baseline: ""
"""

# The `media:` and `sync:` sections of templates/kb.config.yml.template
# (a test keeps the values in step with the template).
MEDIA_BLOCK = """\
# Media processing — transcription (STT), OCR, archive unpacking
# (see kb-docs/15_MEDIA_PROCESSING.md). Requires: pip install -r requirements-media.txt
media:
  stt:                                                 # audio + video → processed/transcripts/
    enabled: true
    backends: ["faster-whisper", "openai-whisper"]     # faster-whisper needs no system ffmpeg
    model: "small"                                     # tiny | base | small | medium | large-v3
    language: "auto"                                   # "auto", or ISO code like "ru" / "en"
    device: "auto"                                     # auto | cpu | cuda
    compute_type: "int8"                               # int8 (fast CPU) | float16 (GPU) | float32
    timestamps: true                                   # add [mm:ss] markers per segment
    allow_cloud: false                                 # reserved: cloud STT is not implemented yet
  ocr:                                                 # images/scans → processed/ocr/
    enabled: true
    backends: ["rapidocr", "tesseract"]                # rapidocr needs no system deps
    language: "auto"
  archives:                                            # .zip/.tar(.gz) → unpacked to raw/unsorted/
    enabled: true
    max_files: 200                                     # safety cap when unpacking
    max_total_mb: 500                                  # total uncompressed size per archive
    max_member_mb: 200                                 # per archive member
"""

SYNC_BLOCK = """\
# Cross-base import/export — merging two deployments of this base
# (see kb-docs/16_MERGE.md). Added by kb_heal: confirm `label` before the
# first export; it must differ on every machine.
sync:
  label: {label}
  export:
    sections: ["knowledge", "assets-index", "interactions", "meta", "config", "log"]
    with_assets: false                                 # binary originals stay home by default
  import:
    strategy: "safe"                                   # safe | prefer-incoming | prefer-local
    similarity_threshold: 0.85                         # ≥ → flagged as a merge candidate
    backup: true                                       # snapshot every touched file first; false also disables kb_import --undo
    move_applied: true                                 # bundle → sync/applied/ after import
"""

REQUIREMENTS_NLP_HEADER = """\
# AI Knowledge Engine — optional NLP extras (KeyBERT keywords)
# Without this file ingest extracts keywords with RAKE (rake-nltk, in
# requirements.txt). KeyBERT pulls in PyTorch; install the CPU-only wheel
# first:
#   pip install torch --index-url https://download.pytorch.org/whl/cpu
#   pip install -r requirements-nlp.txt
# (moved here from requirements.txt by kb_heal)

"""

# .gitignore blocks from templates/.gitignore.template: (comment, entries).
GITIGNORE_PRIVATE = (
    "# Private material (see kb-docs/03_PIPELINE.md and kb-docs/04_REVIEW.md).",
    ("/raw/", "/assets/", "/processed/", "/review/", "/interactions/"),
)
GITIGNORE_BACKUPS = (
    "# Snapshots: heal backups (see kb-docs/18_HEAL.md) and finalize.sh leftovers",
    ("/.kb-backups/", "/.kb-finalize-backup/", "/.kb-finalize.journal"),
)
GITIGNORE_STATE_COMMENT = "# Machine-local state: locks, caches, hook logs"
GITIGNORE_STATUS_COMMENT = (
    "# Session hand-off, regenerated by scripts/kb_status.py on every reindex"
)

ROOT_MODULES = ("17_REFACTOR.md", "18_HEAL.md")
# Base files whose prose points the agent at instruction modules (NN_NAME.md).
POINTER_FILES = ("AGENTS.md", "START_HERE.md", "KNOWLEDGE_STRUCTURE.md")
# A module reference with its folder part, e.g. `18_HEAL.md`, `kb-docs/18_HEAL.md`.
_MODULE_REF_RE = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*)(\d\d_[A-Z][A-Z0-9_]*\.md)\b")
METADATA_DIR = "processed/extracted-metadata"
_KEYBERT_RE = re.compile(r"^\s*keybert\b", re.IGNORECASE)
_EXTRACTION_KEY_RE = re.compile(r"(?m)^extraction:")
_RAW_CATEGORY_KEY_RE = re.compile(r"(?m)^raw_category:")
SESSIONS_DIR = "interactions/sessions"
# The frontmatter body of a Markdown file (between the two `---` lines).
_FRONTMATTER_RE = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)^---[ \t]*\r?$", re.S | re.M)
# Rules of templates/.gitattributes.template other than the catch-all
# `* text=auto` (which would change the line endings of every other file).
GITATTRIBUTES_RULES = (
    "# Line endings that must not follow the checkout platform (added by kb_heal)",
    (
        "*.sh text eol=lf",
        "*.command text eol=lf",
        "shell/hooks/* text eol=lf",
        "*.py text eol=lf",
        "*.bat text eol=crlf",
        "*.cmd text eol=crlf",
    ),
)
HOOK_MARKER = "ai-knowledge-engine post-commit hook"
# Hooks the pre-0.16 13_AUTORUN prose had the owner write by hand.
_HAND_HOOKS = ("post-commit", "post-merge", "post-rewrite")
_PIPELINE_CALL_RE = re.compile(r"kb_reindex|kb_ingest|shell/reindex\.sh")
# The kit check of the 0.16 shell/finalize.sh (its refusal message).
FINALIZE_GUARD = "is not the engine kit"

_SKIP_SIDECAR_PARTS = {".venv", "venv", ".git", ".kb-backups", "node_modules", "__pycache__"}
# L1 lint errors an upgrade can newly surface in an old base. Stale and orphan
# pages are content hygiene: kb_lint reports them, heal does not queue them.
_HYGIENE_LINT = {
    "frontmatter",
    "broken-link",
    "source-hash",
    "duplicate-slug",
    "expired-temporal",
    "invariants",
    "superseded",
}
_LINT_OWNED = {"stale", "orphan"}
_TRIM_LINT = {"agents-bytes", "instruction-absolutes", "work-ordering"}
_CONTENT_LINT = {"instructions-review", "profile-review"}


@dataclass
class MigrationStep:
    version: str
    id: str
    bucket: str
    detect: str = ""
    fix: str = ""


@dataclass
class Finding:
    id: str
    bucket: str
    title: str
    detail: str = ""
    source: str = ""
    stage: int = 1
    locked: bool = False
    fix: str = ""


def parse_migrations(text: str) -> list[MigrationStep]:
    steps: list[MigrationStep] = []
    current_version = "0.0.0"
    current: MigrationStep | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            rest = (line[3:].strip().split() or [""])[0]
            if re.match(r"^\d+\.\d+", rest):
                current_version = rest
            continue
        id_m = re.match(r"- id:\s*(\S+)\s*$", line)
        if id_m:
            if current is not None:
                steps.append(current)
            current = MigrationStep(
                version=current_version, id=id_m.group(1), bucket=""
            )
            continue
        if current is None:
            continue
        field_m = re.match(r"  (bucket|detect|fix):\s*(.*)$", line)
        if not field_m:
            continue
        value = field_m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        setattr(current, field_m.group(1), value)
    if current is not None:
        steps.append(current)
    return steps


def load_migrations_text(
    *, migrations_text: str | None = None, migrations_path: Path | None = None
) -> str:
    if migrations_text is not None:
        return migrations_text
    path = migrations_path or find_migrations_file()
    if path is None or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def find_migrations_file() -> Path | None:
    env = os.environ.get("AI_KNOWLEDGE_ENGINE_HOME", "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env) / "MIGRATIONS.md")
    here = SCRIPT_DIR
    for parent in (here, *here.parents):
        candidates.append(parent / "MIGRATIONS.md")
        candidates.append(parent / "ai-knowledge-engine" / "MIGRATIONS.md")
    try:
        import kb_update

        repo = kb_update.find_source_repo(
            explicit=None,
            start=Path.cwd(),
            script_path=Path(__file__),
        )
        candidates.append(repo / "MIGRATIONS.md")
    except Exception:
        pass
    seen: set[str] = set()
    for cand in candidates:
        try:
            key = str(cand.resolve())
        except OSError:
            key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if cand.is_file():
            return cand
    return None


def _engine_root() -> Path | None:
    """The engine checkout MIGRATIONS.md comes from (reference copies, hashes)."""
    path = find_migrations_file()
    if path is None:
        return None
    engine = path.parent
    return engine if (engine / "knowledge-base").is_dir() else None


def _version_key(value: Any) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", str(value or ""))
    return tuple(int(n) for n in numbers[:4]) or (0,)


def _config_path(root: Path) -> Path:
    return root / kbc.DEFAULT_CONFIG_FILENAME


def _config_text(root: Path) -> str:
    path = _config_path(root)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").lstrip("﻿")


def _has_top_level_key(text: str, key: str) -> bool:
    return bool(re.search(rf"^{re.escape(key)}:", text, re.MULTILINE))


def _raw_section(root: Path, key: str) -> dict:
    raw = kbc.load_config(root).raw
    value = raw.get(key) if isinstance(raw, dict) else None
    return value if isinstance(value, dict) else {}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _read_raw(path: Path) -> str:
    """Like _read, but CRLF stays CRLF (for files heal appends to)."""
    return path.read_bytes().decode("utf-8", errors="replace")


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def measure_closed(root: Path) -> bool:
    questions = root / kbc.EVAL_ROOT / "QUESTIONS.md"
    if not questions.is_file():
        return False
    text = questions.read_text(encoding="utf-8")
    if "{{EVAL_" in text:
        return False
    return all(f"## Q{i}." in text for i in (1, 2, 3))


def _heal_settings(root: Path) -> dict:
    cfg = kbc.load_config(root)
    raw = cfg.raw.get("heal") if isinstance(cfg.raw, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    last_run = raw.get("last_run")

    def _int(value: Any, default: int, low: int, high: int) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return min(max(number, low), high)

    auto_apply = raw.get("auto_apply", True)
    return {
        "auto_apply": auto_apply if isinstance(auto_apply, bool) else True,
        "stage": _int(raw.get("stage"), 1, 1, 5),
        "assisted_batch": _int(
            raw.get("assisted_batch"), DEFAULT_ASSISTED_BATCH, 1, 10_000
        ),
        "last_run": last_run if isinstance(last_run, dict) else {},
        "instructions_version": cfg.instructions_version,
    }


# ---------------------------------------------------------------------------
# Detectors — one per MIGRATIONS.md step. A detector returns False when the
# base is in order, True (or a non-empty string with specifics) when the step
# still has to run.
# ---------------------------------------------------------------------------


def _detect_instruction_lint(root: Path) -> bool:
    text = _config_text(root)
    return bool(text) and not _has_top_level_key(text, "instructions_lint")


def _detect_heal_config(root: Path) -> bool:
    text = _config_text(root)
    return bool(text) and not _has_top_level_key(text, "heal")


def _detect_instructions_review(root: Path) -> bool:
    text = _config_text(root)
    return bool(text) and not _has_top_level_key(text, "instructions_review")


def _detect_agents_max_bytes(root: Path) -> bool:
    if not _has_top_level_key(_config_text(root), "instructions_lint"):
        return False
    val = _raw_section(root, "instructions_lint").get("agents_max_bytes")
    if val is None:
        return True
    try:
        return int(val) < 10240
    except (TypeError, ValueError):
        return True


def _agents_text(root: Path) -> str | None:
    path = root / "AGENTS.md"
    return _read(path) if path.is_file() else None


def _detect_agents_c2_trim(root: Path) -> bool:
    text = _agents_text(root)
    if text is None:
        return False
    return (
        "## Token budget" in text
        or "Auto-detects when meaningful material has accumulated" in text
        or "If you've loaded > 5" in text
        or "If you have loaded > 5" in text
    )


def _detect_refactor_command(root: Path) -> bool:
    text = _agents_text(root)
    return text is not None and "!refactor" not in text


def _detect_profile_review_command(root: Path) -> bool:
    text = _agents_text(root)
    return text is not None and "!profile-review" not in text


def _detect_quiz_command(root: Path) -> bool:
    text = _agents_text(root)
    return text is not None and "!quiz" not in text


def _detect_eval_skeleton(root: Path) -> bool:
    return not (root / kbc.EVAL_ROOT / kbc.EVAL_RESULTS_DIR).is_dir()


def _detect_eval_bootstrap(root: Path) -> bool:
    return not (root / kbc.EVAL_ROOT / "QUESTIONS.md").is_file()


def _detect_invariants(root: Path) -> bool:
    text = _agents_text(root)
    return text is not None and bool(kbc.invariant_problems(text))


def _primary_agent(root: Path) -> str:
    index = kbc.load_config(root).index
    agent = index.get("primary_agent") if isinstance(index, dict) else None
    return str(agent or "").strip().lower()


def _detect_codex_window(root: Path) -> bool:
    if _primary_agent(root) != "codex":
        return False
    index = kbc.load_config(root).index
    profile = str((index or {}).get("window_profile") or "")
    return profile in {"", "256k"}


def _detect_doctor_codex_env(root: Path) -> bool:
    script = root / "scripts" / "kb_doctor.py"
    if not script.is_file():
        return False
    return "def check_agent_env" not in _read(script)


def _detect_start_here_opening(root: Path) -> bool:
    path = root / "START_HERE.md"
    if not path.is_file():
        return False
    return "the agent has no idea this knowledge base exists" in _read(path)


def _detect_agents_stopper(root: Path) -> bool:
    text = _agents_text(root)
    if text is None:
        return False
    return (
        "If the user issues a `!`-command before that opening line" in text
        or "re-issue the command" in text
    )


def _detect_claude_md_bridge(root: Path) -> str:
    path = root / "CLAUDE.md"
    if path.is_file():
        if "@AGENTS.md" in _read(path):
            return ""
        return "CLAUDE.md does not import @AGENTS.md"
    if (root / "AGENTS.md").is_file() and _primary_agent(root) == "claude-code":
        return "CLAUDE.md is missing (index.primary_agent: claude-code)"
    return ""


def _packs_stale(root: Path) -> bool | str:
    knowledge = root / "knowledge"
    packs = root / ".repomix"
    if not packs.is_dir():
        return False
    try:
        manifest = json.loads((packs / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None
    pack_xml = [p for p in packs.glob("*.xml") if p.is_file() and p.name != "output.xml"]
    if pack_xml and not isinstance(manifest, dict):
        # Built before 0.16: may still hold deleted pages or folders the
        # privacy floor now excludes.
        return "packs without .repomix/manifest.json (built before 0.16)"
    if isinstance(manifest, dict):
        packs_entries = manifest.get("packs")
        entries = list(packs_entries.items()) if isinstance(packs_entries, dict) else []
        if manifest.get("mode") == "legacy":
            entries.append(("output.xml", manifest.get("legacy")))
        broken = sorted(
            f"{name} {entry['state']}"
            for name, entry in entries
            if isinstance(entry, dict) and entry.get("state") in ("FAILED", "STALE")
        )
        if broken:
            return "last build left " + ", ".join(broken)
    if not knowledge.is_dir():
        return False
    md = [p for p in knowledge.rglob("*.md") if p.is_file()]
    xml = [p for p in packs.glob("*.xml") if p.is_file()]
    if not md or not xml:
        return False
    return max(p.stat().st_mtime for p in md) > max(p.stat().st_mtime for p in xml) + 1


def _normalized(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _known_hashes(engine: Path, rel: str) -> set[str]:
    try:
        data = json.loads((engine / "scripts" / "known_hashes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    files = data.get("files") if isinstance(data, dict) else None
    entry = files.get(rel) if isinstance(files, dict) else None
    return set(entry) if isinstance(entry, dict) else set()


def _root_modules(root: Path) -> dict[str, str]:
    """Root-level copies of kb-docs modules: name → "pristine" | "customized".

    Pristine = identical (CRLF read as LF) to ``kb-docs/<name>``, to the
    engine's current module, or to any released version of it
    (``scripts/known_hashes.json`` in the engine)."""
    if not _config_path(root).is_file():
        return {}
    states: dict[str, str] = {}
    engine: Path | None = None
    engine_checked = False
    for name in ROOT_MODULES:
        src = root / name
        if not src.is_file():
            continue
        data = _normalized(src.read_bytes())
        if not engine_checked:
            engine, engine_checked = _engine_root(), True
        refs = [root / kbc.KB_DOCS_DIR / name]
        if engine is not None:
            refs.append(engine / "knowledge-base" / name)
        pristine = any(
            ref.is_file() and _normalized(ref.read_bytes()) == data for ref in refs
        ) or (
            engine is not None
            and hashlib.sha256(data).hexdigest()
            in _known_hashes(engine, f"knowledge-base/{name}")
        )
        states[name] = "pristine" if pristine else "customized"
    return states


def _detect_kb_docs_dir(root: Path) -> str:
    pristine = [n for n, s in _root_modules(root).items() if s == "pristine"]
    return ", ".join(f"root-level {name}" for name in pristine)


def _dangling_module_refs(root: Path) -> dict[str, list[str]]:
    """POINTER_FILES name → module references outside ``kb-docs/`` that
    lead nowhere: the file is absent, or it is a pristine root copy that
    kb-docs-dir moves into ``kb-docs/``. A root copy the owner kept (local
    edits) still works, so a reference to it is left alone."""
    moving = {n for n, s in _root_modules(root).items() if s == "pristine"}
    out: dict[str, list[str]] = {}
    for name in POINTER_FILES:
        path = root / name
        if not path.is_file():
            continue
        refs: list[str] = []
        for match in _MODULE_REF_RE.finditer(_read(path)):
            folder, module = match.group(1), match.group(2)
            folder = folder[2:] if folder.startswith("./") else folder
            if folder == f"{kbc.KB_DOCS_DIR}/":
                continue
            if (root / folder / module).is_file() and not (not folder and module in moving):
                continue
            ref = folder + module
            if ref not in refs:
                refs.append(ref)
        if refs:
            out[name] = refs
    return out


def _detect_module_pointers(root: Path) -> str:
    return "; ".join(
        f"{name}: " + ", ".join(refs) for name, refs in _dangling_module_refs(root).items()
    )


def _legacy_metadata(root: Path) -> list[Path]:
    """Metadata written before 0.16: a mapping without ``extraction:``."""
    folder = root / METADATA_DIR
    if not folder.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(folder.glob("*.yml")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if _EXTRACTION_KEY_RE.search(text):
            continue
        try:
            data = kbc.yaml_load(text)
        except Exception:  # noqa: BLE001 — unreadable metadata is not ours to fix
            continue
        if isinstance(data, dict) and data and "extraction" not in data:
            out.append(path)
    return out


def _detect_extraction_registry(root: Path) -> str:
    legacy = _legacy_metadata(root)
    if not legacy:
        return ""
    return f"{len(legacy)} metadata file(s) in {METADATA_DIR}/ without extraction:"


def _norm_ignore(entry: str) -> str:
    text = entry.strip().lstrip("/")
    for suffix in ("/**", "/*", "/"):
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _gitignore_patterns(root: Path) -> list[tuple[bool, str]] | None:
    """(negated, pattern) of every rule in <root>/.gitignore; None if absent."""
    path = root / ".gitignore"
    if not path.is_file():
        return None
    out: list[tuple[bool, str]] = []
    for raw in _read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        out.append((negated, _norm_ignore(line[1:] if negated else line)))
    return out


def _gitignore_has(
    patterns: list[tuple[bool, str]], entry: str, *, decided: bool = False
) -> bool:
    """Is `entry` ignored (or, with `decided`, explicitly un-ignored with `!`)?"""
    name = _norm_ignore(entry)
    for negated, pattern in patterns:
        if negated and not decided:
            continue
        if pattern == name or (
            any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(name, pattern)
        ):
            return True
    return False


def _missing_ignores(root: Path, entries: tuple[str, ...], *, decided: bool = False) -> list[str]:
    patterns = _gitignore_patterns(root)
    if patterns is None:
        return []
    return [e for e in entries if not _gitignore_has(patterns, e, decided=decided)]


def _status_entries(root: Path) -> tuple[str, str]:
    name = str(kbc.load_config(root).status_file or "STATUS.md").strip().lstrip("/")
    return "/.kb-state/", f"/{name or 'STATUS.md'}"


def _detect_status_md(root: Path) -> str:
    missing = _missing_ignores(root, _status_entries(root))
    return ".gitignore lacks " + ", ".join(missing) if missing else ""


def _detect_gitignore_kb_backups(root: Path) -> str:
    missing = _missing_ignores(root, GITIGNORE_BACKUPS[1])
    return ".gitignore lacks " + ", ".join(missing) if missing else ""


def _detect_gitignore_private(root: Path) -> str:
    if _gitignore_patterns(root) is None:
        return "no .gitignore" if (root / ".git").exists() else ""
    missing = _missing_ignores(root, GITIGNORE_PRIVATE[1], decided=True)
    return ".gitignore lacks " + ", ".join(missing) if missing else ""


def _detect_media_sync(root: Path) -> str:
    text = _config_text(root)
    if not text:
        return ""
    missing = [f"kb.config.yml {k}:" for k in ("media", "sync") if not _has_top_level_key(text, k)]
    sync = root / kbc.SYNC_ROOT
    if any(not (sync / sub).is_dir() for sub in kbc.SYNC_DIRS):
        missing.append("sync/ workspace")
    review = root / "review"
    if review.is_dir() and not (review / "needs-merge").is_dir():
        missing.append("review/needs-merge/")
    return ", ".join(missing)


def _keybert_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if _KEYBERT_RE.match(line)]


def _detect_requirements_split(root: Path) -> str:
    path = root / "requirements.txt"
    if not path.is_file() or not _keybert_lines(_read(path)):
        return ""
    return "requirements.txt still lists keybert"


def _shebang_target(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            head = fh.readline(512)
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    parts = head[2:].decode("utf-8", "replace").split()
    return parts[0] if parts else None


def _detect_nested_venv(root: Path) -> str:
    problems: list[str] = []
    venv = root / ".venv"
    if (venv / ".venv" / "pyvenv.cfg").is_file():
        problems.append(".venv/.venv is a second virtual environment inside .venv")
    target = _shebang_target(venv / "bin" / "pip")
    if target and target.startswith("/") and not Path(target).exists():
        problems.append(f".venv/bin/pip runs {target}, which does not exist (the venv was moved)")
    if (root / "knowledge-base" / ".venv" / "pyvenv.cfg").is_file():
        problems.append("knowledge-base/.venv was left behind by finalize.sh")
    return "; ".join(problems)


def _detect_private_index_names(root: Path) -> str:
    """Metadata without ``raw_category:`` (every 0.16 ingest writes the key):
    its assets-index block is still titled by the file name, which may be
    private. The item closes once each file's folder is recorded."""
    if not kbc.load_config(root).privacy_require_redaction_for_chats:
        return ""
    folder = root / METADATA_DIR
    if not folder.is_dir():
        return ""
    count = 0
    for path in sorted(folder.glob("*.yml")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if _RAW_CATEGORY_KEY_RE.search(text):
            continue
        try:
            data = kbc.yaml_load(text)
        except Exception:  # noqa: BLE001 — unreadable metadata is not ours to fix
            continue
        if isinstance(data, dict) and data:
            count += 1
    if not count:
        return ""
    return f"{count} metadata file(s) in {METADATA_DIR}/ without raw_category:"


def _frontmatter(text: str) -> re.Match[str] | None:
    return _FRONTMATTER_RE.match(text)


def _session_files(root: Path) -> list[Path]:
    folder = root / SESSIONS_DIR
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*.md") if p.is_file())


def _has_key(frontmatter: str, key: str) -> bool:
    return bool(re.search(rf"(?m)^{re.escape(key)}:", frontmatter))


def _legacy_redacted_sessions(root: Path) -> list[Path]:
    """Summaries written by kb_save_session.py before 0.16: ``redacted:``
    (which only mirrored the privacy setting) next to ``saved_at:`` and
    ``session_date:``, and no ``redaction_required:``."""
    out: list[Path] = []
    for path in _session_files(root):
        match = _frontmatter(_read(path))
        if match is None:
            continue
        fm = match.group(1)
        if (
            all(_has_key(fm, key) for key in ("redacted", "saved_at", "session_date"))
            and not _has_key(fm, "redaction_required")
        ):
            out.append(path)
    return out


def _detect_session_redacted_flag(root: Path) -> str:
    legacy = _legacy_redacted_sessions(root)
    if not legacy:
        return ""
    return f"{len(legacy)} session file(s) in {SESSIONS_DIR}/ with redacted:"


def _detect_meta_review_backlog(root: Path) -> str:
    waiting = 0
    for path in _session_files(root):
        match = _frontmatter(_read(path))
        if match is None or not _has_key(match.group(1), "meta_reviewed"):
            waiting += 1
    if not waiting:
        return ""
    return f"{waiting} session file(s) in {SESSIONS_DIR}/ without meta_reviewed:"


def _detect_populate_notes_marker(root: Path) -> bool:
    path = root / "DATA_PLACEMENT_EXAMPLES.md"
    if not path.is_file():
        return False
    text = _read(path)
    return (
        "Generated by `kb_populate.py`" in text
        and ".repomix/output.xml" in text
        and "<!-- kb_populate:" not in text
    )


def _missing_gitattributes(root: Path) -> list[str]:
    """Rules of GITATTRIBUTES_RULES the base's .gitattributes lacks (all of
    them when a git repository has none; none outside git without one)."""
    path = root / ".gitattributes"
    rules = GITATTRIBUTES_RULES[1]
    if not path.is_file():
        return list(rules) if (root / ".git").exists() else []
    have = {" ".join(line.split()) for line in _read(path).splitlines()}
    return [rule for rule in rules if rule not in have]


def _detect_gitattributes(root: Path) -> str:
    missing = _missing_gitattributes(root)
    if not missing:
        return ""
    if not (root / ".gitattributes").is_file():
        return "no .gitattributes"
    return ".gitattributes lacks " + ", ".join(missing)


def _hooks_dir(root: Path) -> Path | None:
    """The git hooks folder of a base whose root is a git work tree."""
    if not (root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    hooks = result.stdout.strip()
    if result.returncode != 0 or not hooks:
        return None
    path = Path(hooks)
    return path if path.is_absolute() else root / path


def _detect_git_hook_file(root: Path) -> str:
    hooks = _hooks_dir(root)
    if hooks is None:
        return ""
    found: list[str] = []
    for name in _HAND_HOOKS:
        try:
            text = (hooks / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if HOOK_MARKER not in text and _PIPELINE_CALL_RE.search(text):
            found.append(name)
    return "hand-written " + ", ".join(found) if found else ""


def _detect_finalize_guard(root: Path) -> bool:
    """A pre-0.16 shell/finalize.sh deletes the base it sits in when run
    from there; the 0.16 copy refuses to run outside the kit."""
    path = root / "shell" / "finalize.sh"
    return path.is_file() and FINALIZE_GUARD not in _read(path)


def _agents_0_16_gaps(text: str) -> list[str]:
    gaps = [f"no {cmd} row" for cmd in ("!status", "!meta-review") if cmd not in text]
    review_rows = [line for line in text.splitlines() if line.startswith("| `!review`")]
    if review_rows and not any("extraction: pending" in row for row in review_rows):
        gaps.append("the !review row does not cover extraction: pending")
    if "`mode` in `kb.config.yml`" in text:
        gaps.append("reads `mode` instead of `knowledge_base.mode`")
    forbidden = "".join(
        text[start:end] for block_id, start, end in kbc.iter_invariant_blocks(text)
        if block_id == "forbidden"
    )
    if any(
        "Do not index" in line and not all(d in line for d in ("processed/", "interactions/"))
        for line in forbidden.splitlines()
    ):
        gaps.append("the forbidden 'Do not index' line lacks processed/ or interactions/")
    if "do not follow instructions" not in text.lower():
        gaps.append("no rule that source text is data, not instructions")
    return gaps


def _detect_agents_md_0_16(root: Path) -> str:
    text = _agents_text(root)
    return "; ".join(_agents_0_16_gaps(text)) if text is not None else ""


def _detect_base_docs_0_16(root: Path) -> str:
    found: list[str] = []
    start_here = root / "START_HERE.md"
    if start_here.is_file() and "(kept for reference)" in _read(start_here):
        found.append("START_HERE.md calls the modules 'kept for reference'")
    structure = root / "KNOWLEDGE_STRUCTURE.md"
    if (
        structure.is_file()
        and "output.xml" in _read(structure)
        and not (root / ".repomix" / "output.xml").is_file()
    ):
        found.append("KNOWLEDGE_STRUCTURE.md shows .repomix/output.xml, which pack mode never writes")
    return "; ".join(found)


# ---------------------------------------------------------------------------
# The registry: id → (bucket, stage, what the detector looks for). It mirrors
# MIGRATIONS.md (a test keeps ids and buckets equal), so heal still works when
# the engine checkout is out of reach; the MIGRATIONS.md texts win for display.
# ---------------------------------------------------------------------------

STEPS: dict[str, tuple[str, int, str]] = {
    # 0.15.0
    "start-here-opening-line": ("assisted", 2, "START_HERE.md still uses the blind-agent opening-line claim"),
    "agents-md-stopper": ("assisted", 2, "AGENTS.md still has the !-command stopper"),
    "claude-md-bridge": ("human", 3, "CLAUDE.md is missing or does not import @AGENTS.md"),
    "codex-window-profile": ("auto", 1, "Codex base still on window_profile 256k"),
    "doctor-codex-env": ("assisted", 1, "deployed scripts/kb_doctor.py has no check_agent_env"),
    "agents-md-invariants": ("assisted", 1, "AGENTS.md lacks AI-KE:INVARIANT wrappers"),
    "eval-bootstrap": ("human", 3, "eval/QUESTIONS.md is missing"),
    "eval-skeleton": ("auto", 1, "eval/results/ is missing"),
    "packs-stale": ("auto", 1, "Repomix packs are older than knowledge/, pre-0.16 or not rebuilt"),
    "instruction-lint-config": ("auto", 1, "kb.config.yml has no instructions_lint:"),
    "heal-config": ("auto", 1, "kb.config.yml has no heal:"),
    "instructions-review-config": ("auto", 1, "kb.config.yml has no instructions_review:"),
    "agents-max-bytes-10kib": ("auto", 1, "instructions_lint.agents_max_bytes is below 10240"),
    "refactor-command": ("assisted", 2, "AGENTS.md command table has no !refactor"),
    "agents-md-c2-trim": ("assisted", 4, "AGENTS.md still has Token budget / auto-detect / >5 stop"),
    "profile-review-command": ("assisted", 2, "AGENTS.md command table has no !profile-review"),
    "quiz-command": ("assisted", 2, "AGENTS.md command table has no !quiz"),
    # 0.16.0
    "kb-docs-dir": ("auto", 1, "pristine root-level 17_REFACTOR.md / 18_HEAL.md outside kb-docs/"),
    "module-pointers-kb-docs": ("assisted", 1, "AGENTS.md / START_HERE.md / KNOWLEDGE_STRUCTURE.md point at modules outside kb-docs/"),
    "extraction-registry": ("auto", 1, "ingest metadata has no extraction: field"),
    "status-md": ("auto", 1, ".gitignore lacks .kb-state/ or STATUS.md"),
    "gitignore-private-dirs": ("assisted", 1, ".gitignore does not keep raw/ assets/ processed/ review/ interactions/ private"),
    "gitignore-kb-backups": ("auto", 1, ".gitignore lacks .kb-backups/, .kb-finalize-backup/ or .kb-finalize.journal"),
    "media-sync-sections": ("auto", 1, "kb.config.yml has no media: / sync:, or the sync/ workspace is missing"),
    "requirements-split": ("auto", 1, "requirements.txt still lists keybert"),
    "nested-venv": ("human", 1, "the base's .venv is nested, moved or left in knowledge-base/"),
    "private-index-names": ("assisted", 1, "ingest metadata from before 0.16 records no raw_category:"),
    "session-redacted-flag": ("auto", 1, "session summaries still carry the pre-0.16 redacted: flag"),
    "meta-review-backlog": ("assisted", 2, "session summaries from before 0.16 have no meta_reviewed:"),
    "populate-notes-marker": ("assisted", 2, "DATA_PLACEMENT_EXAMPLES.md has the pre-0.16 footer"),
    "gitattributes-line-endings": ("auto", 1, ".gitattributes does not pin shell and batch line endings"),
    "git-hook-file": ("assisted", 1, "a hand-written git hook runs the pipeline"),
    "agents-md-0-16": ("assisted", 2, "AGENTS.md lacks the 0.16 command rows or rules"),
    "base-docs-0-16": ("assisted", 2, "START_HERE.md / KNOWLEDGE_STRUCTURE.md describe the pre-0.16 layout"),
    "finalize-script-guard": ("assisted", 1, "shell/finalize.sh is a pre-0.16 copy that can delete the base"),
}

DETECT_BY_ID: dict[str, Callable[[Path], bool | str]] = {
    "instruction-lint-config": _detect_instruction_lint,
    "heal-config": _detect_heal_config,
    "instructions-review-config": _detect_instructions_review,
    "agents-max-bytes-10kib": _detect_agents_max_bytes,
    "agents-md-c2-trim": _detect_agents_c2_trim,
    "refactor-command": _detect_refactor_command,
    "profile-review-command": _detect_profile_review_command,
    "quiz-command": _detect_quiz_command,
    "eval-skeleton": _detect_eval_skeleton,
    "eval-bootstrap": _detect_eval_bootstrap,
    "agents-md-invariants": _detect_invariants,
    "codex-window-profile": _detect_codex_window,
    "doctor-codex-env": _detect_doctor_codex_env,
    "packs-stale": _packs_stale,
    "start-here-opening-line": _detect_start_here_opening,
    "agents-md-stopper": _detect_agents_stopper,
    "claude-md-bridge": _detect_claude_md_bridge,
    "kb-docs-dir": _detect_kb_docs_dir,
    "module-pointers-kb-docs": _detect_module_pointers,
    "extraction-registry": _detect_extraction_registry,
    "status-md": _detect_status_md,
    "gitignore-private-dirs": _detect_gitignore_private,
    "gitignore-kb-backups": _detect_gitignore_kb_backups,
    "media-sync-sections": _detect_media_sync,
    "requirements-split": _detect_requirements_split,
    "nested-venv": _detect_nested_venv,
    "private-index-names": _detect_private_index_names,
    "session-redacted-flag": _detect_session_redacted_flag,
    "meta-review-backlog": _detect_meta_review_backlog,
    "populate-notes-marker": _detect_populate_notes_marker,
    "gitattributes-line-endings": _detect_gitattributes,
    "git-hook-file": _detect_git_hook_file,
    "agents-md-0-16": _detect_agents_md_0_16,
    "base-docs-0-16": _detect_base_docs_0_16,
    "finalize-script-guard": _detect_finalize_guard,
}


# ---------------------------------------------------------------------------
# Backups: every file an auto fix changes is copied first; the manifest keeps
# the digest before and after, so a rollback restores only what heal wrote.
# ---------------------------------------------------------------------------


def _digest(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


class Backup:
    """Collects the pre-change state of the files one heal run touches."""

    def __init__(self, root: Path):
        self.root = root
        self._before: dict[str, bytes | None] = {}
        self._dirs: list[str] = []

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def save(self, path: Path) -> None:
        """Remember `path` as it is now; call before changing it."""
        self._before.setdefault(self._rel(path), _read_bytes(path))

    def mkdir(self, path: Path) -> None:
        missing: list[Path] = []
        probe = path
        while not probe.exists() and probe != self.root:
            missing.append(probe)
            probe = probe.parent
        path.mkdir(parents=True, exist_ok=True)
        self._dirs.extend(self._rel(p) for p in reversed(missing))

    def close(self) -> Path | None:
        """Write `.kb-backups/<stamp>/` for what really changed (None: nothing)."""
        changed: dict[str, tuple[bytes | None, bytes | None]] = {}
        for rel, before in self._before.items():
            after = _read_bytes(self.root / rel)
            if after != before:
                changed[rel] = (before, after)
        if not changed and not self._dirs:
            return None
        dest = _new_backup_dir(self.root)
        files: dict[str, dict[str, str | None]] = {}
        for rel, (before, after) in changed.items():
            if before is not None:
                target = dest / "files" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(before)
            files[rel] = {"before": _digest(before), "after": _digest(after)}
        kbc.write_json(
            dest / BACKUP_MANIFEST,
            {
                "format": 1,
                "tool": "kb_heal",
                "created_at": kbc.now_iso(),
                "created_ts": time.time(),
                "files": files,
                "dirs": self._dirs,
                "rolled_back_at": None,
            },
        )
        return dest


def _new_backup_dir(root: Path) -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    parent = root / BACKUP_ROOT
    dest, n = parent / stamp, 1
    while dest.exists():
        n += 1
        dest = parent / f"{stamp}-{n}"
    dest.mkdir(parents=True)
    return dest


def _read_manifest(backup: Path) -> dict | None:
    try:
        data = json.loads((backup / BACKUP_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None


def _heal_manifest(backup: Path) -> dict | None:
    """The manifest of a backup heal wrote; None for any other folder in
    ``.kb-backups/`` (a ``!refactor`` copy, the owner's own snapshot) — heal
    never rolls those back. A heal backup from before 0.16 (only
    ``MANIFEST.txt``) gets a synthetic ``legacy`` manifest: whole-file copies,
    no after-state."""
    manifest = _read_manifest(backup)
    if manifest is not None:
        return manifest if manifest.get("tool") == "kb_heal" else None
    try:
        marker = (backup / LEGACY_MANIFEST).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if marker != LEGACY_MARKER:
        return None
    copies = sorted(p.name for p in backup.iterdir() if p.is_file() and p.name != LEGACY_MANIFEST)
    return {
        "format": 0,
        "tool": "kb_heal",
        "legacy": True,
        "created_ts": backup.stat().st_mtime,
        "copies": copies,
        "files": {},
        "dirs": [],
        "rolled_back_at": None,
    }


def _backups(root: Path) -> list[tuple[Path, dict]]:
    """Heal's own backups with their manifests, newest first."""
    parent = root / BACKUP_ROOT
    if not parent.is_dir():
        return []
    out: list[tuple[Path, dict]] = []
    for path in sorted((p for p in parent.iterdir() if p.is_dir()), reverse=True):
        manifest = _heal_manifest(path)
        if manifest is not None:
            out.append((path, manifest))
    return out


def latest_backup(root: Path) -> Path | None:
    backups = _backups(root)
    return backups[0][0] if backups else None


@dataclass
class Rollback:
    backup: Path
    restored: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # changed after the heal — left alone
    refused: list[str] = field(default_factory=list)  # manifest path outside the base
    legacy: bool = False
    already: bool = False


def restore_backup(root: Path, backup: Path | None = None) -> Rollback | None:
    """Undo one heal run: restore each file it changed unless the file was
    edited since. Without `backup`: the newest heal backup not rolled back
    yet. Folders in ``.kb-backups/`` that heal did not write are skipped."""
    if backup is None:
        backup, manifest = next(
            ((b, m) for b, m in _backups(root) if not m.get("rolled_back_at")),
            (None, None),
        )
    else:
        manifest = _heal_manifest(backup)
    if backup is None or manifest is None:
        return None
    if manifest.get("legacy"):
        # Written before 0.16: whole-file copies without the after-state, so
        # a restore could silently undo the owner's later edits. List them
        # for a manual comparison once; the next --rollback moves on.
        result = Rollback(backup, kept=list(manifest.get("copies") or []), legacy=True)
        if manifest.get("rolled_back_at"):
            result.already = True
            return result
        manifest["rolled_back_at"] = kbc.now_iso()
        kbc.write_json(backup / BACKUP_MANIFEST, manifest)
        kbc.append_log(
            operation="heal",
            title=f"rollback {backup.name}",
            details=[f"pre-0.16 backup, compare by hand `{rel}`" for rel in result.kept]
            or ["(nothing to restore)"],
            root=root,
        )
        return result
    if manifest.get("rolled_back_at"):
        return Rollback(backup, already=True)
    result = Rollback(backup)
    root_real = root.resolve()
    for rel, info in sorted(manifest["files"].items()):
        # A crafted or corrupted MANIFEST.json must not write or delete
        # anything outside the base (or read a copy outside the backup).
        inside = kbc.resolve_under(root, rel)
        copy = kbc.resolve_under(backup / "files", rel)
        if inside is None or inside == root_real or (info.get("before") is not None and copy is None):
            result.refused.append(rel)
            continue
        path = root / rel
        current = _digest(_read_bytes(path))
        if current == info.get("before"):
            continue
        if current != info.get("after"):
            result.kept.append(rel)
            continue
        if info.get("before") is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            kbc.atomic_write_bytes(path, copy.read_bytes())
        result.restored.append(rel)
    for rel in reversed(manifest.get("dirs") or []):
        inside = kbc.resolve_under(root, rel)
        if inside is None or inside == root_real:
            result.refused.append(rel)
            continue
        try:
            (root / rel).rmdir()
        except OSError:
            pass
    manifest["rolled_back_at"] = kbc.now_iso()
    kbc.write_json(backup / BACKUP_MANIFEST, manifest)
    kbc.append_log(
        operation="heal",
        title=f"rollback {backup.name}",
        details=[f"restored `{rel}`" for rel in result.restored]
        + [f"kept (edited after the heal) `{rel}`" for rel in result.kept]
        + [f"refused (outside the base) `{rel}`" for rel in result.refused]
        or ["(nothing to restore)"],
        root=root,
    )
    return result


def describe_rollback(result: Rollback) -> str:
    rel = f"{BACKUP_ROOT}/{result.backup.name}"
    if result.legacy and result.already:
        return f"{rel} (a heal backup from before 0.16) was already listed for a manual comparison"
    if result.already:
        return f"{rel} was already rolled back"
    if result.legacy:
        return (
            f"{rel} is a heal backup from before 0.16: it does not record what heal "
            f"changed, so nothing was restored. Compare these copies in {rel}/ by hand: "
            + (", ".join(result.kept) or "(none)")
            + ". Run --rollback again for the run before."
        )
    lines = [f"rolled back from {result.backup.name}: restored {len(result.restored)} file(s)"]
    lines += [f"  restored {item}" for item in result.restored]
    if result.kept:
        lines.append(
            f"  kept (edited after the heal; the pre-heal copy is in {rel}/files/):"
        )
        lines += [f"    {item}" for item in result.kept]
    if result.refused:
        lines.append("  refused (the backup manifest points outside the base; nothing touched):")
        lines += [f"    {item}" for item in result.refused]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Eval regression (the heal brake)
# ---------------------------------------------------------------------------

_REGRESSION_MARKERS = ("eval: regressed", "verdict: failed")


def eval_regressed(root: Path, since: float | None = None) -> bool:
    """True when the newest ``eval/results/*after*.md`` has a line that is
    exactly ``eval: regressed`` or ``verdict: failed``, and (with `since`) was
    written after that moment — the heal it judges."""
    results = root / kbc.EVAL_ROOT / kbc.EVAL_RESULTS_DIR
    if not results.is_dir():
        return False
    after = sorted(
        (p for p in results.glob("*.md") if "after" in p.name.lower()),
        key=lambda p: p.stat().st_mtime,
    )
    if not after:
        return False
    newest = after[-1]
    if since is not None and newest.stat().st_mtime <= since:
        return False
    return any(
        line.strip().lower() in _REGRESSION_MARKERS
        for line in newest.read_text(encoding="utf-8", errors="replace").splitlines()
    )


def verify(root: Path) -> str:
    backups = _backups(root)
    backup, manifest = backups[0] if backups else (None, {})
    since = None
    if backup is not None:
        since = float(manifest.get("created_ts") or backup.stat().st_mtime)
    if not eval_regressed(root, since=since):
        return "ok"
    if backup is None:
        return "eval regressed; no backup to roll back"
    result = restore_backup(root, backup)
    assert result is not None
    return describe_rollback(result)


# ---------------------------------------------------------------------------
# Auto fixes. Each returns True when the step is done.
# ---------------------------------------------------------------------------


def _drop_last_run_placeholder(text: str) -> str:
    """Remove the template's commented-out `# last_run:` block under `heal:`
    — heal is about to write the real one."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(r"heal:\s*(#.*)?$", line)), None)
    if start is None:
        return text
    i = start + 1
    while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
        content = lines[i].strip().lstrip("#").strip()
        if lines[i].strip().startswith("#") and content.startswith("last_run:"):
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("#") and (
                lines[j].strip().lstrip("#").strip().startswith(("at:", "version:"))
            ):
                j += 1
            del lines[i:j]
            return "".join(lines)
        i += 1
    return text


def _stamp_edits(version: str, stage: int | None) -> list:
    today = _dt.date.today().isoformat()
    edits: list = [
        lambda t: kbc.config_append_block(t, "heal", DEFAULT_HEAL),
        _drop_last_run_placeholder,
        ("heal.last_run.at", today),
        ("heal.last_run.version", version),
    ]
    if stage is not None:
        edits.append(("heal.stage", stage))
    return edits


def _touch_last_run(
    root: Path,
    version: str | None = None,
    *,
    stage: int | None = None,
    backup: Backup | None = None,
) -> None:
    """Stamp `heal.last_run` (and `heal.stage` when given) in place.

    Line edits through `kbc.update_config_file`, never a YAML round-trip:
    `kb.config.yml` is a commented, hand-edited file. Raises
    `kbc.ConfigEditError` when `heal:` cannot be edited line by line
    (flow style `heal: {…}`); nothing is written then.

    ``version`` is the version the base will carry *after* the caller is done.
    Upgrade stamps it explicitly, because heal runs before the version bump
    (it needs the old value to compute the `MIGRATIONS.md` range).
    """
    path = _config_path(root)
    if not path.is_file():
        return
    if version is None:
        version = str(kbc.load_config(root).instructions_version or "")
    if backup is not None:
        backup.save(path)
    kbc.update_config_file(root, _stamp_edits(version, stage))


def _config_edit(root: Path, step_id: str) -> Callable[[str], str] | None:
    """The kb.config.yml line edit of a config-only auto step."""
    if step_id == "instruction-lint-config":
        return lambda t: kbc.config_append_block(t, "instructions_lint", DEFAULT_INSTRUCTIONS_LINT)
    if step_id == "heal-config":
        return lambda t: kbc.config_append_block(t, "heal", DEFAULT_HEAL)
    if step_id == "instructions-review-config":
        return lambda t: kbc.config_append_block(t, "instructions_review", DEFAULT_INSTRUCTIONS_REVIEW)
    if step_id == "agents-max-bytes-10kib":
        return lambda t: kbc.config_set(t, "instructions_lint.agents_max_bytes", 10240)
    if step_id == "codex-window-profile":
        return lambda t: kbc.config_set(t, "index.window_profile", "400k")
    if step_id == "media-sync-sections":
        block = SYNC_BLOCK.format(label=json.dumps(root.name, ensure_ascii=False))
        return lambda t: kbc.config_append_block(
            kbc.config_append_block(t, "media", MEDIA_BLOCK), "sync", block
        )
    return None


def _edit_config(root: Path, backup: Backup, edit: Callable[[str], str]) -> bool:
    backup.save(_config_path(root))
    kbc.update_config_file(root, [edit])
    return True


def _apply_eval_skeleton(root: Path, backup: Backup) -> bool:
    backup.mkdir(root / kbc.EVAL_ROOT / kbc.EVAL_RESULTS_DIR)
    return True


def _apply_packs_stale(root: Path, backup: Backup) -> bool:
    script = root / "scripts" / "kb_reindex.py"
    if not script.is_file():
        return False
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--index-only", "--force"],
        cwd=str(root),
        check=False,
    )
    return result.returncode == 0 and not _packs_stale(root)


def _apply_kb_docs_dir(root: Path, backup: Backup) -> bool:
    for name, state in _root_modules(root).items():
        if state != "pristine":
            continue
        src, dst = root / name, root / kbc.KB_DOCS_DIR / name
        backup.save(src)
        if not dst.is_file():
            backup.save(dst)
            backup.mkdir(dst.parent)
            kbc.atomic_write_bytes(dst, src.read_bytes())
        src.unlink()
    return not _detect_kb_docs_dir(root)


def _ingest_backfill() -> Callable[[Path], Any] | None:
    try:
        import kb_ingest
    except Exception:  # noqa: BLE001 — a broken ingest module blocks this step only
        return None
    backfill = getattr(kb_ingest, "backfill_extraction", None)
    return backfill if callable(backfill) else None


def _apply_extraction_registry(root: Path, backup: Backup) -> bool:
    backfill = _ingest_backfill()
    if backfill is None:
        return False
    for path in _legacy_metadata(root):
        backup.save(path)
    backfill(root)
    return not _legacy_metadata(root)


def _append_gitignore(root: Path, backup: Backup, blocks: list[tuple[str, list[str]]]) -> bool:
    path = root / ".gitignore"
    blocks = [(comment, entries) for comment, entries in blocks if entries]
    if not path.is_file() or not blocks:
        return False
    backup.save(path)
    text = _read_raw(path)
    nl = _newline(text)
    parts = [text if text.endswith("\n") or not text else text + nl]
    for comment, entries in blocks:
        parts.append(nl + comment + nl + "".join(f"{e}{nl}" for e in entries))
    kbc.atomic_write_text(path, "".join(parts))
    return True


def _apply_status_md(root: Path, backup: Backup) -> bool:
    state, status = _status_entries(root)
    blocks = [
        (GITIGNORE_STATE_COMMENT, _missing_ignores(root, (state,))),
        (GITIGNORE_STATUS_COMMENT, _missing_ignores(root, (status,))),
    ]
    return _append_gitignore(root, backup, blocks) and not _detect_status_md(root)


def _apply_gitignore_kb_backups(root: Path, backup: Backup) -> bool:
    comment, entries = GITIGNORE_BACKUPS
    blocks = [(comment, _missing_ignores(root, entries))]
    return _append_gitignore(root, backup, blocks) and not _detect_gitignore_kb_backups(root)


def _apply_media_sync(root: Path, backup: Backup) -> bool:
    edit = _config_edit(root, "media-sync-sections")
    assert edit is not None
    _edit_config(root, backup, edit)
    sync = root / kbc.SYNC_ROOT
    for sub in kbc.SYNC_DIRS:
        backup.mkdir(sync / sub)
    readme = sync / "README.md"
    backup.save(readme)
    kbc.ensure_sync_dirs(root)
    if (root / "review").is_dir():
        backup.mkdir(root / "review" / "needs-merge")
    return not _detect_media_sync(root)


def _apply_requirements_split(root: Path, backup: Backup) -> bool:
    req, nlp = root / "requirements.txt", root / "requirements-nlp.txt"
    text = _read_raw(req)
    lines = text.splitlines(keepends=True)
    moved = [line.rstrip("\r\n") for line in lines if _KEYBERT_RE.match(line)]
    if not moved:
        return True
    backup.save(req)
    backup.save(nlp)
    if nlp.is_file():
        current = _read_raw(nlp)
        if not _keybert_lines(current):
            nl = _newline(current)
            sep = "" if current.endswith("\n") or not current else nl
            kbc.atomic_write_text(nlp, current + sep + "".join(f"{m}{nl}" for m in moved))
    else:
        nl = _newline(text)
        header = REQUIREMENTS_NLP_HEADER.replace("\n", nl)
        kbc.atomic_write_text(nlp, header + "".join(f"{m}{nl}" for m in moved))
    kbc.atomic_write_text(req, "".join(line for line in lines if not _KEYBERT_RE.match(line)))
    return True


def _apply_session_redacted_flag(root: Path, backup: Backup) -> bool:
    """Rename the frontmatter key ``redacted:`` to ``redaction_required:``
    (value kept): nothing was ever redacted, the flag mirrored the setting."""
    for path in _legacy_redacted_sessions(root):
        text = _read_raw(path)
        match = _frontmatter(text)
        if match is None:
            continue
        fm = re.sub(r"(?m)^redacted:", "redaction_required:", match.group(1), count=1)
        backup.save(path)
        kbc.atomic_write_text(path, text[: match.start(1)] + fm + text[match.end(1):])
    return not _legacy_redacted_sessions(root)


def _apply_gitattributes(root: Path, backup: Backup) -> bool:
    """Add the missing rules at the top, so the owner's own later rules keep
    precedence (the last matching line wins), as finalize.sh does."""
    missing = _missing_gitattributes(root)
    if not missing:
        return True
    path = root / ".gitattributes"
    backup.save(path)
    text = _read_raw(path) if path.is_file() else ""
    nl = _newline(text)
    block = GITATTRIBUTES_RULES[0] + nl + "".join(f"{rule}{nl}" for rule in missing)
    kbc.atomic_write_text(path, block + (nl + text if text else ""))
    return not _missing_gitattributes(root)


def _config_applier(step_id: str) -> Callable[[Path, Backup], bool]:
    def apply(root: Path, backup: Backup) -> bool:
        edit = _config_edit(root, step_id)
        assert edit is not None
        return _edit_config(root, backup, edit)

    return apply


APPLY_BY_ID: dict[str, Callable[[Path, Backup], bool]] = {
    "instruction-lint-config": _config_applier("instruction-lint-config"),
    "heal-config": _config_applier("heal-config"),
    "instructions-review-config": _config_applier("instructions-review-config"),
    "agents-max-bytes-10kib": _config_applier("agents-max-bytes-10kib"),
    "codex-window-profile": _config_applier("codex-window-profile"),
    "eval-skeleton": _apply_eval_skeleton,
    "packs-stale": _apply_packs_stale,
    "kb-docs-dir": _apply_kb_docs_dir,
    "extraction-registry": _apply_extraction_registry,
    "status-md": _apply_status_md,
    "gitignore-kb-backups": _apply_gitignore_kb_backups,
    "media-sync-sections": _apply_media_sync,
    "requirements-split": _apply_requirements_split,
    "session-redacted-flag": _apply_session_redacted_flag,
    "gitattributes-line-endings": _apply_gitattributes,
}


def _auto_blocker(root: Path, step_id: str) -> str | None:
    """Why an auto step cannot be applied here (it is then assisted)."""
    edit = _config_edit(root, step_id)
    if edit is not None:
        try:
            edit(_config_text(root))
        except kbc.ConfigEditError as exc:
            return f"kb.config.yml cannot be edited line by line: {exc}"
    if step_id == "extraction-registry" and _ingest_backfill() is None:
        return (
            "scripts/kb_ingest.py has no backfill_extraction (older than 0.16 or "
            "customized): run kb_upgrade.py or merge scripts/kb_ingest.py.new"
        )
    if step_id == "packs-stale" and not (root / "scripts" / "kb_reindex.py").is_file():
        return "scripts/kb_reindex.py is missing"
    return None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _sidecars(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not root.is_dir():
        return findings
    for path in root.rglob("*.new"):
        if any(part in _SKIP_SIDECAR_PARTS for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        findings.append(
            Finding(
                id=f"sidecar:{rel}",
                bucket="assisted",
                title=rel,
                detail="hanging upgrade sidecar — merge, then delete .new",
                source="sidecar",
                stage=2,
                fix="ask the agent to merge the sidecar into the live file",
            )
        )
    return findings


def _config_findings(root: Path) -> list[Finding]:
    """`heal:` that heal cannot stamp (flow style `heal: {…}`)."""
    text = _config_text(root)
    if not text or not _has_top_level_key(text, "heal"):
        return []
    try:
        kbc.config_set(text, "heal.last_run.at", "2000-01-01")
    except kbc.ConfigEditError as exc:
        return [
            Finding(
                id="heal-config-block-style",
                bucket="assisted",
                title="kb.config.yml heal: cannot be edited line by line",
                detail=str(exc),
                source="config",
                stage=1,
                fix=(
                    "rewrite heal: in block style (one key per line, as in "
                    "templates/kb.config.yml.template), then run "
                    "python3 scripts/kb_heal.py --apply auto"
                ),
            )
        ]
    return []


def _kb_docs_findings(root: Path) -> list[Finding]:
    return [
        Finding(
            id=f"kb-docs-dir:{name}",
            bucket="assisted",
            title=f"root-level {name} has local edits",
            detail=f"kb-docs/{name} is the copy kb_upgrade maintains",
            source="migration",
            stage=1,
            fix=(
                f"merge the local edits into kb-docs/{name} (or keep them in a note), "
                f"then delete the root-level {name}"
            ),
        )
        for name, state in _root_modules(root).items()
        if state == "customized"
    ]


def _crashed(source: str, exc: Exception, fix: str) -> list[Finding]:
    """A lint or doctor crash is one item; the rest of the plan still comes."""
    return [
        Finding(
            id=f"{source}:crashed",
            bucket="assisted",
            title=f"{source} stopped with an error",
            detail=f"{type(exc).__name__}: {exc}",
            source=source,
            stage=1,
            fix=fix,
        )
    ]


def _lint_findings(root: Path) -> list[Finding]:
    try:
        report = kb_lint.run_lint(root)
    except Exception as exc:  # noqa: BLE001 — one bad page must not stop heal
        return _crashed(
            "lint", exc, "run python3 scripts/kb_lint.py and fix the page it stops on"
        )
    out: list[Finding] = []
    seen: dict[str, int] = {}
    for issue in report.issues:
        if issue.severity == "info" or issue.check in _LINT_OWNED:
            continue
        path = str(issue.path)
        if kbc.is_archived(path):
            continue
        if issue.check in _TRIM_LINT:
            stage, bucket = 4, "human"
        elif issue.check in _CONTENT_LINT:
            stage, bucket = 5, "human"
        elif issue.check in _HYGIENE_LINT or issue.severity == "error":
            stage, bucket = 2, "assisted"
        else:
            continue
        # Two broken links in one page are two items, not one.
        base_id = f"lint:{issue.check}:{path}"
        seen[base_id] = seen.get(base_id, 0) + 1
        out.append(
            Finding(
                id=base_id if seen[base_id] == 1 else f"{base_id}#{seen[base_id]}",
                bucket=bucket,
                title=f"[{issue.check}] {path}",
                detail=issue.message,
                source="lint",
                stage=stage,
                fix="see kb-docs/09_LINT.md",
            )
        )
    return out


def _doctor_findings(root: Path) -> list[Finding]:
    try:
        # ephemeral_log: ignored since 0.16; an older kb_doctor.py (a partial
        # upgrade) would otherwise write a test entry to log.md.
        results = kb_doctor.run_all_checks(root, skip_nlp=True, ephemeral_log=True)
    except Exception as exc:  # noqa: BLE001 — a broken check must not stop heal
        return _crashed("doctor", exc, "run python3 scripts/kb_doctor.py and fix what it stops on")
    out: list[Finding] = []
    for item in results:
        if item.severity != "error":
            continue
        if item.name.startswith("heal:"):
            continue
        out.append(
            Finding(
                id=f"doctor:{item.name}",
                bucket="assisted",
                title=item.name,
                detail=item.message,
                source="doctor",
                stage=1,
                fix="python3 scripts/kb_doctor.py shows the details",
            )
        )
    return out


def collect_findings(
    root: Path,
    *,
    migrations_text: str | None = None,
    migrations_path: Path | None = None,
) -> list[Finding]:
    root = root.resolve()
    findings: list[Finding] = []
    seen: set[str] = set()

    def add(finding: Finding) -> None:
        if finding.id in seen:
            return
        seen.add(finding.id)
        findings.append(finding)

    text = load_migrations_text(
        migrations_text=migrations_text, migrations_path=migrations_path
    )
    registry = {step.id: step for step in (parse_migrations(text) if text else [])}

    # Every detector runs whatever the version: a bumped instructions_version
    # is not proof the contents were healed.
    for step_id, (bucket, stage, summary) in STEPS.items():
        hit = DETECT_BY_ID[step_id](root)
        if not hit:
            continue
        step = registry.get(step_id)
        detail = (step.detect if step and step.detect else summary)
        if isinstance(hit, str):
            detail = f"{detail} — found: {hit}"
        fix = step.fix if step and step.fix else ""
        if bucket == "auto":
            blocker = _auto_blocker(root, step_id)
            if blocker:
                bucket, detail = "assisted", f"{detail} — not applied automatically: {blocker}"
            elif not fix:
                fix = "deterministic apply (--apply auto)"
        add(
            Finding(
                id=step_id,
                bucket=bucket,
                title=step_id,
                detail=detail,
                source="migration",
                stage=stage,
                fix=fix,
            )
        )

    # A MIGRATIONS.md step without a detector is a manual step, listed while
    # the base's version is below the step's (and the step is not newer than
    # these scripts).
    base_version = _version_key(_heal_settings(root)["instructions_version"])
    engine_version = _version_key(kbc.ENGINE_VERSION)
    for step in registry.values():
        if step.id in STEPS:
            continue
        if not base_version < _version_key(step.version) <= engine_version:
            continue
        add(
            Finding(
                id=step.id,
                bucket="human",
                title=step.id,
                detail=f"{step.detect} (manual step from MIGRATIONS.md {step.version}; heal has no detector for it)",
                source="migration",
                stage=1,
                fix=step.fix,
            )
        )

    for finding in _config_findings(root) + _kb_docs_findings(root) + _sidecars(root):
        add(finding)
    for finding in _lint_findings(root):
        if finding.id.startswith("lint:invariants:AGENTS.md") and "agents-md-invariants" in seen:
            continue
        add(finding)
    for finding in _doctor_findings(root):
        add(finding)

    closed = measure_closed(root)
    for finding in findings:
        if finding.stage == 4 and not closed:
            finding.locked = True
    return findings


def current_stage(findings: list[Finding], configured: int, *, closed: bool) -> int:
    """The stage the base is in: the configured one, advanced past every stage
    with nothing open — never into stage 4 while the measure gate is locked."""
    stage = configured
    while stage < 5:
        if any(not f.locked and f.stage <= stage for f in findings):
            break
        if stage + 1 == 4 and not closed:
            break
        stage += 1
    return stage


# ---------------------------------------------------------------------------
# HEAL_PLAN.md
# ---------------------------------------------------------------------------


def plan_path(root: Path) -> Path:
    return root / "review" / "needs-heal" / HEAL_PLAN_NAME


def plan_id(findings: list[Finding]) -> str:
    joined = "\n".join(sorted(f.id for f in findings))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8]


def read_plan_summary(path: Path) -> dict[str, str] | None:
    """Fields of the `heal-summary` comment on the first line of a plan."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        return None
    match = SUMMARY_RE.search(first)
    return dict(re.findall(r"(\w+)=(\S+)", match.group("fields"))) if match else None


def plan_summary(root: Path, findings: list[Finding]) -> dict[str, Any]:
    settings = _heal_settings(root)
    summary: dict[str, Any] = {
        "version": kbc.ENGINE_VERSION,
        "plan_id": plan_id(findings),
        "stage": current_stage(findings, settings["stage"], closed=measure_closed(root)),
    }
    for bucket in ("auto", "assisted", "human"):
        summary[bucket] = sum(1 for f in findings if f.bucket == bucket)
    return summary


def summary_line(summary: dict[str, Any]) -> str:
    fields = " ".join(
        f"{key}={summary[key]}"
        for key in ("version", "plan_id", "stage", "auto", "assisted", "human")
    )
    return f"<!-- heal-summary: {fields} -->"


def _stage_label(stage: int) -> str:
    return f"stage {stage} {STAGE_NAMES.get(stage, '?')}"


def render_plan(
    root: Path,
    findings: list[Finding],
    *,
    previous: dict[str, str] | None = None,
) -> str:
    settings = _heal_settings(root)
    batch = settings["assisted_batch"]
    closed = measure_closed(root)
    summary = plan_summary(root, findings)
    stage = summary["stage"]
    # Locked items get their own section; listing them in a bucket too would
    # double-count them and read as work that can start now. Items of later
    # stages wait until the current stage is closed.
    open_items = [f for f in findings if not f.locked]
    now = [f for f in open_items if f.stage <= stage]
    later = [f for f in open_items if f.stage > stage]
    locked = [f for f in findings if f.locked]
    auto = [f for f in now if f.bucket == "auto"]
    assisted = [f for f in now if f.bucket == "assisted"]
    human = [f for f in now if f.bucket == "human"]
    shown, deferred = assisted[:batch], assisted[batch:]
    trim_gate = (
        "open"
        if closed
        else "locked (eval/QUESTIONS.md needs ## Q1. – ## Q3. filled in)"
    )
    stage_line = f"heal.stage: {stage} ({STAGE_NAMES.get(stage, '?')})"
    if stage != settings["stage"]:
        stage_line += (
            f" — kb.config.yml says {settings['stage']}; stages with nothing open "
            "are skipped and `--apply auto` records the new value"
        )
    lines = [
        summary_line(summary),
        f"# Heal plan — {_dt.date.today().isoformat()}",
        "",
        f"Catch-up from `instructions_version` {settings['instructions_version']} "
        f"(heal {kbc.ENGINE_VERSION}).",
        stage_line,
        f"assisted_batch: {batch}",
    ]
    same = bool(previous) and previous.get("plan_id") == summary["plan_id"]
    if previous and previous.get("plan_id"):
        lines.append(
            f"previous plan: {previous['plan_id']}"
            + (" — same open items" if same else "")
        )
    lines += [
        "",
        "## Summary",
        f"- auto: {len(auto)}",
        f"- assisted: {len(assisted)} (showing {len(shown)}, {len(deferred)} deferred)",
        f"- human: {len(human)}",
        f"- later stages: {len(later)}",
        f"- locked (stage 4 trim): {len(locked)}",
        f"- stage 4 trim gate: {trim_gate}",
        "",
    ]
    if not findings:
        lines += [
            "No findings. The base is in order.",
            "",
            '→ next: nothing to do — `!heal` ends here.',
            "",
        ]
        return "\n".join(lines)
    if same:
        lines += [
            "**Same open items as the previous plan.** If items were worked on "
            "since that plan (step 6 of kb-docs/18_HEAL.md), this is the "
            "stagnation brake: stop and show the owner what will not heal.",
            "",
        ]

    def dump(title: str, items: list[Finding], *, box: bool = True) -> None:
        lines.append(f"## {title}")
        if not items:
            lines.append("- (none)")
            lines.append("")
            return
        for item in items:
            lock = " *(locked until stage 3 measure is closed)*" if item.locked else ""
            mark = "- [ ] " if box else "- "
            lines.append(
                f"{mark}`{item.id}` — {item.title} · {_stage_label(item.stage)}{lock}"
            )
            if item.detail:
                lines.append(f"  - {item.detail}")
            if item.fix:
                lines.append(f"  - fix: {item.fix}")
        lines.append("")

    dump("auto", auto)
    dump("assisted", shown)
    if deferred:
        dump("assisted (deferred to later sessions)", deferred)
    dump("human", human)
    if later:
        dump(f"Later stages (start after stage {stage} is closed)", later, box=False)
    if locked:
        dump("Locked (stage 4 trim — wait for measure)", locked)
    lines.append('→ next: скажи агенту "!heal"')
    lines.append("")
    return "\n".join(lines)


def _refresh_status(root: Path) -> None:
    """Rewrite STATUS.md, whose heal line reads HEAL_PLAN.md (a no-op when
    status.enabled is false or the base has no kb_status.py)."""
    if not _config_path(root).is_file():
        return
    try:
        import kb_status  # optional: an older base has no kb_status.py

        cfg = kbc.load_config(root)
        if cfg.status_enabled:
            kb_status.write_status(root, cfg=cfg)
    except ImportError:
        return
    except Exception as exc:  # noqa: BLE001 — STATUS.md must not fail heal
        print(f"⚠️  [heal] STATUS.md not refreshed: {exc}", file=sys.stderr)


def _write_plan(root: Path, findings: list[Finding]) -> Path:
    dest = plan_path(root)
    previous = read_plan_summary(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    kbc.atomic_write_text(dest, render_plan(root, findings, previous=previous))
    return dest


def write_plan(
    root: Path,
    *,
    migrations_text: str | None = None,
    migrations_path: Path | None = None,
) -> Path:
    findings = collect_findings(
        root, migrations_text=migrations_text, migrations_path=migrations_path
    )
    return _write_plan(root, findings)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_auto(
    root: Path,
    *,
    migrations_text: str | None = None,
    migrations_path: Path | None = None,
    version: str | None = None,
) -> list[Finding]:
    root = root.resolve()
    findings = collect_findings(
        root, migrations_text=migrations_text, migrations_path=migrations_path
    )
    candidates = [
        finding
        for finding in findings
        if finding.bucket == "auto"
        and not finding.locked
        and finding.id in APPLY_BY_ID
    ]
    settings = _heal_settings(root)
    expected_version = version or settings["instructions_version"]
    backup = Backup(root)
    applied: list[Finding] = []
    stage_note: list[str] = []
    try:
        for finding in candidates:
            try:
                done = APPLY_BY_ID[finding.id](root, backup)
            except kbc.ConfigEditError as exc:
                print(f"[WARN] {finding.id} not applied: {exc}", file=sys.stderr)
                done = False
            if done:
                applied.append(finding)
        applied_ids = {item.id for item in applied}
        remaining = [f for f in findings if f.id not in applied_ids]
        stage = current_stage(remaining, settings["stage"], closed=measure_closed(root))
        last_run = settings["last_run"]
        stamp_current = (
            str(last_run.get("at") or "") == _dt.date.today().isoformat()
            and str(last_run.get("version") or "") == str(expected_version)
            and stage == settings["stage"]
        )
        if not stamp_current:
            try:
                _touch_last_run(
                    root,
                    version=version,
                    stage=stage if stage != settings["stage"] else None,
                    backup=backup,
                )
            except kbc.ConfigEditError as exc:
                print(f"[WARN] heal.last_run not stamped: {exc}", file=sys.stderr)
            else:
                if stage != settings["stage"]:
                    stage_note = [f"heal.stage {settings['stage']} → {stage}"]
    finally:
        snapshot = backup.close()
    if snapshot is None:
        return applied
    kbc.append_log(
        operation="heal",
        title="apply auto",
        details=([f"`{item.id}`" for item in applied] or ["(nothing to apply)"])
        + stage_note
        + [f"Backup: {BACKUP_ROOT}/{snapshot.name}"],
        root=root,
    )
    return applied


def summarize(findings: list[Finding], applied: list[Finding], stage: int) -> str:
    remaining_a = sum(
        1 for f in findings if f.bucket == "assisted" and not f.locked
    )
    remaining_h = sum(1 for f in findings if f.bucket == "human" and not f.locked)
    locked = sum(1 for f in findings if f.locked)
    tail = f" locked={locked}" if locked else ""
    return (
        f"Heal: applied {len(applied)} auto; remaining assisted={remaining_a} "
        f"human={remaining_h}{tail}; stage={stage} "
        f"({STAGE_NAMES.get(stage, '?')})\n"
        '→ next: скажи агенту "!heal"'
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — heal")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--plan", action="store_true", help="write HEAL_PLAN.md")
    parser.add_argument(
        "--json",
        action="store_true",
        help="with --plan: also print the plan summary and items as JSON",
    )
    parser.add_argument(
        "--apply",
        choices=("auto",),
        default=None,
        help="apply one bucket (only 'auto' is allowed)",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="undo the newest heal run (files edited since are kept)",
    )
    parser.add_argument("--verify", action="store_true", help="rollback if eval regressed")
    parser.add_argument("--migrations", type=Path, default=None)
    args = parser.parse_args(argv)

    root = (args.root or kbc.find_kb_root()).resolve()
    if _config_path(root).is_file():
        try:
            kbc.load_config(root)
        except Exception as exc:  # noqa: BLE001 — yaml.YAMLError or an unreadable file
            print(
                f"[ERROR] kb.config.yml is not valid YAML — fix it first:\n{exc}",
                file=sys.stderr,
            )
            return 3
    if args.rollback:
        result = restore_backup(root)
        if result is None:
            print(f"No heal run left to roll back in {BACKUP_ROOT}/")
            return 1
        print(describe_rollback(result))
        return 2 if result.kept or result.refused else 0
    if args.verify:
        print(verify(root))
        return 0
    if args.apply == "auto":
        applied = apply_auto(root, migrations_path=args.migrations)
        print(f"Applied {len(applied)} auto fix(es)")
        # HEAL_PLAN.md and STATUS.md still list what was just fixed.
        path = _write_plan(root, collect_findings(root, migrations_path=args.migrations))
        _refresh_status(root)
        print(f"Wrote {path}")
        return 0
    findings = collect_findings(root, migrations_path=args.migrations)
    path = _write_plan(root, findings)
    _refresh_status(root)
    if args.json:
        payload = plan_summary(root, findings)
        payload["items"] = [asdict(item) for item in findings]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
