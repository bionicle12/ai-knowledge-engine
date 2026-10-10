"""kb_common — shared utilities for AI Knowledge Engine reference scripts.

Designed to be imported by every ``scripts/kb_*.py``. Run directly,
``python3 scripts/kb_common.py --version`` prints the engine version (used to
fill ``{{KB_INSTRUCTIONS_VERSION}}`` at deploy time; works before PyYAML is
installed).

No heavy dependencies are imported at module level — NLP libs are imported
lazily inside the functions that need them so the module loads fast.
"""
from __future__ import annotations

import argparse
import bisect
import codecs
import contextlib
import copy
import datetime as _dt
import errno
import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    if __name__ != "__main__":
        print(
            "[kb_common] PyYAML is required. Install: pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise
    # `python3 kb_common.py --version` must work before `pip install`.
    yaml = None  # type: ignore[assignment]


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

# The engine version this copy of the scripts belongs to. Mirrors the repo
# VERSION file (a test keeps them equal).
ENGINE_VERSION = "0.16.0"

DEFAULT_CONFIG_FILENAME = "kb.config.yml"
DEFAULT_LOG_FILENAME = "log.md"
DEFAULT_LINT_REPORT_FILENAME = "lint-report.md"

# Machine-local caches, locks and hook logs. Never versioned, never indexed.
STATE_DIR = ".kb-state"
# Runtime instruction modules copied into a deployed base (NN_*.md, README.md).
KB_DOCS_DIR = "kb-docs"

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

# Cross-base sync workspace (see kb-docs/16_MERGE.md). Never indexed.
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

LIFECYCLES = ("permanent", "evolving", "temporal")

# Code defaults for kb.config.yml keys. A base whose config lacks a key gets
# exactly these values (templates/kb.config.yml.template ships the same ones).
DEFAULT_INGEST_IGNORE_GLOBS = (
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "~$*",
    "._*",
    "*.part",
    "*.crdownload",
    "*.tmp",
    "*.swp",
)
DEFAULT_REDACT_CATEGORIES = ("chats", "personal-context")
DEFAULT_LIFECYCLE_BY_FOLDER = {
    "decisions": "permanent",
    "profile": "permanent",
    "principles": "permanent",
}
DEFAULT_WATCH_DIRS = ("raw/*/unsorted/", "knowledge/")

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


def resolve_under(base: Path | str, candidate: Path | str) -> Path | None:
    """Resolve `candidate` (relative paths are taken relative to `base`).

    Returns the real path when it stays inside `base` after following every
    symlink, else ``None``. Unresolvable paths (loops, NUL bytes) → ``None``.
    """
    try:
        base_path = Path(base)
        base_real = base_path.resolve()
        cand = Path(candidate)
        if not cand.is_absolute():
            cand = base_path / cand
        real = cand.resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if real == base_real or real.is_relative_to(base_real):
        return real
    return None


def _posix_parts(rel_posix: Path | str) -> list[str]:
    return [
        part
        for part in str(rel_posix).replace("\\", "/").split("/")
        if part and part != "."
    ]


def is_archived(rel_posix: Path | str) -> bool:
    """True when any path segment is ``_archive``."""
    return "_archive" in _posix_parts(rel_posix)


def is_generated(meta: Any) -> bool:
    """True for pages written by a script (``generated_by:`` is set)."""
    return isinstance(meta, dict) and bool(meta.get("generated_by"))


def state_dir(root: Path | str) -> Path:
    """``<root>/.kb-state/`` — created on demand, ignores itself in git."""
    base = Path(root) / STATE_DIR
    base.mkdir(parents=True, exist_ok=True)
    ignore = base / ".gitignore"
    if not ignore.exists():
        try:
            ignore.write_text(
                "# Machine-local state (kb_common.state_dir). Never versioned.\n*\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return base


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------

# A few hundred bytes of nested aliases ("billion laughs") explode in every
# consumer that walks the data (JSON for the viewer, lint, export). Documents
# with more aliases than this, or whose aliases expand beyond
# MAX_YAML_EXPANDED_NODES nodes, are refused.
MAX_YAML_ALIASES = 100
MAX_YAML_EXPANDED_NODES = 100_000

# libyaml's CSafeLoader is ~2x faster than the pure-Python SafeLoader.
YAML_LOADER = getattr(yaml, "CSafeLoader", None) or getattr(yaml, "SafeLoader", None)
# But libyaml composes nested collections by unbounded C recursion: ~30 000
# nested `[` (60 KB) overflow the C stack and kill the process with SIGSEGV,
# which no `except` can catch. yaml_load therefore refuses documents nesting
# deeper than MAX_YAML_DEPTH levels before libyaml composes them; 200 levels
# fit a 256 KiB thread stack with room to spare, and no real frontmatter or
# config nests beyond ~10. Every level needs one of the
# _NESTING_INDICATORS, so documents with fewer of them skip the check.
MAX_YAML_DEPTH = 200
_NESTING_INDICATORS = "[{-?:"
_NESTING_INDICATOR_BYTES = tuple(ch.encode() for ch in _NESTING_INDICATORS)


def _yaml_children(node: Any) -> list[Any]:
    if isinstance(node, yaml.SequenceNode):
        return list(node.value)
    if isinstance(node, yaml.MappingNode):
        return [item for pair in node.value for item in pair]
    return []


def _check_yaml_aliases(root: Any) -> None:
    """Raise :class:`yaml.YAMLError` for alias-heavy, recursive or exploding
    node graphs. An alias is a node object met a second time."""
    sizes: dict[int, int] = {}  # id(node) -> expanded node count
    active: set[int] = set()
    aliases = 0
    stack: list[tuple[Any, bool]] = [(root, False)]
    while stack:
        node, finished = stack.pop()
        key = id(node)
        if finished:
            active.discard(key)
            sizes[key] = 1 + sum(sizes[id(child)] for child in _yaml_children(node))
            if sizes[key] > MAX_YAML_EXPANDED_NODES:
                raise yaml.YAMLError(
                    f"aliases expand to more than {MAX_YAML_EXPANDED_NODES} nodes"
                )
        elif key in active:
            raise yaml.YAMLError("recursive alias")
        elif key in sizes:
            aliases += 1
            if aliases > MAX_YAML_ALIASES:
                raise yaml.YAMLError(f"more than {MAX_YAML_ALIASES} aliases")
        else:
            active.add(key)
            stack.append((node, True))
            stack.extend((child, False) for child in _yaml_children(node))


def _check_yaml_depth(text: str | bytes) -> None:
    """Raise :class:`yaml.YAMLError` when `text` nests deeper than
    :data:`MAX_YAML_DEPTH`. libyaml's event parser is iterative, so this
    pass cannot crash; it stops at the first level too deep."""
    if YAML_LOADER is yaml.SafeLoader:
        return  # pure Python: deep nesting raises RecursionError (→ YAMLError)
    indicators = _NESTING_INDICATOR_BYTES if isinstance(text, bytes) else _NESTING_INDICATORS
    if sum(text.count(mark) for mark in indicators) <= MAX_YAML_DEPTH:  # type: ignore[arg-type]
        return
    parser = YAML_LOADER(text)
    depth = 0
    try:
        while parser.check_event():
            event = parser.get_event()
            if isinstance(event, (yaml.SequenceStartEvent, yaml.MappingStartEvent)):
                depth += 1
                if depth > MAX_YAML_DEPTH:
                    raise yaml.YAMLError(f"nested deeper than {MAX_YAML_DEPTH} levels")
            elif isinstance(event, (yaml.SequenceEndEvent, yaml.MappingEndEvent)):
                depth -= 1
    finally:
        parser.dispose()


def yaml_load(text: str | bytes) -> Any:
    """Parse one YAML document safely and fast (:data:`YAML_LOADER`).

    Every failure — syntax, a bad value such as ``2026-13-45``, the alias
    limits, nesting deeper than :data:`MAX_YAML_DEPTH` — raises
    :class:`yaml.YAMLError`.
    """
    try:
        _check_yaml_depth(text)
        loader = YAML_LOADER(text)
    except (ValueError, TypeError) as exc:  # a lone surrogate libyaml cannot encode
        raise yaml.YAMLError(f"invalid YAML text: {exc}") from exc
    try:
        if (b"*" if isinstance(text, bytes) else "*") not in text:
            return loader.get_single_data()
        node = loader.get_single_node()
        if node is None:
            return None
        _check_yaml_aliases(node)
        return loader.construct_document(node)
    except yaml.YAMLError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise yaml.YAMLError(f"invalid YAML value: {exc}") from exc
    finally:
        loader.dispose()


def _one_line(exc: BaseException, limit: int = 200) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    # 0.16 keys (templates/kb.config.yml.template ships the same defaults).
    ingest_ignore_globs: tuple[str, ...] = DEFAULT_INGEST_IGNORE_GLOBS
    ingest_max_file_mb: float = 200.0
    ingest_duplicates_dir: str = "raw/_duplicates"
    archives_max_total_mb: float = 500.0
    archives_max_member_mb: float = 200.0
    privacy_require_redaction_for_chats: bool = True
    privacy_redact_categories: tuple[str, ...] = DEFAULT_REDACT_CATEGORIES
    privacy_secret_scan: bool = True
    lifecycle_default: str = "evolving"
    lifecycle_stale_warning_days: int = 30
    lifecycle_by_folder: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_LIFECYCLE_BY_FOLDER)
    )
    log_rotation_threshold: int = 1000
    log_archive_dir: str = "log-archive"
    index_repomix_version: str = "1.14.0"
    index_npx_fallback: bool = True
    status_enabled: bool = True
    status_file: str = "STATUS.md"
    autorun_watch_enabled: bool = True
    autorun_watch_dirs: tuple[str, ...] = DEFAULT_WATCH_DIRS
    autorun_auto_nlp: bool = True
    autorun_auto_lint_on_change: bool = True
    autorun_auto_reindex_on_change: bool = True
    autorun_consolidation_on_reindex: bool = True

    @property
    def stt(self) -> dict[str, Any]:
        """Speech-to-text settings (media.stt in kb.config.yml)."""
        return _section(self.media, "stt")

    @property
    def ocr(self) -> dict[str, Any]:
        """OCR settings (media.ocr in kb.config.yml)."""
        return _section(self.media, "ocr")

    @property
    def archives(self) -> dict[str, Any]:
        """Archive-unpacking settings (media.archives in kb.config.yml)."""
        return _section(self.media, "archives")

    @property
    def sync_label(self) -> str:
        """Name this base carries into another one (sync.label)."""
        label = (self.sync or {}).get("label")
        if label and not str(label).startswith("{{"):
            return str(label)
        return _section(self.raw, "knowledge_base").get("name") or self.root.name

    @property
    def sync_export(self) -> dict[str, Any]:
        """Export defaults (sync.export in kb.config.yml)."""
        return _section(self.sync, "export")

    @property
    def sync_import(self) -> dict[str, Any]:
        """Import defaults (sync.import in kb.config.yml)."""
        return _section(self.sync, "import")

    def profile(self) -> ModeProfile:
        chosen = _section(self.raw, "mode_profiles", self.mode)
        prof = ModeProfile(name=self.mode)
        prof.surprise_engine = _section(chosen, "surprise").get(
            "engine", prof.surprise_engine
        )
        prof.annotations_engine = _section(chosen, "annotations").get(
            "engine", prof.annotations_engine
        )
        prof.entity_resolution_engine = _section(chosen, "entity_resolution").get(
            "engine", prof.entity_resolution_engine
        )
        prof.importance_with_reasoning = _section(chosen, "importance_scoring").get(
            "with_reasoning", prof.importance_with_reasoning
        )
        refl = _section(chosen, "reflection")
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
        lint = _section(chosen, "lint")
        prof.lint_level2_trigger = lint.get("level2_trigger", prof.lint_level2_trigger)
        prof.review_auto_process = lint.get("review_auto_process", prof.review_auto_process)
        return prof


def _section(data: Any, *names: str) -> dict[str, Any]:
    """Nested mapping at ``data[names[0]][names[1]]…``; ``{}`` if absent or not a mapping."""
    current = data
    for name in names:
        current = current.get(name) if isinstance(current, dict) else None
    return current if isinstance(current, dict) else {}


def _opt(section: dict[str, Any], key: str, default: Any) -> Any:
    """``section[key]`` as the type of `default`; `default` when the key is
    missing, null or unusable (a hand-edited config must never crash)."""
    value = section.get(key)
    if value is None:
        return default
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(value, bool):
        return default
    if isinstance(default, tuple):
        if isinstance(value, str):
            return (value,)
        return tuple(str(v) for v in value if v is not None) if isinstance(value, list) else default
    if isinstance(default, dict):
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else default
    if isinstance(value, (dict, list)):
        return default
    try:
        converted = type(default)(value)
    except (TypeError, ValueError, OverflowError):  # OverflowError: int(.inf)
        return default
    if isinstance(converted, float) and not math.isfinite(converted):
        return default  # .nan / .inf would silently disable every size limit
    return converted


def load_config(root: Path | None = None) -> KbConfig:
    """Read ``kb.config.yml``; every key missing from it gets its code default.

    Raises :class:`yaml.YAMLError` for invalid YAML or a non-mapping document.
    """
    root = root or find_kb_root()
    cfg_file = kb_config_path(root)
    if not cfg_file.is_file():
        # Return a minimal default config so kb_doctor and tests can run on
        # bare directories.
        return KbConfig(raw={}, root=root)
    raw = yaml_load(cfg_file.read_text(encoding="utf-8-sig"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise yaml.YAMLError(f"{cfg_file}: top level is not a mapping")
    nlp = _section(raw, "nlp")
    ingest = _section(raw, "ingest")
    archives = _section(raw, "media", "archives")
    privacy = _section(raw, "privacy")
    lifecycle = _section(raw, "lifecycle")
    logging_cfg = _section(raw, "logging")
    index = _section(raw, "index")
    status = _section(raw, "status")
    autorun = _section(raw, "autorun")
    d = KbConfig(raw={}, root=root)  # the code defaults
    return KbConfig(
        raw=raw,
        root=root,
        mode=_opt(_section(raw, "knowledge_base"), "mode", d.mode),
        primary_language=_opt(_section(raw, "language_policy"), "primary", d.primary_language),
        spacy_model=_opt(nlp, "spacy_model", d.spacy_model),
        spacy_model_fallback=_opt(nlp, "spacy_model_fallback", d.spacy_model_fallback),
        complexity_threshold=_opt(nlp, "complexity_threshold", d.complexity_threshold),
        fuzzy_match_threshold=_opt(nlp, "fuzzy_match_threshold", d.fuzzy_match_threshold),
        keyword_top_n=_opt(nlp, "keyword_top_n", d.keyword_top_n),
        skip_extensions=_opt(nlp, "skip_extensions", d.skip_extensions),
        nlp_enabled=_opt(nlp, "enabled", d.nlp_enabled),
        autorun=autorun,
        indexer_output_path=_opt(_section(raw, "indexer"), "output_path", d.indexer_output_path),
        instructions_version=_opt(raw, "instructions_version", d.instructions_version),
        media=_section(raw, "media"),
        sync=_section(raw, "sync"),
        index=index,
        ingest_ignore_globs=_opt(ingest, "ignore_globs", d.ingest_ignore_globs),
        ingest_max_file_mb=_opt(ingest, "max_file_mb", d.ingest_max_file_mb),
        ingest_duplicates_dir=_opt(ingest, "duplicates_dir", d.ingest_duplicates_dir),
        archives_max_total_mb=_opt(archives, "max_total_mb", d.archives_max_total_mb),
        archives_max_member_mb=_opt(archives, "max_member_mb", d.archives_max_member_mb),
        privacy_require_redaction_for_chats=_opt(
            privacy, "require_redaction_for_chats", d.privacy_require_redaction_for_chats
        ),
        privacy_redact_categories=_opt(privacy, "redact_categories", d.privacy_redact_categories),
        privacy_secret_scan=_opt(privacy, "secret_scan", d.privacy_secret_scan),
        lifecycle_default=_opt(lifecycle, "default", d.lifecycle_default),
        lifecycle_stale_warning_days=_opt(
            lifecycle, "stale_warning_days", d.lifecycle_stale_warning_days
        ),
        lifecycle_by_folder=_opt(lifecycle, "by_folder", d.lifecycle_by_folder),
        log_rotation_threshold=_opt(logging_cfg, "rotation_threshold", d.log_rotation_threshold),
        log_archive_dir=_opt(logging_cfg, "archive_dir", d.log_archive_dir),
        index_repomix_version=_opt(index, "repomix_version", d.index_repomix_version),
        index_npx_fallback=_opt(index, "npx_fallback", d.index_npx_fallback),
        status_enabled=_opt(status, "enabled", d.status_enabled),
        status_file=_opt(status, "file", d.status_file),
        autorun_watch_enabled=_opt(autorun, "watch_enabled", d.autorun_watch_enabled),
        autorun_watch_dirs=_opt(autorun, "watch_dirs", d.autorun_watch_dirs),
        autorun_auto_nlp=_opt(autorun, "auto_nlp", d.autorun_auto_nlp),
        autorun_auto_lint_on_change=_opt(
            autorun, "auto_lint_on_change", d.autorun_auto_lint_on_change
        ),
        autorun_auto_reindex_on_change=_opt(
            autorun, "auto_reindex_on_change", d.autorun_auto_reindex_on_change
        ),
        autorun_consolidation_on_reindex=_opt(
            autorun, "consolidation_on_reindex", d.autorun_consolidation_on_reindex
        ),
    )


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
# Secrets: credential-looking strings (D10), scanned by kb_ingest (incoming
# files) and kb_lint (knowledge/ pages). Only kinds and line numbers are ever
# reported — never the matched value. Every pattern runs in linear time
# (bounded, atomic quantifiers): the scan must not stall ingest, which holds
# the pipeline lock, whatever the file holds.
# ---------------------------------------------------------------------------

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("Stripe key", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    (
        "OpenAI-style API key",
        re.compile(r"\bsk-(?:(?:proj|ant|svcacct)-[A-Za-z0-9_-]{20,}|[A-Za-z0-9]{20,})"),
    ),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ ){0,4}PRIVATE KEY(?: BLOCK)?-----")),
    (
        # A key name (one run of [\w.-], up to 128 chars, optionally quoted as
        # in JSON/YAML) holding password/passwd/secret, then `:` or `=` and a
        # value that is not a boolean/null or a $VAR / {{ template }} reference.
        "password/secret assignment",
        re.compile(
            r"(?i)(?<![\w.-])(?=[\w.-]{0,64}?(?:password|passwd|secret)(?![a-z]))"
            r"(?>[\w.-]{1,128})[\"']?[ \t]*[:=][ \t]*[\"']?"
            r"(?!(?:true|false|null|none|yes|no)\b)(?![$%{<])[^\s\"']{4,}"
        ),
    ),
)


def find_secrets(text: str) -> list[str]:
    """Kinds of credential-looking strings in *text* with their line numbers
    (e.g. ``"GitHub token (line 3)"``) — never the values themselves."""
    found: list[str] = []
    for kind, pattern in SECRET_PATTERNS:
        lines: list[int] = []
        line, pos = 1, 0
        for match in pattern.finditer(text):
            line += text.count("\n", pos, match.start())
            pos = match.start()
            if line not in lines:
                lines.append(line)
                if len(lines) > 5:
                    break
        if lines:
            shown = ", ".join(str(n) for n in lines[:5]) + (", …" if len(lines) > 5 else "")
            found.append(f"{kind} (line{'s' if len(lines) > 1 else ''} {shown})")
    return found



# ---------------------------------------------------------------------------
# Text decoding
# ---------------------------------------------------------------------------

# High bytes that are the same punctuation in cp1251 and cp1252 (quotes,
# dashes, «», №/¹, nbsp, …): no evidence for either code page.
_NEUTRAL_HIGH_BYTES = frozenset(
    b"\x82\x84\x85\x86\x87\x89\x8b\x91\x92\x93\x94\x95\x96\x97\x99\x9b"
    b"\xa0\xa6\xa7\xa9\xab\xac\xad\xae\xb0\xb1\xb5\xb6\xb7\xb9\xbb"
)
_LETTERISH = b"".join(
    re.escape(bytes([byte])) for byte in range(0x80, 0x100) if byte not in _NEUTRAL_HIGH_BYTES
)
_HIGH_LETTER_RE = re.compile(b"[" + _LETTERISH + b"]")
# Cyrillic letters in cp1251: А..я (0xC0-0xFF), Ё (0xA8), ё (0xB8).
_CP1251_LETTER_RE = re.compile(rb"[\xc0-\xff\xa8\xb8]")
_HIGH_TOUCHING_ASCII_LETTER_RE = re.compile(
    b"(?<=[A-Za-z])[" + _LETTERISH + b"]|[" + _LETTERISH + b"](?=[A-Za-z])"
)
# C0 control bytes other than \t \n \f \r: absent from real text files, but
# every other byte of BOM-less UTF-16 (the high byte of ASCII and Cyrillic).
_CONTROL_BYTES = bytes(byte for byte in range(0x20) if byte not in b"\t\n\x0c\r")
_CONTROL_CHAR_RE = re.compile("[\x00-\x08\x0b\x0e-\x1f]")
_STRAY_BYTES_RE = re.compile("[\udc80-\udcff]+")
_CYRILLIC_RE = re.compile("[\u0400-\u04ff]")


def _looks_cp1251(data: bytes) -> bool:
    """Russian cp1251 text: its letter bytes are Cyrillic letters forming
    whole words. Western cp1252 text puts accented letters *inside* ASCII
    words. Punctuation shared by both code pages proves nothing."""
    sample = data[: 1 << 20]
    letters = len(_HIGH_LETTER_RE.findall(sample))
    return (
        letters > 0
        and len(_CP1251_LETTER_RE.findall(sample)) >= 0.7 * letters
        and len(_HIGH_TOUCHING_ASCII_LETTER_RE.findall(sample)) <= 0.2 * letters
    )


def _bomless_utf16(data: bytes) -> tuple[str, str] | None:
    """UTF-16 without a BOM: one byte of each pair is mostly a control byte
    (0x00 for ASCII, 0x04 for Cyrillic)."""
    if len(data) < 4 or len(data) % 2:
        return None
    sample = data[: 1 << 20]
    if 4 * (len(sample) - len(sample.translate(None, _CONTROL_BYTES))) < len(sample):
        return None
    even, odd = sample[0::2], sample[1::2]
    controls_even = len(even) - len(even.translate(None, _CONTROL_BYTES))
    controls_odd = len(odd) - len(odd.translate(None, _CONTROL_BYTES))
    encoding = "utf-16-le" if controls_odd >= controls_even else "utf-16-be"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        return None
    return None if _CONTROL_CHAR_RE.search(text) else (text, encoding)


def _stray_byte(byte: int, encoding: str) -> str:
    try:
        return bytes([byte]).decode(encoding)
    except UnicodeDecodeError:
        return chr(byte)  # undefined in the code page: latin-1


def _mostly_utf8(data: bytes) -> tuple[str, str] | None:
    """UTF-8 text with stray bytes (a cp1251/cp1252 dash or paragraph pasted
    in, a cut multi-byte character). Decoding it all as a single-byte code
    page would garble every valid character; instead the valid UTF-8 stays
    and only the stray bytes are read as cp1251 or cp1252.

    Valid multi-byte UTF-8 sequences are strong evidence: a cp1251/cp1252
    file forms a 2-byte one only by accident (an uppercase letter before
    "ё"/"«"/"—", about one per 2000 letters) and a 3-byte one almost never
    (’ — € are 3 bytes). So a handful of them outweighs many stray bytes.
    """
    text = data.decode("utf-8", errors="surrogateescape")
    strays = [match.group() for match in _STRAY_BYTES_RE.finditer(text)]
    stray = sum(len(chunk) for chunk in strays)
    valid = evidence = 0
    for ch in text:
        if "\x80" <= ch and not "\udc80" <= ch <= "\udcff":
            valid += 1
            evidence += 1 if ch < "\u0800" else 10  # 2-byte vs 3/4-byte sequence
    if not stray or 20 * evidence < stray:
        return None
    stray_bytes = bytes(ord(ch) - 0xDC00 for chunk in strays for ch in chunk)
    cyrillic_text = 2 * len(_CYRILLIC_RE.findall(text)) > valid
    encoding = "cp1251" if cyrillic_text or _looks_cp1251(stray_bytes) else "cp1252"
    text = _STRAY_BYTES_RE.sub(
        lambda match: "".join(_stray_byte(ord(ch) - 0xDC00, encoding) for ch in match.group()),
        text,
    )
    return text, f"utf-8+{encoding}"


def _charset_normalizer_guess(data: bytes) -> tuple[str, str] | None:
    try:
        from charset_normalizer import from_bytes  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        best = from_bytes(data).best()
        return (data.decode(best.encoding), str(best.encoding)) if best else None
    except Exception:  # noqa: BLE001 — a detector bug must not break ingest
        return None


def _decode_text_auto(data: bytes) -> tuple[str, str]:
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"),
                          (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            with contextlib.suppress(UnicodeDecodeError):
                return data.decode(encoding), encoding
    wide = _bomless_utf16(data)
    if wide is not None:
        return wide
    with contextlib.suppress(UnicodeDecodeError):
        return data.decode("utf-8"), "utf-8"
    mixed = _mostly_utf8(data)
    if mixed is not None:
        return mixed
    # Before the detector: charset_normalizer misreads short cp1251 notes
    # ("Встреча" → shift_jis), the most common legacy file in a Russian base.
    if _looks_cp1251(data):
        with contextlib.suppress(UnicodeDecodeError):
            return data.decode("cp1251"), "cp1251"
    guess = _charset_normalizer_guess(data)
    if guess is not None:
        return guess
    with contextlib.suppress(UnicodeDecodeError):
        return data.decode("cp1252"), "cp1252"
    return data.decode("latin-1"), "latin-1"


def read_text_auto(path: Path | str) -> tuple[str, str]:
    """Read a text file of unknown encoding → ``(text, encoding)``.

    Order: UTF-8/UTF-16 BOM → BOM-less UTF-16 (``utf-16-le``/``utf-16-be``)
    → UTF-8 → mostly UTF-8 with a few stray bytes (``utf-8+cp1251`` /
    ``utf-8+cp1252``: the stray bytes alone are read in that code page) →
    cp1251 (Russian-looking bytes) → ``charset_normalizer`` when importable →
    cp1252 → latin-1. Never returns U+FFFD-replaced text. Newlines are
    normalised to ``\\n`` like :meth:`pathlib.Path.read_text`.
    """
    text, encoding = _decode_text_auto(Path(path).read_bytes())
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Write `data` via a temp file in the same directory + ``os.replace``.

    Readers see the old or the new content, never a torn file. The target's
    permission bits are kept; a symlink target is written through (the link
    stays a link). The parent directory must exist.
    """
    target = Path(path)
    if target.is_symlink():
        target = Path(os.path.realpath(target))
    try:
        mode: int | None = stat.S_IMODE(os.stat(target).st_mode)
    except FileNotFoundError:
        mode = None
    # NAME_MAX is 255 *bytes*: a long Cyrillic name must not overflow it.
    short = target.name.encode("utf-8")[:150].decode("utf-8", "ignore")
    tmp = target.parent / f".{short}.{secrets.token_hex(4)}.tmp"
    fd = os.open(
        tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    """Atomic ``Path.write_text``. Newlines are written as given on every OS
    (no ``os.linesep`` translation), so output is byte-identical everywhere."""
    atomic_write_bytes(path, text.encode(encoding))


def write_if_changed(path: Path | str, text: str, encoding: str = "utf-8") -> bool:
    """Atomically write `text` unless the file already holds exactly these
    bytes. Returns ``True`` when it wrote (the mtime is untouched otherwise)."""
    data = text.encode(encoding)
    try:
        if Path(path).read_bytes() == data:
            return False
    except FileNotFoundError:
        pass
    atomic_write_bytes(path, data)
    return True


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

# The frontmatter may be empty (`---` right after `---`), and the closing
# `---` may be the last line of a file without a trailing newline.
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)?---(?:\s*\n|[ \t]*\Z)", re.DOTALL)
_FRONTMATTER_OPEN_RE = re.compile(r"---[ \t]*\r?\n")


def _split_frontmatter(text: str) -> tuple[str | None, str, str]:
    """``(yaml_text or None, body, text_without_bom)``."""
    # Files saved by Windows editors may start with a UTF-8 BOM; without this
    # the frontmatter regex silently fails and metadata is treated as empty.
    text = text.lstrip("\ufeff")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, text, text
    return match.group(1) or "", text[match.end():], text


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(metadata_dict, body)``. Never raises.

    No frontmatter, invalid YAML (see :func:`yaml_load`) or a frontmatter that
    is not a mapping (a list, a scalar) → ``({}, text)``. Use
    :func:`frontmatter_error` to tell those cases apart.
    """
    raw, body, text = _split_frontmatter(text)
    if raw is None:
        return {}, text
    try:
        meta = yaml_load(raw)
    except yaml.YAMLError:
        return {}, text
    if meta is None:
        return {}, body
    if not isinstance(meta, dict):
        return {}, text
    return meta, body


def frontmatter_error(text: str) -> str | None:
    """``None`` for no frontmatter or a valid mapping; otherwise a short reason.

    Reasons: ``"invalid YAML: …"``, ``"frontmatter is not a mapping (got
    list)"``, ``"frontmatter is not closed (no '---' line after it)"``.
    """
    raw, _body, stripped = _split_frontmatter(text)
    if raw is None:
        if _FRONTMATTER_OPEN_RE.match(stripped):
            return "frontmatter is not closed (no '---' line after it)"
        return None
    try:
        meta = yaml_load(raw)
    except yaml.YAMLError as exc:
        return f"invalid YAML: {_one_line(exc)}"
    if meta is None or isinstance(meta, dict):
        return None
    return f"frontmatter is not a mapping (got {type(meta).__name__})"


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
    # A page saved in a legacy code page is decoded, not crashed on.
    text, _encoding = read_text_auto(path)
    return parse_frontmatter(text)


def write_frontmatter_file(
    path: Path | str,
    meta: dict[str, Any],
    body: str,
    *,
    only_if_changed: bool = False,
) -> bool:
    """Atomically write a page. Returns whether the file was written.

    ``only_if_changed=True`` leaves an identical file (and its mtime) alone.
    """
    text = render_frontmatter(meta, body)
    if only_if_changed:
        return write_if_changed(path, text)
    atomic_write_text(path, text)
    return True


# ---------------------------------------------------------------------------
# Lifecycle & staleness (one rule for kb_lint and the viewer)
# ---------------------------------------------------------------------------


def _as_date(value: Any) -> _dt.date | None:
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _folder_lifecycle(rel_posix: Path | str, by_folder: Mapping[str, Any]) -> str | None:
    """``lifecycle.by_folder`` value for the deepest folder of the page that
    has one (``decisions`` covers ``decisions/2026/x.md``)."""
    parts = _posix_parts(rel_posix)
    if parts[:1] == ["knowledge"]:
        parts = parts[1:]
    policy = {"/".join(_posix_parts(k)): str(v).strip().lower() for k, v in by_folder.items()}
    for depth in range(len(parts) - 1, 0, -1):
        lifecycle = policy.get("/".join(parts[:depth]))
        if lifecycle in LIFECYCLES:
            return lifecycle
    return None


def effective_lifecycle(
    meta: Any,
    rel_posix: Path | str,
    by_folder: Mapping[str, Any] | None = None,
    *,
    default: str = "evolving",
) -> str:
    """The lifecycle a page really has.

    A page's own non-default value (``permanent``/``temporal`` when `default`
    is ``evolving``) wins. A missing, invalid or default-valued one — what
    ``kb_lint --fix`` and the templates fill in — yields to the
    ``lifecycle.by_folder`` policy, then to `default`.
    """
    default = default if default in LIFECYCLES else "evolving"
    page = meta.get("lifecycle") if isinstance(meta, dict) else None
    page = str(page).strip().lower() if page is not None else ""
    if page in LIFECYCLES and page != default:
        return page
    return _folder_lifecycle(rel_posix, by_folder or {}) or default


def stale_status(
    meta: Any,
    rel_posix: Path | str,
    *,
    today: _dt.date,
    stale_days: int = 30,
    by_folder: Mapping[str, Any] | None = None,
    default_lifecycle: str = "evolving",
) -> tuple[bool, str]:
    """THE stale rule → ``(is_stale, reason)``.

    Never stale: archived path, generated page, effective lifecycle
    ``permanent``, ``valid_until`` ≥ today, or no date at all (missing fields
    are a separate lint check). Otherwise stale when the newest of
    ``last_verified`` / ``extracted_at`` is more than `stale_days` old.
    """
    if isinstance(today, _dt.datetime):
        today = today.date()
    if is_archived(rel_posix):
        return False, "archived"
    meta = meta if isinstance(meta, dict) else {}
    if is_generated(meta):
        return False, "generated"
    lifecycle = effective_lifecycle(
        meta, rel_posix, by_folder, default=default_lifecycle
    )
    if lifecycle == "permanent":
        return False, "permanent"
    valid_until = _as_date(meta.get("valid_until"))
    if valid_until is not None and valid_until >= today:
        return False, f"valid until {valid_until.isoformat()}"
    dated = [
        (date, name)
        for name in ("last_verified", "extracted_at")
        if (date := _as_date(meta.get(name))) is not None
    ]
    if not dated:
        return False, "no date"
    reference, source = max(dated)
    age = (today - reference).days
    if age > stale_days:
        return True, f"{source} {reference.isoformat()} is {age} days old (threshold: {stale_days})"
    return False, f"{source} {reference.isoformat()} is {age} days old"


# ---------------------------------------------------------------------------
# Content fingerprinting (cross-base sync — see kb-docs/16_MERGE.md)
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
            "(see `kb-docs/16_MERGE.md`). Never indexed.\n\n"
            "| Folder | What lives here |\n"
            "|--------|-----------------|\n"
            "| `inbox/` | Drop bundles (`.zip`) from another base here, then run import |\n"
            "| `outbox/` | Bundles produced by export |\n"
            "| `applied/` | Bundles already imported |\n"
            "| `backups/` | Pre-import snapshots of every file the import touched, plus its undo journal (`kb_import.py --undo <report>`) |\n"
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
# Locks
# ---------------------------------------------------------------------------


class KbLockTimeout(TimeoutError):
    """Another process holds the named lock and `timeout` ran out."""


_LOCK_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
# Claim → thread that holds it, for the claims this process made. os.environ
# is process-wide, so without it a second thread would read the first one's
# claim as its own and enter the critical section beside it.
_LOCK_THREADS: dict[str, int] = {}


def _claim_is_ours(claim: str) -> bool:
    """An inherited claim a nested call or a child process may share.

    A claim from another process (an ancestor) is shared; one this process
    made is shared only with the thread that holds it.
    """
    if claim.split(":", 1)[0] != str(os.getpid()):
        return True
    return _LOCK_THREADS.get(claim) == threading.get_ident()


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return True  # os.kill(pid, 0) would terminate the process on Windows
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists, owned by someone else
    return True


# "Held by someone else". Any other error (ENOLCK, EOPNOTSUPP on a network or
# FUSE mount without lock support) is raised at once instead of being retried
# until the timeout.
_LOCK_BUSY_ERRNOS = frozenset(
    code
    for code in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES, getattr(errno, "EDEADLK", None))
    if code is not None
)


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows only
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in _LOCK_BUSY_ERRNOS:
            return False
        raise
    return True


def _unlock(fd: int) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


@contextlib.contextmanager
def kb_lock(
    root: Path | str, name: str = "pipeline", timeout: float | None = 600.0
) -> Iterator[Path]:
    """Hold the exclusive lock ``<root>/.kb-state/locks/<name>.lock``.

    ``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows; the OS drops it
    when the process dies. Waits up to `timeout` seconds (``0`` = one try,
    ``None`` = forever), then raises :class:`KbLockTimeout`. Yields the lock
    file path. A filesystem without lock support (``ENOLCK``,
    ``EOPNOTSUPP``) raises its ``OSError`` at once.

    While held, ``KB_LOCK_<NAME>=<pid>:<token>:<lock path>`` is exported (and
    written to ``<name>.lock.owner``), so nested
    calls and child processes (``kb_reindex`` → ``kb_ingest``) share the lock
    instead of deadlocking on it. Another thread of the holding process does
    not share it: it waits like any other process.
    """
    if not _LOCK_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid lock name: {name!r}")
    path = state_dir(root) / "locks" / f"{name}.lock"
    path.parent.mkdir(exist_ok=True)
    key = "KB_LOCK_" + re.sub(r"[^A-Za-z0-9]+", "_", name).upper()
    # The current holder writes its claim to <name>.lock.owner. An inherited
    # claim is honoured only while that file still names it: once the holder
    # releases and an unrelated process takes the lock, the child waits too.
    owner = path.with_name(path.name + ".owner")
    claim = f"{os.getpid()}:{secrets.token_hex(8)}:{os.path.realpath(path)}"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
    try:
        if not _try_lock(fd):
            inherited = os.environ.get(key, "")
            try:
                current = owner.read_text(encoding="utf-8")
            except OSError:
                current = ""
            # held by this thread (nested call) or an ancestor process
            if inherited and current == inherited and _claim_is_ours(inherited):
                yield path
                return
            deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
            while not _try_lock(fd):
                if deadline is not None and time.monotonic() >= deadline:
                    raise KbLockTimeout(
                        f"'{name}' lock is busy (another kb_* process holds {path})"
                    )
                time.sleep(0.1)
        previous = os.environ.get(key)
        atomic_write_text(owner, claim)
        os.environ[key] = claim
        _LOCK_THREADS[claim] = threading.get_ident()
        try:
            yield path
        finally:
            _LOCK_THREADS.pop(claim, None)
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
            with contextlib.suppress(OSError):
                if owner.read_text(encoding="utf-8") == claim:
                    owner.unlink()
            _unlock(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Logging (append-only log.md)
# ---------------------------------------------------------------------------

_LOG_ENTRY_RE = re.compile(r"^## \[", re.MULTILINE)
_LOG_ENTRY_MONTH_RE = re.compile(r"## \[(\d{4})-(\d{2})")
_LOG_LOCK_TIMEOUT = 30.0


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
    """Append a structured entry to log.md. See 10_LOG.md for the format.

    Honours ``logging.rotation_threshold`` (entries): when log.md holds more,
    the oldest entries move to ``<logging.archive_dir>/log-YYYY-MM.md`` (by
    each entry's month) so the newest half stays. Writers serialize on the
    ``log`` lock; if it cannot be taken the entry is still appended.
    """
    root = root or find_kb_root()
    p = log_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(kb_lock(root, "log", timeout=_LOG_LOCK_TIMEOUT))
            locked = True
        except (KbLockTimeout, OSError):
            locked = False
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
        if locked:
            try:
                _rotate_log(root, p)
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                print_err(f"⚠️  [kb_common] log rotation skipped: {_one_line(exc)}")
    return p


def _rotate_log(root: Path, p: Path) -> None:
    cfg = load_config(root)
    threshold = cfg.log_rotation_threshold
    if threshold <= 0:
        return
    text = p.read_text(encoding="utf-8")
    starts = [match.start() for match in _LOG_ENTRY_RE.finditer(text)]
    if len(starts) <= threshold:
        return
    keep = max(1, threshold // 2)
    moved = starts[: len(starts) - keep]
    cut = starts[len(starts) - keep]
    groups: dict[str, list[str]] = {}
    month = _dt.date.today().strftime("%Y-%m")
    for index, start in enumerate(moved):
        end = moved[index + 1] if index + 1 < len(moved) else cut
        entry = text[start:end]
        found = _LOG_ENTRY_MONTH_RE.match(entry)
        if found:
            month = f"{found.group(1)}-{found.group(2)}"
        groups.setdefault(month, []).append(entry if entry.endswith("\n") else entry + "\n")
    archive = resolve_under(root, cfg.log_archive_dir) or (root / "log-archive")
    archive.mkdir(parents=True, exist_ok=True)
    # Archives first: a crash in between duplicates entries, never loses them.
    for month_key, entries in groups.items():
        target = archive / f"log-{month_key}.md"
        existing = (
            target.read_text(encoding="utf-8")
            if target.exists()
            else f"# Operations Log — archive {month_key}\n\n"
        )
        if not existing.endswith("\n"):
            existing += "\n"
        atomic_write_text(target, existing + "".join(entries))
    atomic_write_text(p, text[: starts[0]] + text[cut:])


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
    atomic_write_text(
        path, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    )


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# kb.config.yml line editing
# ---------------------------------------------------------------------------
# kb.config.yml is a commented, hand-edited file. Code never round-trips it
# through a YAML dumper (that strips every comment); it edits single lines.


class ConfigEditError(ValueError):
    """A kb.config.yml edit that cannot be done safely line by line."""


_YAML_LINE_RE = re.compile(
    r"[^\r\n\x85\u2028\u2029]*(?:\r\n|[\r\n\x85\u2028\u2029])"
    r"|[^\r\n\x85\u2028\u2029]+\Z"
)


def _config_lines(text: str) -> list[str]:
    return _YAML_LINE_RE.findall(text)


def _yaml_inline(value: Any) -> str:
    """One-line YAML for a scalar or a flat list (strings double-quoted)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)  # an exotic float that reads back differently is refused later
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_yaml_inline(item) for item in value) + "]"
    if isinstance(value, dict) and not value:
        return "{}"
    raise ConfigEditError(
        f"cannot write {type(value).__name__} values; set leaf keys one by one"
    )


def _yaml_equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _yaml_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _yaml_equal(a, b) for a, b in zip(left, right)
        )
    return type(left) is type(right) and left == right


def _compose_config(text: str) -> Any:
    try:
        # The loader of yaml_load (and so of load_config): config_set accepts
        # exactly the configs load_config reads. libyaml's marks count
        # characters, like the pure-Python loader's.
        _check_yaml_depth(text)
        root = yaml.compose(text, Loader=YAML_LOADER)
    except (yaml.YAMLError, ValueError) as exc:
        raise ConfigEditError(f"kb.config.yml is not valid YAML: {_one_line(exc)}") from exc
    except RecursionError as exc:
        raise ConfigEditError("kb.config.yml nests too deeply") from exc
    if root is None:
        return None
    if not isinstance(root, yaml.MappingNode):
        raise ConfigEditError("kb.config.yml top level is not a mapping")
    if root.flow_style:
        raise ConfigEditError("kb.config.yml top level is a flow-style mapping")
    return root


def _config_data(text: str) -> dict[str, Any]:
    try:
        data = yaml_load(text) if text.strip() else None
    except yaml.YAMLError as exc:
        raise ConfigEditError(f"kb.config.yml is not valid YAML: {_one_line(exc)}") from exc
    return data if isinstance(data, dict) else {}


def _find_pair(mapping: Any, key: str) -> tuple[Any, Any] | None:
    found = None
    for key_node, value_node in mapping.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            found = (key_node, value_node)  # YAML keeps the last duplicate
    return found


def _is_null_scalar(node: Any) -> bool:
    return (
        isinstance(node, yaml.ScalarNode)
        and node.tag == "tag:yaml.org,2002:null"
        and node.start_mark.line == node.end_mark.line
    )


def _is_empty_flow(node: Any) -> bool:
    return (
        isinstance(node, (yaml.MappingNode, yaml.SequenceNode))
        and bool(node.flow_style)
        and not node.value
        and node.start_mark.line == node.end_mark.line
    )


def _last_line(node: Any) -> int:
    """Index of the last line holding `node`'s content."""
    if isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and not node.flow_style and node.value:
        last = node.value[-1]
        if isinstance(node, yaml.MappingNode):
            return max(last[0].start_mark.line, _last_line(last[1]))
        return _last_line(last)
    end = node.end_mark
    if end.column == 0 and end.line > node.start_mark.line:
        return end.line - 1
    return end.line


def _indent_step(root: Any) -> int:
    stack = [root] if root is not None else []
    while stack:
        node = stack.pop()
        for key_node, value_node in node.value:
            if (
                isinstance(value_node, yaml.MappingNode)
                and not value_node.flow_style
                and value_node.value
            ):
                step = value_node.value[0][0].start_mark.column - key_node.start_mark.column
                if step > 0:
                    return step
                stack.append(value_node)
    return 2


def _chain_lines(
    keys: list[str], indent: int, step: int, rendered: str, comment: str | None, newline: str
) -> list[str]:
    out = []
    for depth, key in enumerate(keys):
        prefix = " " * (indent + depth * step) + key + ":"
        if depth == len(keys) - 1:
            prefix += " " + rendered
            if comment:
                prefix += "  # " + comment.strip()
        out.append(prefix + newline)
    return out


def _rewrite_value_span(line: str, node: Any, replacement: str) -> str:
    before = line[: node.start_mark.column]
    after = line[node.end_mark.column:]
    if replacement:
        if not before.endswith((" ", "\t")):
            before += " "
        return before + replacement + after
    return before.rstrip(" \t") + after


def _insert_under(
    lines: list[str],
    mapping: Any,
    parent_key: Any,
    keys: list[str],
    rendered: str,
    comment: str | None,
    newline: str,
    step: int,
) -> None:
    """Insert the missing chain `keys` as the last children of `mapping`."""
    if parent_key is None:
        # New top-level section: at the end of the file.
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend(_chain_lines(keys, 0, step, rendered, comment, newline))
        return
    child_indent = mapping.value[0][0].start_mark.column
    own_step = child_indent - parent_key.start_mark.column
    at = _last_line(mapping) + 1
    # Comment lines indented like the children still belong to this block.
    while at < len(lines):
        stripped = lines[at].lstrip(" ")
        if not stripped.startswith("#") or len(lines[at]) - len(stripped) < child_indent:
            break
        at += 1
    if at > 0 and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += newline
    lines[at:at] = _chain_lines(
        keys, child_indent, own_step if own_step > 0 else step, rendered, comment, newline
    )


_MISSING = object()


def config_set(text: str, dotted_key: str, value: Any, *, comment: str | None = None) -> str:
    """Set ``a.b.c`` in kb.config.yml text by line surgery; returns new text.

    * Existing key → only its value is replaced; the trailing comment stays.
      Commented-out lines (``# a: 1``) are never touched. When the current
      value already equals `value`, the text comes back unchanged.
    * Missing key → inserted as the last child of its parent mapping with
      the parent's child indent; missing parents are created in block style
      (a new top-level section is appended at the end of the file). A null or
      empty ``{}`` parent becomes a block mapping. `comment` is added only to
      a newly inserted line.
    * `value` (a Python value, not YAML text): str / int / float / bool /
      None / flat list / ``{}``; strings are written double-quoted, lists in
      flow style.

    Raises :class:`ConfigEditError` for invalid YAML, flow-style or
    non-mapping parents, multi-line existing values, unsupported values, and
    whenever the result would change anything besides this one key.
    """
    keys = dotted_key.split(".")
    if not dotted_key or any(not part.strip() for part in keys):
        raise ConfigEditError(f"invalid dotted key: {dotted_key!r}")
    rendered = _yaml_inline(value)
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    body = text[len(bom):]
    before = _config_data(body)
    expected_value = list(value) if isinstance(value, tuple) else value

    current: Any = before
    for key in keys:
        current = current.get(key) if isinstance(current, dict) else _MISSING
        if current is _MISSING:
            break
    if current is not _MISSING and _yaml_equal(current, expected_value):
        return text

    newline = "\r\n" if "\r\n" in body else "\n"
    lines = _config_lines(body)
    root = _compose_config(body)
    step = _indent_step(root)
    mapping = root
    parent_key = None
    for depth, key in enumerate(keys):
        if mapping is None:  # empty document
            _insert_under(lines, None, None, keys[depth:], rendered, comment, newline, step)
            break
        pair = _find_pair(mapping, key)
        if pair is None:
            _insert_under(lines, mapping, parent_key, keys[depth:], rendered, comment, newline, step)
            break
        key_node, value_node = pair
        label = ".".join(keys[: depth + 1])
        if depth == len(keys) - 1:
            single_line = (
                value_node.start_mark.line == key_node.start_mark.line
                and _last_line(value_node) == key_node.start_mark.line
                and (
                    isinstance(value_node, yaml.ScalarNode)
                    or bool(getattr(value_node, "flow_style", False))
                )
            )
            if not single_line:
                raise ConfigEditError(f"{label} spans several lines; edit it by hand")
            row = key_node.start_mark.line
            lines[row] = _rewrite_value_span(lines[row], value_node, rendered)
            break
        if isinstance(value_node, yaml.MappingNode) and not value_node.flow_style:
            mapping, parent_key = value_node, key_node
            continue
        if _is_null_scalar(value_node) or (
            _is_empty_flow(value_node) and isinstance(value_node, yaml.MappingNode)
        ):
            # `key:` / `key: ~` / `key: {}` → `key:` followed by the new children.
            row = key_node.start_mark.line
            lines[row] = _rewrite_value_span(lines[row], value_node, "")
            if not lines[row].endswith(("\n", "\r")):
                lines[row] += newline
            lines[row + 1:row + 1] = _chain_lines(
                keys[depth + 1:], key_node.start_mark.column + step, step,
                rendered, comment, newline,
            )
            break
        if isinstance(value_node, yaml.MappingNode):
            raise ConfigEditError(f"{label} is a flow-style mapping; edit it by hand")
        raise ConfigEditError(f"{label} is not a mapping; cannot set {dotted_key}")

    result = bom + "".join(lines)
    expected = copy.deepcopy(before)
    _assign(expected, keys, expected_value)
    if not _yaml_equal(_config_data(result[len(bom):]), expected):
        raise ConfigEditError(f"setting {dotted_key} would change other keys; edit it by hand")
    return result


def _assign(data: dict[str, Any], keys: list[str], value: Any) -> None:
    current = data
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[keys[-1]] = value


def config_append_block(text: str, top_key: str, block_text: str) -> str:
    """Add a whole top-level section (e.g. ``media:``) unless it has content.

    `block_text` must be a block-style mapping with exactly one top-level key,
    `top_key`, at column 0; its comments are kept verbatim. If `top_key`
    already exists with a non-empty value the text is returned unchanged
    (idempotent). If it exists with an empty value (``key:``, ``key: {}``,
    ``key: null``), that line is replaced by the block (its trailing comment
    moves to the block's first line). Otherwise the block is appended at the
    end of the file after a blank line.
    """
    block = _compose_config(block_text)
    if (
        block is None
        or len(block.value) != 1
        or not isinstance(block.value[0][0], yaml.ScalarNode)
        or block.value[0][0].value != top_key
        or block.value[0][0].start_mark.column != 0
    ):
        raise ConfigEditError(
            f"block_text must be one top-level `{top_key}:` block"
        )
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    body = text[len(bom):]
    before = _config_data(body)
    newline = "\r\n" if "\r\n" in body else "\n"
    block_lines = [
        line.rstrip("\r\n") + newline for line in _config_lines(block_text)
    ]
    lines = _config_lines(body)
    root = _compose_config(body)
    pair = _find_pair(root, top_key) if root is not None else None
    if pair is not None:
        key_node, value_node = pair
        if not (_is_null_scalar(value_node) or _is_empty_flow(value_node)):
            return text
        if key_node.start_mark.column != 0:
            raise ConfigEditError(f"`{top_key}:` is not at column 0")
        row = key_node.start_mark.line
        old = lines[row].rstrip("\r\n")
        comment_at = old.find("#", value_node.end_mark.column)
        first = block_lines[0].rstrip("\r\n")
        if comment_at != -1 and "#" not in first:
            block_lines[0] = f"{first}  {old[comment_at:].strip()}{newline}"
        lines[row:row + 1] = block_lines
    else:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        if lines and lines[-1].strip():
            lines.append(newline)
        lines.extend(block_lines)
    result = bom + "".join(lines)
    expected = dict(before)
    expected[top_key] = _config_data(block_text).get(top_key)
    if not _yaml_equal(_config_data(result[len(bom):]), expected):
        raise ConfigEditError(f"adding `{top_key}:` would change other keys; edit it by hand")
    return result


def update_config_file(
    root: Path | str,
    edits: Mapping[str, Any] | Iterable[Any],
) -> bool:
    """Apply edits to ``<root>/kb.config.yml`` and write it atomically.

    `edits`: a mapping ``{dotted_key: value}`` or an iterable whose items are
    ``(dotted_key, value)`` / ``(dotted_key, value, comment)`` tuples (applied
    with :func:`config_set`) or callables ``text -> text`` (e.g.
    ``lambda t: config_append_block(t, "media", block)``), applied in order.
    Keeps a UTF-8 BOM and CRLF line endings. Returns ``True`` when the file
    changed; nothing is written when any edit fails.
    """
    path = kb_config_path(Path(root))
    raw = path.read_bytes()
    bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    items = edits.items() if isinstance(edits, Mapping) else edits
    new = text
    for item in items:
        if callable(item):
            new = item(new)
            continue
        key, value, *rest = item
        new = config_set(new, key, value, comment=rest[0] if rest else None)
    if new == text:
        return False
    atomic_write_bytes(path, (codecs.BOM_UTF8 if bom else b"") + new.encode("utf-8"))
    return True


# ---------------------------------------------------------------------------
# Wikilinks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WikiLink:
    """One ``[[…]]`` / ``![[…]]`` link, normalised.

    ``target`` — the link path as written, minus alias, ``#section``, a
    trailing ``.md``, ``./`` and surrounding slashes (backslashes → ``/``).
    ``slug`` — its last segment; ``path_hint`` — the folder part or ``None``.
    """

    target: str
    slug: str
    section: str | None
    alias: str | None
    is_embed: bool
    path_hint: str | None

    @property
    def page_id(self) -> str:
        """Target relative to ``knowledge/`` (a leading ``knowledge/`` dropped)."""
        parts = self.target.split("/")
        if len(parts) > 1 and parts[0].lower() == "knowledge":
            parts = parts[1:]
        return "/".join(parts)


_WIKILINK_RE = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
# A fence line: up to 3 spaces, then ``` or ~~~ (an info string may follow).
_FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_BACKTICK_RUN_RE = re.compile(r"`+")
_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")
_NON_NEWLINE_RE = re.compile(r"[^\r\n]")


def _blank(text: str) -> str:
    if "\n" not in text and "\r" not in text:
        return " " * len(text)  # the common case: one inline span
    return _NON_NEWLINE_RE.sub(" ", text)


def _inline_code_spans(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` of every inline code span: a backtick run closed by
    the next run of the same length, never across a blank line (an
    unmatched run is literal text). O(n log n) — a regex backtracks to the
    end of the paragraph for every unmatched run."""
    runs = [match.span() for match in _BACKTICK_RUN_RE.finditer(text)]
    by_length: dict[int, list[int]] = {}
    for index, (start, end) in enumerate(runs):
        by_length.setdefault(end - start, []).append(index)
    blank_lines = [match.start() for match in _BLANK_LINE_RE.finditer(text)]
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        start, end = runs[index]
        same = by_length[end - start]
        position = bisect.bisect_right(same, index)
        if position < len(same):
            closer = same[position]
            blank = bisect.bisect_left(blank_lines, end)
            if blank == len(blank_lines) or blank_lines[blank] >= runs[closer][0]:
                spans.append((start, runs[closer][1]))
                index = closer + 1
                continue
        index += 1
    return spans


def _mask_code(text: str) -> str:
    """`text` with fenced code blocks and inline code blanked out; offsets
    and line breaks are kept. An unclosed fence runs to the end."""
    if "`" not in text and "~~~" not in text:
        return text
    out: list[str] = []
    fence = ""
    for line in text.splitlines(keepends=True):
        match = _FENCE_RE.match(line)
        if fence:
            run = match.group(1) if match else ""
            if run[:1] == fence[0] and len(run) >= len(fence) and not match.group(2).strip():
                fence = ""
            out.append(_blank(line))
        elif match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence = match.group(1)
            out.append(_blank(line))
        else:
            out.append(line)
    text = "".join(out)
    pieces: list[str] = []
    done = 0
    for start, end in _inline_code_spans(text):
        pieces += [text[done:start], _blank(text[start:end])]
        done = end
    pieces.append(text[done:])
    return "".join(pieces)


def _parse_wikilink(inner: str, is_embed: bool) -> WikiLink | None:
    alias: str | None = None
    bar = inner.find("|")
    if bar != -1:
        # `\|` is how a link inside a Markdown table escapes its alias pipe.
        head = inner[: bar - 1] if bar > 0 and inner[bar - 1] == "\\" else inner[:bar]
        alias = inner[bar + 1:].strip() or None
        inner = head
    target = inner.strip().replace("\\", "/")
    section: str | None = None
    if "#" in target:
        target, section_text = target.split("#", 1)
        section = section_text.strip() or None
    target = target.strip()
    while target.startswith("./"):
        target = target[2:]
    target = target.strip("/")
    if target.lower().endswith(".md"):
        target = target[:-3].rstrip()
    parts = [part.strip() for part in target.split("/") if part.strip()]
    if not parts:
        return None
    return WikiLink(
        target="/".join(parts),
        slug=parts[-1],
        section=section,
        alias=alias,
        is_embed=is_embed,
        path_hint="/".join(parts[:-1]) or None,
    )


def _iter_wikilinks_at(text: str) -> Iterator[tuple[WikiLink, int]]:
    masked = _mask_code(text)
    for match in _WIKILINK_RE.finditer(masked):
        link = _parse_wikilink(text[match.start(2):match.end(2)], bool(match.group(1)))
        if link is not None:
            yield link, match.start()


def iter_wikilinks(text: str) -> Iterator[WikiLink]:
    """Every wikilink outside fenced code blocks and inline code, in order.

    ``[[x#sec]]`` → slug ``x``, section ``sec``; ``[[x.md]]`` → ``x``;
    ``[[knowledge/domain/x]]`` → slug ``x``, path_hint ``knowledge/domain``;
    ``![[img.png]]`` → ``is_embed=True``. Links without a target
    (``[[#heading]]``) are skipped.
    """
    for link, _start in _iter_wikilinks_at(text):
        yield link


def extract_wikilinks(text: str) -> list[str]:
    """Knowledge-relative targets (:attr:`WikiLink.page_id`) of the non-embed
    links: ``[[caching|alias]]`` → ``caching``, ``[[domain/db#x]]`` →
    ``domain/db``. Links inside code are ignored."""
    return [link.page_id for link in iter_wikilinks(text) if not link.is_embed]


def extract_wikilinks_with_context(text: str) -> list[tuple[str, str]]:
    """Return ``(target, source_line)`` for each wikilink, in document order.

    ``source_line`` is the stripped line containing the link's opening
    brackets — enough context to show *why* one page links to another.
    Target order matches :func:`extract_wikilinks` exactly.
    """
    results: list[tuple[str, str]] = []
    for link, start in _iter_wikilinks_at(text):
        if link.is_embed:
            continue
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", start)
        if line_end == -1:
            line_end = len(text)
        results.append((link.page_id, text[line_start:line_end].strip()))
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
    "ENGINE_VERSION",
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_LOG_FILENAME",
    "DEFAULT_LINT_REPORT_FILENAME",
    "STATE_DIR",
    "KB_DOCS_DIR",
    "KNOWLEDGE_DIRS",
    "RAW_DIRS",
    "ASSET_DIRS",
    "REVIEW_DIRS",
    "PROCESSED_DIRS",
    "EVAL_ROOT",
    "EVAL_RESULTS_DIR",
    "LIFECYCLES",
    "DEFAULT_INGEST_IGNORE_GLOBS",
    "DEFAULT_REDACT_CATEGORIES",
    "DEFAULT_LIFECYCLE_BY_FOLDER",
    "DEFAULT_WATCH_DIRS",
    "MAX_YAML_ALIASES",
    "MAX_YAML_EXPANDED_NODES",
    "YAML_LOADER",
    "MAX_YAML_DEPTH",
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
    "resolve_under",
    "is_archived",
    "is_generated",
    "state_dir",
    "yaml_load",
    "load_config",
    "compute_source_hash",
    "read_text_auto",
    "atomic_write_bytes",
    "atomic_write_text",
    "write_if_changed",
    "parse_frontmatter",
    "frontmatter_error",
    "render_frontmatter",
    "read_frontmatter_file",
    "write_frontmatter_file",
    "effective_lifecycle",
    "stale_status",
    "slugify",
    "stable_filename",
    "KbLockTimeout",
    "kb_lock",
    "now_iso",
    "append_log",
    "iter_files",
    "ensure_dir",
    "write_json",
    "read_json",
    "ConfigEditError",
    "config_set",
    "config_append_block",
    "update_config_file",
    "WikiLink",
    "iter_wikilinks",
    "extract_wikilinks",
    "extract_wikilinks_with_context",
    "scan_knowledge_slugs",
    "print_err",
    "detect_python_executable",
    "find_ffmpeg",
    "os_install_hint",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine shared helpers (imported by scripts/kb_*.py)."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=ENGINE_VERSION,
        help="print the engine version (fills {{KB_INSTRUCTIONS_VERSION}})",
    )
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
