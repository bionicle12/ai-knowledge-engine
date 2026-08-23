"""kb_common — shared utilities for AI Knowledge Engine reference scripts.

Designed to be imported by kb_ingest.py, kb_lint.py, kb_watch.py, kb_reflect.py,
kb_nlp_batch.py, kb_doctor.py.

No heavy dependencies are imported at module level — NLP libs are imported
lazily inside the functions that need them so the module loads fast.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    print(
        "[kb_common] PyYAML is required. Install: pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise


def _enable_utf8_console() -> None:
    """Make stdout/stderr UTF-8 safe so emoji output never crashes the run.

    On Windows the default console encoding is often a legacy code page (e.g.
    cp1251), which raises UnicodeEncodeError when scripts print status icons
    like ✅/⚠️/❌. We switch to UTF-8 with errors="replace" so output is always
    safe. Guarded for environments (e.g. pytest capture) where the stream can't
    be reconfigured.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc.startswith("utf"):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


_enable_utf8_console()


# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_FILENAME = "kb.config.yml"
DEFAULT_LOG_FILENAME = "log.md"
DEFAULT_LINT_REPORT_FILENAME = "lint-report.md"

KNOWLEDGE_DIRS = (
    "profile",
    "principles",
    "voice",
    "domain",
    "projects",
    "decisions",
    "playbooks",
    "insights",
    "opinions",
    "timelines",
    "routing",
    "open-questions",
    "_archive",
)

RAW_DIRS = (
    "documents",
    "reference",
    "work",
    "chats",
    "media",
    "personal-context",
    "unsorted",
)

ASSET_DIRS = ("documents", "presentations", "media", "images", "archives")

REVIEW_DIRS = (
    "needs-classification",
    "needs-ai-decision",
    "needs-redaction",
    "excluded-sensitive",
    "needs-merge",
    "needs-heal",
)

# Cross-base sync workspace (see 16_MERGE.md). Never indexed.
SYNC_ROOT = "sync"
SYNC_DIRS = ("inbox", "outbox", "applied", "backups", "reports")

PROCESSED_DIRS = (
    "markdown",
    "transcripts",
    "ocr",
    "tables",
    "extracted-metadata",
    "nlp-meta",
)

# Manual eval lite (iteration B). Never indexed. results/ holds before/after
# answer dumps; do not gitignore them — they are the measurement artifacts.
EVAL_ROOT = "eval"
EVAL_RESULTS_DIR = "results"

REQUIRED_INVARIANT_IDS = frozenset({"forbidden", "language"})

_INVARIANT_BLOCK_RE = re.compile(
    r"<!--\s*AI-KE:INVARIANT:BEGIN\s+id=\"([^\"]+)\"\s*-->"
    r"(.*?)"
    r"<!--\s*AI-KE:INVARIANT:END\s+id=\"\1\"\s*-->",
    re.DOTALL,
)
_INVARIANT_BEGIN_RE = re.compile(
    r"<!--\s*AI-KE:INVARIANT:BEGIN\s+id=\"([^\"]+)\"\s*-->"
)
_INVARIANT_END_RE = re.compile(
    r"<!--\s*AI-KE:INVARIANT:END\s+id=\"([^\"]+)\"\s*-->"
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def find_kb_root(start: Path | str | None = None) -> Path:
    """Walk up from `start` to find the directory containing kb.config.yml.

    Falls back to `start` itself if not found (e.g., during tests on a fixture).
    """
    p = Path(start or os.getcwd()).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / DEFAULT_CONFIG_FILENAME).is_file():
            return candidate
    return p


def kb_config_path(root: Path) -> Path:
    return root / DEFAULT_CONFIG_FILENAME


def log_path(root: Path) -> Path:
    return root / DEFAULT_LOG_FILENAME


def lint_report_path(root: Path) -> Path:
    return root / DEFAULT_LINT_REPORT_FILENAME


def posix_relpath(
    path: Path | str,
    start: Path | str | None = None,
    *,
    without_suffix: bool = False,
) -> str:
    """Return a forward-slash relative path for wikilinks and metadata."""
    result = Path(path)
    if start is not None:
        result = result.relative_to(Path(start))
    if without_suffix:
        result = result.with_suffix("")
    return result.as_posix()


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


@dataclass
class ModeProfile:
    name: str
    surprise_engine: str = "python"
    annotations_engine: str = "python"
    entity_resolution_engine: str = "python"
    importance_with_reasoning: bool = False
    reflection_trigger: str = "threshold+weekly"
    reflection_importance_threshold: int = 25
    reflection_min_interval_days: int = 7
    reflection_require_changes: bool = True
    reflection_max_insights_per_run: int = 3
    lint_level2_trigger: str = "manual"
    review_auto_process: bool = False


@dataclass
class KbConfig:
    raw: dict[str, Any]
    root: Path
    mode: str = "default"
    primary_language: str = "en"
    spacy_model: str = "en_core_web_md"
    spacy_model_fallback: str = "xx_ent_wiki_sm"
    complexity_threshold: float = 0.7
    fuzzy_match_threshold: float = 0.8
    keyword_top_n: int = 20
    skip_extensions: tuple[str, ...] = ()
    nlp_enabled: bool = True
    autorun: dict[str, Any] = field(default_factory=dict)
    indexer_output_path: str = ".repomix/output.xml"
    instructions_version: str = "0.0.0"
    media: dict[str, Any] = field(default_factory=dict)
    sync: dict[str, Any] = field(default_factory=dict)
    index: dict[str, Any] = field(default_factory=dict)

    @property
    def stt(self) -> dict[str, Any]:
        """Speech-to-text settings (media.stt in kb.config.yml)."""
        return (self.media or {}).get("stt", {}) or {}

    @property
    def ocr(self) -> dict[str, Any]:
        """OCR settings (media.ocr in kb.config.yml)."""
        return (self.media or {}).get("ocr", {}) or {}

    @property
    def archives(self) -> dict[str, Any]:
        """Archive-unpacking settings (media.archives in kb.config.yml)."""
        return (self.media or {}).get("archives", {}) or {}

    @property
    def sync_label(self) -> str:
        """Name this base carries into another one (sync.label)."""
        label = (self.sync or {}).get("label")
        if label and not str(label).startswith("{{"):
            return str(label)
        return (self.raw.get("knowledge_base", {}) or {}).get("name") or self.root.name

    @property
    def sync_export(self) -> dict[str, Any]:
        """Export defaults (sync.export in kb.config.yml)."""
        return (self.sync or {}).get("export", {}) or {}

    @property
    def sync_import(self) -> dict[str, Any]:
        """Import defaults (sync.import in kb.config.yml)."""
        return (self.sync or {}).get("import", {}) or {}

    def profile(self) -> ModeProfile:
        profiles = self.raw.get("mode_profiles", {})
        chosen = profiles.get(self.mode, {})
        prof = ModeProfile(name=self.mode)
        prof.surprise_engine = chosen.get("surprise", {}).get("engine", prof.surprise_engine)
        prof.annotations_engine = chosen.get("annotations", {}).get("engine", prof.annotations_engine)
        prof.entity_resolution_engine = chosen.get("entity_resolution", {}).get(
            "engine", prof.entity_resolution_engine
        )
        prof.importance_with_reasoning = chosen.get("importance_scoring", {}).get(
            "with_reasoning", prof.importance_with_reasoning
        )
        refl = chosen.get("reflection", {})
        prof.reflection_trigger = refl.get("trigger", prof.reflection_trigger)
        prof.reflection_importance_threshold = refl.get(
            "importance_threshold", prof.reflection_importance_threshold
        )
        prof.reflection_min_interval_days = refl.get(
            "min_interval_days", prof.reflection_min_interval_days
        )
        prof.reflection_require_changes = refl.get(
            "require_changes", prof.reflection_require_changes
        )
        prof.reflection_max_insights_per_run = int(
            refl.get(
                "max_insights_per_run", prof.reflection_max_insights_per_run
            )
        )
        lint = chosen.get("lint", {})
        prof.lint_level2_trigger = lint.get("level2_trigger", prof.lint_level2_trigger)
        prof.review_auto_process = lint.get("review_auto_process", prof.review_auto_process)
        return prof


def load_config(root: Path | None = None) -> KbConfig:
    root = root or find_kb_root()
    cfg_file = kb_config_path(root)
    if not cfg_file.is_file():
        # Return a minimal default config so kb_doctor and tests can run on
        # bare directories.
        return KbConfig(raw={}, root=root)
    with cfg_file.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    nlp = raw.get("nlp", {})
    cfg = KbConfig(
        raw=raw,
        root=root,
        mode=raw.get("knowledge_base", {}).get("mode", "default"),
        primary_language=raw.get("language_policy", {}).get("primary", "en"),
        spacy_model=nlp.get("spacy_model", "en_core_web_md"),
        spacy_model_fallback=nlp.get("spacy_model_fallback", "xx_ent_wiki_sm"),
        complexity_threshold=float(nlp.get("complexity_threshold", 0.7)),
        fuzzy_match_threshold=float(nlp.get("fuzzy_match_threshold", 0.8)),
        keyword_top_n=int(nlp.get("keyword_top_n", 20)),
        skip_extensions=tuple(nlp.get("skip_extensions", []) or ()),
        nlp_enabled=bool(nlp.get("enabled", True)),
        autorun=raw.get("autorun", {}) or {},
        indexer_output_path=raw.get("indexer", {}).get("output_path", ".repomix/output.xml"),
        instructions_version=raw.get("instructions_version", "0.0.0"),
        media=raw.get("media", {}) or {},
        sync=raw.get("sync", {}) or {},
        index=raw.get("index", {}) or {},
    )
    return cfg


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def compute_source_hash(filepath: Path | str, prefix_len: int = 16) -> str:
    """SHA-256 of file contents, truncated. Format: ``sha256:<hex>``."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()[:prefix_len]}"


# ---------------------------------------------------------------------------
# AI-KE:INVARIANT blocks (AGENTS.md)
# ---------------------------------------------------------------------------
# These wrappers mark text that no revision — human, !refactor, or an
# evolving agent — may silently drop. Upgrade never writes or overwrites
# them; lint errors if a required id is missing or markers are malformed.


def iter_invariant_blocks(text: str) -> list[tuple[str, int, int]]:
    """Return ``(id, start, end)`` for each well-formed INVARIANT span."""
    return [
        (match.group(1), match.start(), match.end())
        for match in _INVARIANT_BLOCK_RE.finditer(text)
    ]


def invariant_ids(text: str) -> set[str]:
    """Ids of well-formed (BEGIN+matching END) INVARIANT blocks."""
    return {block_id for block_id, _start, _end in iter_invariant_blocks(text)}


def strip_invariant_bodies(text: str) -> str:
    """Remove well-formed INVARIANT spans so lint can count the rest."""
    return _INVARIANT_BLOCK_RE.sub("", text)


def invariant_problems(text: str) -> list[str]:
    """Missing required ids and unmatched BEGIN/END markers."""
    problems: list[str] = []
    present = invariant_ids(text)
    for required in sorted(REQUIRED_INVARIANT_IDS):
        if required not in present:
            problems.append(f"missing invariant block id={required!r}")
    begins = _INVARIANT_BEGIN_RE.findall(text)
    ends = _INVARIANT_END_RE.findall(text)
    if len(begins) != len(present) or len(ends) != len(present):
        problems.append("malformed AI-KE:INVARIANT markers (BEGIN/END mismatch)")
    return problems


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(metadata_dict, body)``. Empty dict if no frontmatter."""
    # Files saved by Windows editors may start with a UTF-8 BOM; without this
    # the frontmatter regex silently fails and metadata is treated as empty.
    text = text.lstrip("﻿")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    body = text[m.end():]
    return meta, body


def render_frontmatter(meta: dict[str, Any], body: str) -> str:
    """Render metadata + body into a Markdown string with YAML frontmatter."""
    if not meta:
        return body
    serialized = yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    if not serialized.endswith("\n"):
        serialized += "\n"
    return f"---\n{serialized}---\n{body}"


def read_frontmatter_file(path: Path | str) -> tuple[dict[str, Any], str]:
    # utf-8-sig transparently strips a BOM when present and reads plain
    # UTF-8 unchanged otherwise.
    text = Path(path).read_text(encoding="utf-8-sig")
    return parse_frontmatter(text)


def write_frontmatter_file(path: Path | str, meta: dict[str, Any], body: str) -> None:
    Path(path).write_text(render_frontmatter(meta, body), encoding="utf-8")


# ---------------------------------------------------------------------------
# Content fingerprinting (cross-base sync — see 16_MERGE.md)
# ---------------------------------------------------------------------------

# Frontmatter keys that change without the knowledge itself changing. They are
# excluded from the fingerprint so a page read on one machine is not treated as
# "modified" relative to the same page on another machine.
VOLATILE_FRONTMATTER_KEYS = (
    "last_accessed",
    "access_count",
    "imported_at",
    "merged_from",
    "merge_bundle",
    "merge_source_fingerprint",
)


def normalize_for_fingerprint(text: str) -> str:
    """Return a canonical form of a knowledge page for content comparison.

    **The body is the knowledge; frontmatter is bookkeeping.** Only the body is
    normalized here — line endings unified, trailing whitespace stripped per
    line, trailing blank lines collapsed. Two pages with the same normalized
    body carry the same knowledge even when their tags, importance or access
    counters drifted apart on two machines; that metadata is merged
    non-destructively rather than treated as a conflict.
    """
    _, body = parse_frontmatter(text)
    body_lines = [ln.rstrip() for ln in body.replace("\r\n", "\n").split("\n")]
    while body_lines and not body_lines[-1]:
        body_lines.pop()
    return "\n".join(body_lines)


def stable_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Frontmatter without the keys that drift on their own."""
    return {k: v for k, v in (meta or {}).items() if k not in VOLATILE_FRONTMATTER_KEYS}


def content_fingerprint(text: str, prefix_len: int = 16) -> str:
    """Stable ``sha256:<hex>`` fingerprint of a page's *knowledge content*."""
    digest = hashlib.sha256(
        normalize_for_fingerprint(text).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest[:prefix_len]}"


def fingerprint_file(path: Path | str, prefix_len: int = 16) -> str:
    return content_fingerprint(
        Path(path).read_text(encoding="utf-8-sig", errors="replace"), prefix_len
    )


# ---------------------------------------------------------------------------
# Sync workspace paths (cross-base import/export)
# ---------------------------------------------------------------------------


def sync_dir(root: Path, name: str = "") -> Path:
    """Path inside the ``sync/`` workspace (``sync/inbox`` etc.)."""
    base = root / SYNC_ROOT
    return base / name if name else base


def ensure_sync_dirs(root: Path) -> Path:
    """Create the ``sync/`` workspace. Idempotent."""
    base = ensure_dir(sync_dir(root))
    for sub in SYNC_DIRS:
        ensure_dir(base / sub)
    readme = base / "README.md"
    if not readme.exists():
        readme.write_text(
            "# sync/ — cross-base import & export\n\n"
            "Workspace for merging two deployments of this knowledge base\n"
            "(see `16_MERGE.md`). Never indexed.\n\n"
            "| Folder | What lives here |\n"
            "|--------|-----------------|\n"
            "| `inbox/` | Drop bundles (`.zip`) from another base here, then run import |\n"
            "| `outbox/` | Bundles produced by export |\n"
            "| `applied/` | Bundles already imported |\n"
            "| `backups/` | Pre-import snapshots of every file the import touched |\n"
            "| `reports/` | Per-import merge reports |\n",
            encoding="utf-8",
        )
    return base


def timestamp_slug() -> str:
    """``YYYY-MM-DDTHH-MM-SS`` — filesystem-safe, sortable."""
    return _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


# ---------------------------------------------------------------------------
# Slugify
# ---------------------------------------------------------------------------


def slugify(text: str, max_len: int = 60) -> str:
    """Best-effort slugifier. Uses python-slugify if available, else a simple ASCII fallback."""
    try:
        from slugify import slugify as _ext_slugify  # type: ignore[import-untyped]

        return _ext_slugify(text, max_length=max_len) or "unnamed"
    except ImportError:  # pragma: no cover
        s = text.lower()
        s = re.sub(r"[^a-z0-9]+", "-", s)
        s = re.sub(r"-+", "-", s).strip("-")
        return (s[:max_len] or "unnamed").strip("-") or "unnamed"


def stable_filename(
    *, original_name: str, date: _dt.date | None = None, ext: str | None = None
) -> str:
    """Build ``YYYY-MM-DD__short-slug.ext`` (or ``unknown-date__...``)."""
    base = Path(original_name).stem
    suffix = ext if ext is not None else Path(original_name).suffix
    if not suffix.startswith(".") and suffix:
        suffix = f".{suffix}"
    slug = slugify(base)
    date_part = date.isoformat() if date else "unknown-date"
    return f"{date_part}__{slug}{suffix}"


# ---------------------------------------------------------------------------
# Logging (append-only log.md)
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Local time with timezone offset, ISO-8601."""
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def append_log(
    *,
    operation: str,
    title: str,
    details: list[str] | None = None,
    root: Path | None = None,
) -> Path:
    """Append a structured entry to log.md. See 10_LOG.md for the format."""
    root = root or find_kb_root()
    p = log_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if not p.exists():
        lines.append("# Operations Log\n")
    else:
        lines.append("")
    lines.append(f"## [{now_iso()}] {operation} | {title}")
    for d in details or []:
        lines.append(f"- {d}")
    lines.append("")
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return p


# ---------------------------------------------------------------------------
# Filesystem walking
# ---------------------------------------------------------------------------


def iter_files(root: Path, *, suffixes: Iterable[str] | None = None) -> Iterator[Path]:
    """Iterate files under root, optionally filtered by suffix (case-insensitive)."""
    suffix_set = {s.lower() for s in suffixes} if suffixes else None
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if suffix_set is None or p.suffix.lower() in suffix_set:
            yield p


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def write_json(path: Path | str, data: Any) -> None:
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Wikilinks
# ---------------------------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+?)(?:\|[^\]]+?)?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    """Return list of wikilink targets in `text`. Aliases (``[[a|b]]``) → ``a``."""
    return _WIKILINK_RE.findall(text)


def extract_wikilinks_with_context(text: str) -> list[tuple[str, str]]:
    """Return ``(target, source_line)`` for each wikilink, in document order.

    ``source_line`` is the stripped line containing the link's opening
    brackets — enough context to show *why* one page links to another.
    Target order matches :func:`extract_wikilinks` exactly.
    """
    results: list[tuple[str, str]] = []
    for match in _WIKILINK_RE.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.start())
        if line_end == -1:
            line_end = len(text)
        results.append((match.group(1), text[line_start:line_end].strip()))
    return results


def scan_knowledge_slugs(knowledge_dir: Path) -> dict[str, list[Path]]:
    """Map slug (filename without .md) → list of paths.

    Multiple paths means duplicate slugs across subfolders (caller decides
    how to disambiguate).
    """
    out: dict[str, list[Path]] = {}
    if not knowledge_dir.is_dir():
        return out
    for p in knowledge_dir.rglob("*.md"):
        slug = p.stem
        out.setdefault(slug, []).append(p)
    return out


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


def detect_python_executable() -> str:
    """Return the python executable to invoke (prefer venv if active)."""
    return sys.executable


# ---------------------------------------------------------------------------
# Cross-platform tool discovery
# ---------------------------------------------------------------------------


def find_ffmpeg() -> str | None:
    """Locate an ffmpeg binary, cross-platform.

    Tries ``shutil.which`` first, then a list of common install locations that
    are frequently *missing* from the PATH that GUI apps (IDEs) hand to their
    child processes. The classic case is Homebrew on Apple Silicon, where
    ``/opt/homebrew/bin`` is not on a launchd-inherited PATH — so ``ffmpeg``
    "is installed" yet the agent's subprocess can't find it.

    Returns the resolved path, or ``None`` if no ffmpeg is found.

    Note: the default STT backend (faster-whisper) does NOT need ffmpeg — it
    decodes audio via the bundled PyAV libraries. ffmpeg is only relevant for
    the optional openai-whisper backend.
    """
    import shutil

    found = shutil.which("ffmpeg")
    if found:
        return found

    candidates: list[str] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        candidates += [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe") if local else "",
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        ]
    else:
        candidates += [
            "/opt/homebrew/bin/ffmpeg",  # macOS Apple Silicon (Homebrew)
            "/usr/local/bin/ffmpeg",     # macOS Intel (Homebrew) / Linux
            "/usr/bin/ffmpeg",           # Linux
            "/opt/local/bin/ffmpeg",     # MacPorts
        ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def os_install_hint(tool: str) -> str:
    """Return a per-OS install command hint for an optional system tool."""
    system = sys.platform
    table = {
        "ffmpeg": {
            "darwin": "brew install ffmpeg",
            "linux": "sudo apt install -y ffmpeg   # or your distro's package manager",
            "win32": "winget install Gyan.FFmpeg",
        },
        "tesseract": {
            "darwin": "brew install tesseract",
            "linux": "sudo apt install -y tesseract-ocr",
            "win32": "winget install UB-Mannheim.TesseractOCR   # then add to PATH",
        },
    }
    per_tool = table.get(tool, {})
    if system.startswith("win"):
        return per_tool.get("win32", f"install {tool}")
    if system == "darwin":
        return per_tool.get("darwin", f"install {tool}")
    return per_tool.get("linux", f"install {tool}")


__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_LOG_FILENAME",
    "DEFAULT_LINT_REPORT_FILENAME",
    "KNOWLEDGE_DIRS",
    "RAW_DIRS",
    "ASSET_DIRS",
    "REVIEW_DIRS",
    "PROCESSED_DIRS",
    "EVAL_ROOT",
    "EVAL_RESULTS_DIR",
    "REQUIRED_INVARIANT_IDS",
    "iter_invariant_blocks",
    "invariant_ids",
    "strip_invariant_bodies",
    "invariant_problems",
    "ModeProfile",
    "KbConfig",
    "find_kb_root",
    "kb_config_path",
    "log_path",
    "lint_report_path",
    "posix_relpath",
    "load_config",
    "compute_source_hash",
    "parse_frontmatter",
    "render_frontmatter",
    "read_frontmatter_file",
    "write_frontmatter_file",
    "slugify",
    "stable_filename",
    "now_iso",
    "append_log",
    "iter_files",
    "ensure_dir",
    "write_json",
    "read_json",
    "extract_wikilinks",
    "extract_wikilinks_with_context",
    "scan_knowledge_slugs",
    "print_err",
    "detect_python_executable",
    "find_ffmpeg",
    "os_install_hint",
]
