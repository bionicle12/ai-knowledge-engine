#!/usr/bin/env python3
"""kb_reindex — cross-platform reindex orchestrator for AI Knowledge Engine.

``shell/reindex.sh`` and ``shell/reindex.bat`` are thin wrappers over this
script, so the pipeline runs identically on Windows (no Git Bash / WSL
required), macOS, and Linux. The file watcher (``kb_watch.py``) and the git
hook (``--hook``) call it too.

Steps (a run holds the ``pipeline`` lock, shared with the child scripts):
  1. ingest        — python kb_ingest.py
  2. routing       — python kb_route.py
  3. quick lint    — python kb_lint.py --quick
  4. consolidation — lint report + nlp batch + reflection request (throttled by
                     a ``.last_consolidation`` marker; default every 24h)
  5. index         — repomix packs (``index:`` section) or the legacy monolith
  6. status        — kb_status.py rewrites STATUS.md (every mode)

Usage:
  python3 scripts/kb_reindex.py                # full pipeline
  python3 scripts/kb_reindex.py --quick        # skip consolidation
  python3 scripts/kb_reindex.py --no-index     # skip the index step
  python3 scripts/kb_reindex.py --index-only   # index + status only
  python3 scripts/kb_reindex.py --hook         # git hook: index + status, output in .kb-state/hooks.log

Exit status: 0 when every step that ran succeeded; 1 when kb_ingest.py
failed, the index is incomplete (repomix unavailable, a pack FAILED, invalid
repomix.config.json) or another run kept the pipeline lock; 2 when the root
has no kb.config.yml (nothing is written). ``--hook`` always exits 0.
"""
from __future__ import annotations

import argparse
import contextlib
import fnmatch
import glob as globmod
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402

CONSOLIDATION_MARKER = ".last_consolidation"
# A normal run waits this long for a concurrent one (watcher, hook, manual).
PIPELINE_LOCK_TIMEOUT = 600.0
# The git hook never queues behind another run: the next run catches up.
HOOK_LOCK_TIMEOUT = 5.0
HOOK_LOG = "hooks.log"

# --- Pack-based index constants ---------------------------------------------
# o200k_base averages ~3.8 chars/token on prose; used for estimates only.
CHARS_PER_TOKEN = 3.8
WINDOW_CEILINGS = {"200k": 60_000, "256k": 80_000, "400k": 120_000, "1m": 150_000}
DEFAULT_MERGE_BELOW = 15_000
# A legacy monolithic output.xml above this deserves a loud warning.
MONOLITH_WARN_TOKENS = 150_000
# Sections that form the always-loadable "core" pack. Small by design:
# who the author is, how they think, how they write, plus routing tables.
CORE_SECTIONS = ("profile", "principles", "voice", "routing")
# Loose pages directly under knowledge/ (routing-table.md aside, it is core).
ROOT_PACK = "knowledge-root"
# Auto-mode names a knowledge/ section must not take: `knowledge/core/` used
# to overwrite the real core pack. Such a section is packed as knowledge-<name>.
RESERVED_PACK_NAMES = ("core", "aux", ROOT_PACK)
# AGENTS.md is intentionally NOT indexed: it is already in the system prompt,
# indexing it charges its tokens twice. Nor is kb.config.yml: AGENTS.md has the
# agent read it directly at session start. Nor is README.md: the base has none
# of its own, and a finalized base shares the project root with the project's.
META_FILES = (
    "KNOWLEDGE_STRUCTURE.md",
    "DATA_PLACEMENT_EXAMPLES.md",
)
PACK_HEADER = (
    "Knowledge-base pack '{name}'. Full text (compress:false — wording and "
    "nuance are the payload). Route via knowledge/routing-table.md and load "
    "AT MOST ONE domain pack per task."
)
MANIFEST_REL = ".repomix/manifest.json"
PACKS_STATUS_REL = ".repomix/PACKS_STATUS.md"
# repomix writes into `<output><BUILD_SUFFIX>` (`-o`); only a file that this
# build really wrote replaces the output, so a build that exits 0 without
# writing never passes an old copy off as rebuilt.
BUILD_SUFFIX = ".building"
# Ignore files repomix applies on top of its config (globby `gitignore`, plus
# `**/.ignore` and `**/.repomixignore`): part of every pack's freshness key.
IGNORE_FILES = (".gitignore", ".ignore", ".repomixignore")
# repomix's own default when repomix.config.json names no output.filePath.
REPOMIX_DEFAULT_OUTPUT = "repomix-output.xml"
# repomix XML output (`output.style: xml`, the default): the files section and
# one element per packed file (indented in `parsableStyle` output).
_XML_FILES_RE = re.compile(r"^[ \t]*<files>[ \t]*$", re.MULTILINE)
_XML_FILE_RE = re.compile(r'^[ \t]*<file path="([^"\n]*)">', re.MULTILINE)
LEGACY_WHEN = "whole base in one file; add an `index:` section to kb.config.yml to split it"

# Never packed, whatever repomix.config.json or an explicit pack says: a
# broken or trimmed base config must not put private material into a pack.
# Syntax of repomix `ignore.customPatterns`; added to every pack config and
# to the legacy build's --ignore.
ALWAYS_IGNORED = (
    "processed/**",
    "assets/**",
    "sync/**",
    "eval/**",
    "setup/**",
    "kb-docs/**",
    ".kb-state/**",
    ".kb-backups/**",
    ".kb-finalize-backup/**",
    ".repomix/**",
    ".venv/**",
    "venv/**",
    ".git/**",
    "node_modules/**",
    "log.md",
    "log-archive/**",
    "STATUS.md",
    ".env",
    ".env.*",
    "**/*.pem",
    "**/*.key",
)
# privacy.<flag> in kb.config.yml: only an explicit `true` lets the folder in.
PRIVACY_GATED = (
    ("raw_indexing_allowed", "raw/**"),
    ("review_indexing_allowed", "review/**"),
    ("interactions_indexing_allowed", "interactions/**"),
)


class RepomixConfigError(ValueError):
    """repomix.config.json exists but cannot serve as the base config."""


def _py(script: str, *args: str, root: Path) -> int:
    """Run a sibling kb_*.py script with the current interpreter."""
    script_path = SCRIPT_DIR / script
    if not script_path.is_file():
        return 0  # optional step, silently skip
    cmd = [kbc.detect_python_executable(), str(script_path), "--root", str(root), *args]
    return subprocess.run(cmd, check=False).returncode


def _py_capture(script: str, *args: str, root: Path) -> tuple[int, str]:
    """Like :func:`_py`, but returns ``(exit status, stdout)``."""
    cmd = [
        kbc.detect_python_executable(),
        str(SCRIPT_DIR / script),
        "--root",
        str(root),
        *args,
    ]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr)
    return result.returncode, result.stdout


def _consolidation_due(root: Path, interval_hours: float) -> bool:
    marker = root / CONSOLIDATION_MARKER
    if not marker.is_file():
        return True
    try:
        last = float(marker.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return True
    return (time.time() - last) > interval_hours * 3600


def _touch_consolidation(root: Path) -> None:
    (root / CONSOLIDATION_MARKER).write_text(str(int(time.time())), encoding="utf-8")


def request_reflection(root: Path) -> str | None:
    """Ask kb_reflect whether a reflection is due; log the request when it is.

    Runs ``kb_reflect.py --check-threshold`` (read-only) and, on
    ``THRESHOLD_MET``, ``kb_reflect.py --generate`` (logs a reflection request
    in log.md). Returns the decision, or None when kb_reflect is missing or
    failed.
    """
    if not (SCRIPT_DIR / "kb_reflect.py").is_file():
        return None
    code, out = _py_capture("kb_reflect.py", "--check-threshold", root=root)
    words = out.split()
    if code != 0 or not words:
        print(
            f"⚠️  [reindex] kb_reflect.py --check-threshold failed (exit {code}); "
            "no reflection request"
        )
        return None
    decision = words[-1]
    if decision == "THRESHOLD_MET":
        print("🧠 [reindex] reflection due — logging the request (kb_reflect.py --generate)")
        _py("kb_reflect.py", "--generate", root=root)
    return decision


def _consolidate(root: Path, cfg: "kbc.KbConfig") -> None:
    try:
        interval = float(cfg.autorun.get("consolidation_interval_hours", 24))
    except (TypeError, ValueError):
        interval = 24.0
    if not _consolidation_due(root, interval):
        return
    print("🧰 [reindex] consolidation...")
    _py("kb_lint.py", "--output", "report", root=root)
    _py("kb_nlp_batch.py", "--incremental", root=root)
    if cfg.autorun_consolidation_on_reindex:
        request_reflection(root)
    _touch_consolidation(root)


# ---------------------------------------------------------------------------
# Repomix
# ---------------------------------------------------------------------------


def repomix_command(cfg: "kbc.KbConfig") -> list[str] | None:
    """``repomix`` from PATH, else the pinned npx fallback, else None."""
    repomix = shutil.which("repomix")
    if repomix:
        return [repomix]
    if cfg.index_npx_fallback:
        npx = shutil.which("npx")
        if npx:
            return [npx, "--yes", f"repomix@{cfg.index_repomix_version}"]
    return None


def _describe_builder(cmd: list[str] | None) -> str:
    if cmd is None:
        return "none (repomix not found)"
    if len(cmd) == 1:
        return "repomix (PATH)"
    return f"npx {cmd[-1]}"


def _announce_npx(cmd: list[str]) -> None:
    if len(cmd) > 1:
        print(f"📦 [reindex] repomix not on PATH — using {_describe_builder(cmd)}")


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"⚠️  [reindex] could not remove {path}: {exc}")


def _print_missing_repomix(cfg: "kbc.KbConfig") -> None:
    if cfg.index_npx_fallback:
        reason = "neither repomix nor npx is on PATH"
    else:
        reason = "repomix is not on PATH (index.npx_fallback: false)"
    print(f"❌ [reindex] {reason} — the index was not built")
    print(
        f"    install: npm install -g repomix@{cfg.index_repomix_version} "
        "(needs Node.js; see kb-docs/05_INDEX.md)"
    )


def _run_repomix(cmd: list[str], root: Path) -> int:
    """Run repomix from the base root. Its output goes through print(), so
    ``--hook`` mode keeps it in .kb-state/hooks.log."""
    result = subprocess.run(
        cmd,
        check=False,
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for text in (result.stdout, result.stderr):
        if text.strip():
            print(text.rstrip())
    return result.returncode


def forced_ignore_patterns(cfg: "kbc.KbConfig") -> list[str]:
    """Patterns excluded from every pack, whatever repomix.config.json says."""
    privacy = cfg.raw.get("privacy") if isinstance(cfg.raw, dict) else None
    if not isinstance(privacy, dict):
        privacy = {}
    patterns = [
        pattern for flag, pattern in PRIVACY_GATED if privacy.get(flag) is not True
    ]
    patterns.extend(ALWAYS_IGNORED)
    status_file = str(cfg.status_file).replace("\\", "/").lstrip("/")
    if status_file and status_file not in patterns:
        patterns.append(status_file)
    return patterns


def _is_ignored(rel: str, patterns: Sequence[str]) -> bool:
    """Match a root-relative POSIX path against repomix-style ignore globs."""
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/**"):
            if rel.startswith(pattern[:-2]):
                return True
        elif pattern.startswith("**/"):
            if fnmatch.fnmatchcase(name, pattern[3:]):
                return True
        elif fnmatch.fnmatchcase(rel, pattern):
            return True
    return False


def _legacy_output_rel(base: dict) -> str:
    """Where the legacy build writes: the base config's output.filePath."""
    output = base.get("output")
    path = output.get("filePath") if isinstance(output, dict) else None
    if isinstance(path, str) and path.strip():
        return path.strip().replace("\\", "/")
    return REPOMIX_DEFAULT_OUTPUT


def _build_legacy(root: Path, cmd: list[str], cfg: "kbc.KbConfig", output_rel: str) -> bool:
    """One repomix run over the base config, into a temp file first."""
    output = root / output_rel
    building_rel = output_rel + BUILD_SUFFIX
    building = root / building_rel
    output.parent.mkdir(parents=True, exist_ok=True)
    _unlink(building)
    _announce_npx(cmd)
    print("📦 [reindex] generating Repomix index...")
    args = ["--ignore", ",".join(forced_ignore_patterns(cfg)), "-o", building_rel]
    code = _run_repomix([*cmd, "--quiet", *args], root)
    if code != 0:
        # --quiet hides the reason; rerun loudly so the error is visible.
        code = _run_repomix([*cmd, *args], root)
    if code != 0 or not building.is_file():
        _unlink(building)
        why = f"exit {code}" if code != 0 else "it exited 0 but wrote no output"
        print(f"❌ [reindex] repomix failed ({why}); {output_rel} was not rebuilt")
        return False
    building.replace(output)
    return True


def retire_packs(root: Path, manifest: dict) -> list[str]:
    """Legacy mode: remove what pack mode generated.

    A base that went back from packs to the monolith must not keep pack
    .xml files nobody refreshes (they may hold deleted or private pages).
    """
    removed = remove_orphans(root, set(), manifest)
    if removed:
        _unlink(root / ".repomix" / "audit" / "CROSS_PACK__request.md")
        for name in removed:
            print(f"🧹 [reindex] removed pack '{name}' (legacy mode builds no packs)")
    return removed


def run_repomix(root: Path, cfg: "kbc.KbConfig | None" = None) -> bool:
    """Generate the legacy monolithic Repomix index. True when it was built.

    Records the outcome in ``.repomix/manifest.json`` (``mode: legacy``) and
    ``.repomix/PACKS_STATUS.md``, like pack mode.
    """
    cfg = cfg or kbc.load_config(root)
    previous = read_manifest(root)
    removed = retire_packs(root, previous)
    cmd = repomix_command(cfg)
    manifest: dict = {
        "generator": "kb_reindex.py",
        "engine_version": kbc.ENGINE_VERSION,
        "checked_at": kbc.now_iso(),
        "builder": _describe_builder(cmd),
        "mode": "legacy",
        "ceiling": MONOLITH_WARN_TOKENS,
        "packs": {},
        "removed": removed,
    }
    old = previous.get("legacy") if previous.get("mode") == "legacy" else None
    entry = dict(old) if isinstance(old, dict) else {}
    try:
        output_rel = _legacy_output_rel(_base_repomix_config(root))
    except RepomixConfigError as exc:
        _print_config_error(exc)
        manifest["error"] = str(exc)
        output_rel, state = str(entry.get("output") or REPOMIX_DEFAULT_OUTPUT), "FAILED"
    else:
        if cmd is None:
            _print_missing_repomix(cfg)
            state = "STALE"
        elif _build_legacy(root, cmd, cfg, output_rel):
            state = "rebuilt"
            entry["built_at"] = kbc.now_iso()
        else:
            state = "FAILED"
    output = root / output_rel
    tokens = _output_tokens(output) if output.is_file() else 0
    entry.update(
        output=output_rel,
        state=state,
        tokens=tokens,
        over_ceiling=tokens > MONOLITH_WARN_TOKENS,
        when_to_load=LEGACY_WHEN,
    )
    manifest["legacy"] = entry
    _write_index_state(root, manifest)
    if state == "rebuilt":
        _warn_monolith(root, output)
    return state == "rebuilt"


def _warn_monolith(root: Path, output: Path | None = None) -> None:
    """Loudly flag a legacy single-file index that outgrew a context window."""
    output = output or root / ".repomix" / "output.xml"
    if not output.is_file():
        return
    tokens = int(output.stat().st_size / CHARS_PER_TOKEN)
    if tokens > MONOLITH_WARN_TOKENS:
        print(
            f"⚠️  [reindex] monolithic index is ~{tokens:,} tokens "
            f"(> {MONOLITH_WARN_TOKENS:,}). Agents can no longer read it whole."
        )
        print(
            "    Enable pack mode: add an `index:` section to kb.config.yml "
            "(see kb-docs/05_INDEX.md) and rerun."
        )


# ---------------------------------------------------------------------------
# Pack-based index (index: section in kb.config.yml)
# ---------------------------------------------------------------------------


@dataclass
class PackPlan:
    name: str
    include: list[str]
    files: list[Path] = field(default_factory=list)
    when_to_load: str = ""
    est_tokens: int = 0
    # Pack-specific ignore patterns on top of the shared ones.
    exclude: list[str] = field(default_factory=list)

    @property
    def output_rel(self) -> str:
        return f".repomix/{self.name}.xml"

    @property
    def config_rel(self) -> str:
        return f".repomix/configs/{self.name}.json"


def _md_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md") if p.is_file())


def _estimate_tokens(files: list[Path]) -> int:
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            continue
    return int(total / CHARS_PER_TOKEN)


def _resolve_globs(root: Path, patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        for hit in globmod.glob(str(root / pattern), recursive=True):
            p = Path(hit)
            if p.is_file():
                files.append(p)
    return sorted(set(files))


def _rel(root: Path, path: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def index_ceiling(index_cfg: dict) -> int:
    profile = str(index_cfg.get("window_profile", "256k")).lower()
    default = WINDOW_CEILINGS.get(profile, WINDOW_CEILINGS["256k"])
    return int(index_cfg.get("pack_token_ceiling", default))


def _safe_pack_name(name: str) -> str:
    """A pack name becomes a file name: no path separators, no leading dot."""
    cleaned = re.sub(r"[\\/\x00-\x1f]+", "-", name).strip().lstrip(".")
    return cleaned or "unnamed"


def _unique_names(plans: list[PackPlan]) -> list[PackPlan]:
    """Two packs with one name would overwrite each other's .xml."""
    seen: set[str] = set()
    for plan in plans:
        base = _safe_pack_name(plan.name)
        name, n = base, 2
        while name in seen:
            name, n = f"{base}-{n}", n + 1
        if name != plan.name:
            print(
                f"⚠️  [reindex] pack '{plan.name}' is built as '{name}' "
                "(pack names must be unique file names)"
            )
            plan.name = name
        seen.add(name)
    return plans


def plan_packs(
    root: Path, index_cfg: dict, *, ignore: Sequence[str] | None = None
) -> list[PackPlan]:
    """Turn the `index:` config section into a concrete pack list.

    ``packs: auto`` (default): core pack (meta + profile/principles/voice +
    routing) plus one pack per top-level ``knowledge/`` section (a section
    named after a reserved pack — core, aux, knowledge-root — is packed as
    ``knowledge-<name>``) and ``knowledge-root`` for the loose pages at the
    ``knowledge/`` root; sections over the ceiling are split by subfolder;
    parts under the merge threshold are collected into a shared ``aux`` pack.
    Explicit ``packs:`` list: taken as-is (name + include globs).
    Files matching `ignore` (default: :func:`forced_ignore_patterns`) are
    never pack members.
    """
    if ignore is None:
        ignore = forced_ignore_patterns(kbc.load_config(root))
    packs_cfg = index_cfg.get("packs", "auto")
    if isinstance(packs_cfg, list):
        plans = _plan_explicit(root, packs_cfg)
    else:
        plans = _plan_auto(root, index_cfg)
    for plan in plans:
        plan.files = [
            f
            for f in plan.files
            if (rel := _rel(root, f)) is not None and not _is_ignored(rel, ignore)
        ]
        plan.est_tokens = _estimate_tokens(plan.files)
    return _unique_names(plans)


def _plan_explicit(root: Path, entries: list) -> list[PackPlan]:
    plans = []
    for entry in entries:
        if not isinstance(entry, dict):
            print(f"⚠️  [reindex] index.packs: skipping {entry!r} (expected name + include)")
            continue
        include = entry.get("include") or []
        if isinstance(include, str):
            include = [include]
        include = [str(p) for p in include]
        plans.append(
            PackPlan(
                name=str(entry.get("name") or "unnamed"),
                include=include,
                files=_resolve_globs(root, include),
                when_to_load=str(entry.get("when_to_load") or ""),
            )
        )
    return plans


def _plan_auto(root: Path, index_cfg: dict) -> list[PackPlan]:
    ceiling = index_ceiling(index_cfg)
    merge_below = int(index_cfg.get("merge_below_tokens", DEFAULT_MERGE_BELOW))
    knowledge = root / "knowledge"

    core_include: list[str] = [f for f in META_FILES if (root / f).is_file()]
    core_files: list[Path] = [root / f for f in core_include]
    if (knowledge / "routing-table.md").is_file():
        core_include.append("knowledge/routing-table.md")
        core_files.append(knowledge / "routing-table.md")
    for section in CORE_SECTIONS:
        sec_dir = knowledge / section
        if sec_dir.is_dir():
            core_include.append(f"knowledge/{section}/**/*.md")
            core_files.extend(_md_files(sec_dir))

    plans = [
        PackPlan(
            name="core",
            include=core_include,
            files=core_files,
            when_to_load="Always loadable: author profile, principles, voice, routing.",
        )
    ]

    aux_include: list[str] = []
    aux_files: list[Path] = []
    aux_parts: list[str] = []
    aux_exclude: list[str] = []

    # Loose pages at the knowledge/ root (glossary.md, ...) belong to a pack
    # too: their own when big enough, aux otherwise.
    root_pages = (
        sorted(
            f
            for f in knowledge.glob("*.md")
            if f.is_file() and f.name != "routing-table.md"
        )
        if knowledge.is_dir()
        else []
    )
    if root_pages:
        # routing-table.md is core; keep it out of the second pack.
        exclude = ["knowledge/routing-table.md"]
        if _estimate_tokens(root_pages) < merge_below:
            aux_include.append("knowledge/*.md")
            aux_files.extend(root_pages)
            aux_parts.append(ROOT_PACK)
            aux_exclude.extend(exclude)
        else:
            plans.append(
                PackPlan(
                    name=ROOT_PACK,
                    include=["knowledge/*.md"],
                    files=root_pages,
                    when_to_load="Top-level pages of knowledge/ (outside any section).",
                    exclude=exclude,
                )
            )

    sections = []
    if knowledge.is_dir():
        sections = sorted(
            d
            for d in knowledge.iterdir()
            if d.is_dir()
            and not d.name.startswith((".", "_"))
            and d.name not in CORE_SECTIONS
        )

    for sec_dir in sections:
        sec = sec_dir.name
        # `knowledge/core/` must not overwrite (or read as) the real core pack.
        pack_name = f"knowledge-{sec}" if sec in RESERVED_PACK_NAMES else sec
        files = _md_files(sec_dir)
        if not files:
            continue
        est = _estimate_tokens(files)
        if est < merge_below:
            aux_include.append(f"knowledge/{sec}/**/*.md")
            aux_files.extend(files)
            aux_parts.append(pack_name)
            continue
        subdirs = sorted(
            d for d in sec_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
        )
        if est > ceiling and subdirs:
            # Oversized section -> one pack per subfolder ("library" becomes
            # library-craft, library-marketing, ...). Loose files at the
            # section root become <section>-root.
            root_files = sorted(
                f for f in sec_dir.glob("*.md") if f.is_file()
            )
            if root_files:
                plans.append(
                    PackPlan(
                        name=f"{sec}-root",
                        include=[f"knowledge/{sec}/*.md"],
                        files=root_files,
                        when_to_load=f"Top-level pages of '{sec}'.",
                    )
                )
            for sub in subdirs:
                sub_files = _md_files(sub)
                if not sub_files:
                    continue
                plans.append(
                    PackPlan(
                        name=f"{sec}-{sub.name}",
                        include=[f"knowledge/{sec}/{sub.name}/**/*.md"],
                        files=sub_files,
                        when_to_load=f"Only for tasks about '{sec}/{sub.name}'.",
                    )
                )
        else:
            plans.append(
                PackPlan(
                    name=pack_name,
                    include=[f"knowledge/{sec}/**/*.md"],
                    files=files,
                    when_to_load=f"Tasks about '{sec}'.",
                )
            )

    assets_index = root / "assets-index"
    ai_files = _md_files(assets_index)
    if ai_files:
        aux_include.append("assets-index/**/*.md")
        aux_files.extend(ai_files)
        aux_parts.append("assets-index")

    if aux_include:
        plans.append(
            PackPlan(
                name="aux",
                include=aux_include,
                files=aux_files,
                when_to_load="Merged small sections: " + ", ".join(aux_parts) + ".",
                exclude=aux_exclude,
            )
        )
    return plans


def _base_repomix_config(root: Path) -> dict:
    """The base ``repomix.config.json`` (``{}`` when there is none).

    Raises :class:`RepomixConfigError` when it exists but is not a JSON
    object: an unreadable base config stops the build instead of silently
    dropping its ignore list.
    """
    cfg_path = root / "repomix.config.json"
    if not cfg_path.is_file():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepomixConfigError(f"repomix.config.json is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RepomixConfigError("repomix.config.json: the top level is not a JSON object")
    return data


def _print_config_error(exc: RepomixConfigError) -> None:
    print(f"❌ [reindex] {exc}")
    print(
        "    Nothing was built. Fix the file (plain JSON: no trailing commas or "
        "comments) — its ignore list is part of what keeps private folders out "
        "of the index."
    )


def pack_config(base: dict, plan: PackPlan, ignore: Sequence[str]) -> dict:
    """The repomix config of one pack: the base config + per-pack overrides."""
    cfg = json.loads(json.dumps(base)) if base else {}
    output = cfg.get("output")
    output = dict(output) if isinstance(output, dict) else {}
    output["filePath"] = plan.output_rel
    output.setdefault("style", "xml")
    output["compress"] = False
    output["removeComments"] = False
    output["headerText"] = PACK_HEADER.format(name=plan.name)
    cfg["output"] = output
    cfg["include"] = plan.include
    ign = cfg.get("ignore")
    ign = dict(ign) if isinstance(ign, dict) else {}
    ign.setdefault("useGitignore", True)
    ign.setdefault("useDefaultPatterns", True)
    custom = ign.get("customPatterns")
    custom = [str(p) for p in custom] if isinstance(custom, list) else []
    for pattern in [*ignore, *plan.exclude]:
        if pattern not in custom:
            custom.append(pattern)
    ign["customPatterns"] = custom
    cfg["ignore"] = ign
    cfg.setdefault("security", {"enableSecurityCheck": True})
    cfg.setdefault("tokenCount", {"encoding": "o200k_base"})
    return cfg


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_pack_configs(
    root: Path, plans: list[PackPlan], *, ignore: Sequence[str] | None = None
) -> dict[str, str]:
    """Generate .repomix/configs/<pack>.json, inheriting the base config.

    Inherits ignore/security/tokenCount and output options from the root
    repomix.config.json, then overrides per-pack path/include/header and adds
    the forced ignore patterns (`ignore`, default
    :func:`forced_ignore_patterns`). compress stays false for knowledge bases:
    full text IS the payload. Returns ``{pack name: sha256 of its config}``;
    raises :class:`RepomixConfigError` for an unusable base config.
    """
    if ignore is None:
        ignore = forced_ignore_patterns(kbc.load_config(root))
    base = _base_repomix_config(root)
    configs_dir = root / ".repomix" / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for plan in plans:
        payload = (
            json.dumps(pack_config(base, plan, ignore), ensure_ascii=False, indent=2)
            + "\n"
        )
        kbc.write_if_changed(configs_dir / f"{plan.name}.json", payload)
        digests[plan.name] = _sha256(payload.encode("utf-8"))
    return digests


def _membership(root: Path, plan: PackPlan) -> dict[str, str]:
    """``{root-relative path: sha256}`` of the files the pack should hold."""
    members: dict[str, str] = {}
    for f in plan.files:
        rel = _rel(root, f)
        if rel is None:
            continue
        try:
            members[rel] = _sha256(f.read_bytes())
        except OSError:
            continue
    return members


def _git_parents(root: Path) -> list[Path]:
    """Folders above ``root`` up to the git work tree root (repomix applies
    their .gitignore too); none when ``root`` is not inside a git work tree."""
    if (root / ".git").exists():
        return []
    walked: list[Path] = []
    for parent in root.parents:
        walked.append(parent)
        if (parent / ".git").exists():
            return walked
    return []


def _ignore_digest(root: Path, members: dict[str, str]) -> str:
    """SHA-256 of every ignore file that can hide or reveal a member.

    repomix filters the pack through .gitignore (and .ignore /
    .repomixignore) of each member's folder and its parents, and through
    .git/info/exclude, none of which is in the pack config: hiding an
    already packed page with .gitignore must still rebuild the pack.
    """
    folders = {""}
    for rel in members:
        parts = rel.split("/")[:-1]
        folders.update("/".join(parts[: i + 1]) for i in range(len(parts)))
    sources = [
        (f"{folder}/{name}".lstrip("/"), (root / folder / name) if folder else root / name)
        for folder in sorted(folders)
        for name in IGNORE_FILES
    ]
    sources.append((".git/info/exclude", root / ".git" / "info" / "exclude"))
    sources += [(str(p / ".gitignore"), p / ".gitignore") for p in _git_parents(root)]
    digest = hashlib.sha256()
    for label, path in sources:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest.update(f"{label}\0{_sha256(data)}\n".encode("utf-8"))
    return digest.hexdigest()


def read_manifest(root: Path) -> dict:
    """``.repomix/manifest.json`` written by the last index run (``{}`` if none)."""
    try:
        data = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _manifest_packs(manifest: dict) -> dict:
    packs = manifest.get("packs")
    return packs if isinstance(packs, dict) else {}


def _pack_is_fresh(
    output: Path, entry: dict, config_sha: str, members: dict, ignore_sha: str
) -> bool:
    """Fresh = the last successful build used this exact config, file set
    and ignore files.

    Membership and content are compared by hash, so a deleted, renamed or
    edited page always triggers a rebuild (mtimes do not matter), and so
    does an edited .gitignore / .ignore / .repomixignore.
    """
    return (
        output.is_file()
        and entry.get("config_sha256") == config_sha
        and entry.get("files") == members
        and entry.get("ignore_sha256") == ignore_sha
    )


def remove_orphans(root: Path, keep: set[str], manifest: dict) -> list[str]:
    """Delete the generated files of packs that left the plan.

    A renamed section or an edited ``packs:`` list used to leave its old
    .xml behind (with pages that were deleted since). Only kb_reindex's own
    files are touched: ``.repomix/<name>.xml`` of a pack known from the
    manifest, ``.repomix/configs/`` or ``.repomix/audit/``, plus that
    config and audit request. The legacy ``output.xml`` is never removed.
    """
    repomix = root / ".repomix"
    configs = repomix / "configs"
    audit = repomix / "audit"
    known = set(_manifest_packs(manifest))
    if configs.is_dir():
        known |= {p.stem for p in configs.glob("*.json")}
    if audit.is_dir():
        known |= {
            p.name[: -len("__request.md")]
            for p in audit.glob("*__request.md")
            if p.name != "CROSS_PACK__request.md"
        }
    removed: list[str] = []
    for name in sorted(known - keep):
        if not isinstance(name, str) or name != _safe_pack_name(name):
            continue
        hit = False
        for path in (
            repomix / f"{name}.xml",
            configs / f"{name}.json",
            audit / f"{name}__request.md",
        ):
            try:
                path.unlink()
                hit = True
            except FileNotFoundError:
                pass
            except OSError as exc:
                print(f"⚠️  [reindex] could not remove {path}: {exc}")
        _unlink(repomix / f"{name}.xml{BUILD_SUFFIX}")  # left by an interrupted build
        if hit:
            removed.append(name)
    return removed


AUDIT_CHECKLIST = """\
- Contradictions with other pages in this pack
- Missing cross-refs between related pages
- Data gaps (too thin to answer confidently)
- Consolidation candidates
- Freshness: which pages need re-verify

A finding without `file:line` and a short quote does not enter the report.
"""


def write_audit_requests(root: Path, plans: list[PackPlan]) -> None:
    """Write per-pack !audit briefs. Fresh session; no kb_audit.py."""
    dest = root / ".repomix" / "audit"
    dest.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        path = dest / f"{plan.name}__request.md"
        kbc.write_if_changed(
            path,
            "\n".join(
                [
                    f"# Audit request — pack `{plan.name}`",
                    "",
                    "Open this in a **new session** with a clean context.",
                    f"Load only `.repomix/{plan.name}.xml` (or the files it covers).",
                    f"When to load: {plan.when_to_load or 'see PACKS_STATUS.md'}",
                    "",
                    "## Checklist",
                    AUDIT_CHECKLIST.rstrip(),
                    "",
                    "## Report format",
                    "",
                    "```markdown",
                    "## Finding",
                    "- file: `knowledge/.../page.md:12`",
                    "- quote: \"…\"",
                    "- issue: …",
                    "```",
                    "",
                    "Write the answer in `eval/results/<date>__audit-"
                    f"{plan.name}.md` or keep it in the session.",
                    "",
                ]
            ),
        )
    cross = dest / "CROSS_PACK__request.md"
    names = ", ".join(f"`{p.name}`" for p in plans) or "(no packs)"
    kbc.write_if_changed(
        cross,
        "\n".join(
            [
                "# Audit request — cross-pack (titles only)",
                "",
                "New session. Do **not** load full packs.",
                f"Packs in this base: {names}.",
                "Read `.repomix/PACKS_STATUS.md` and page titles / H1s only.",
                "Look for contradictions that span two domains.",
                "Same rule: no `file:line` + quote → drop the finding.",
                "",
            ]
        ),
    )


def _state_label(entry: dict, root: Path) -> str:
    state = entry.get("state", "")
    built_at = entry.get("built_at")
    if state == "rebuilt":
        return f"rebuilt {built_at}"
    if state == "fresh":
        return f"fresh (built {built_at})"
    has_copy = bool(built_at) and (root / str(entry.get("output", ""))).is_file()
    suffix = f"; copy from {built_at} kept" if has_copy else ""
    if state == "STALE":
        return f"STALE — repomix unavailable{suffix}"
    return f"FAILED{suffix}"


def _status_rows(manifest: dict) -> list[tuple[str, dict]]:
    """``(row name, entry)`` of every pack, or of the legacy monolith."""
    rows = [(name, e) for name, e in _manifest_packs(manifest).items() if isinstance(e, dict)]
    legacy = manifest.get("legacy")
    if manifest.get("mode") == "legacy" and isinstance(legacy, dict):
        name = Path(str(legacy.get("output") or REPOMIX_DEFAULT_OUTPUT)).name
        rows.append((f"{name} (legacy monolith)", legacy))
    return rows


def render_packs_status(root: Path, manifest: dict) -> str:
    rows = _status_rows(manifest)
    ceiling = int(manifest.get("ceiling") or 0)
    legacy = manifest.get("mode") == "legacy"
    lines = [
        "# Knowledge-base packs — build status",
        "",
        "Auto-generated by kb_reindex.py. Do not edit.",
        f"Checked: {manifest.get('checked_at')} · builder: {manifest.get('builder')}",
        "",
    ]
    if legacy:
        lines += [
            "Legacy mode: one monolithic index, no packs (no `index:` section in "
            "kb.config.yml, or `index.enabled: false`). See kb-docs/05_INDEX.md.",
            "",
        ]
    if manifest.get("error"):
        lines += [f"**Index not built:** {manifest['error']}", ""]
    # Four columns, the token cell a number with an optional `⚠ OVER`:
    # kb_doctor.py reads the tokens from cell 2 and the build state from cell 3.
    lines += [
        "| Pack | ~Tokens (o200k est.) | Last build | Load when |",
        "|------|----------------------|------------|-----------|",
    ]
    for name, entry in rows:
        tokens = f"{int(entry.get('tokens') or 0):,}"
        if entry.get("over_ceiling"):
            tokens += " ⚠ OVER"
        when = str(entry.get("when_to_load", "")).replace("|", "\\|")
        lines.append(f"| {name} | {tokens} | {_state_label(entry, root)} | {when} |")

    def _count(names: list[str]) -> str:
        return f"{len(names)} ({', '.join(names)})" if names else "0"

    over = [n for n, e in rows if e.get("over_ceiling")]
    failed = [n for n, e in rows if e.get("state") == "FAILED"]
    stale = [n for n, e in rows if e.get("state") == "STALE"]
    lines += [
        "",
        f"Pack ceiling: {ceiling:,} tokens. OVER ceiling: {_count(over)} · "
        f"FAILED: {_count(failed)} · STALE: {_count(stale)}.",
    ]
    left_out = [
        f"{name}: {', '.join(str(p) for p in e['left_out'])}"
        for name, e in rows
        if isinstance(e.get("left_out"), list) and e["left_out"]
    ]
    if left_out:
        lines.append(
            "Left out by repomix (its security check found credential-looking text — "
            "`python3 scripts/kb_lint.py` names the lines — or an ignore file hides "
            "them): " + "; ".join(left_out) + "."
        )
    if manifest.get("removed"):
        lines.append("Removed orphan packs: " + ", ".join(manifest["removed"]) + ".")
    if not legacy:
        lines.append(
            "Route via knowledge/routing-table.md; load AT MOST ONE domain pack per task."
        )
    lines.append("")
    return "\n".join(lines)


def _write_index_state(root: Path, manifest: dict) -> None:
    """Write .repomix/manifest.json and .repomix/PACKS_STATUS.md."""
    (root / ".repomix").mkdir(parents=True, exist_ok=True)
    kbc.write_json(root / MANIFEST_REL, manifest)
    kbc.atomic_write_text(root / PACKS_STATUS_REL, render_packs_status(root, manifest))


def _output_tokens(output: Path) -> int:
    try:
        return int(output.stat().st_size / CHARS_PER_TOKEN)
    except OSError:
        return 0


def _run_repomix_config(root: Path, config_rel: str, cmd: list[str], output_rel: str) -> bool:
    """Build one pack into ``output_rel`` (``-o`` overrides the config's
    filePath). Separate function so tests can monkeypatch it."""
    return _run_repomix([*cmd, "-c", config_rel, "-o", output_rel, "--quiet"], root) == 0


def _build_pack(root: Path, plan: PackPlan, cmd: list[str]) -> bool:
    """True only when repomix succeeded AND wrote a new file, which then
    replaces the pack; a failed build leaves the previous copy untouched."""
    output = root / plan.output_rel
    building = output.with_name(output.name + BUILD_SUFFIX)
    _unlink(building)
    ok = _run_repomix_config(root, plan.config_rel, cmd, plan.output_rel + BUILD_SUFFIX)
    if ok and building.is_file():
        building.replace(output)
        return True
    _unlink(building)
    return False


def _packed_paths(root: Path, plan: PackPlan) -> set[str] | None:
    """Root-relative paths repomix wrote into the pack; ``None`` when the
    output cannot be compared (not XML, or `output.files: false`)."""
    try:
        cfg = json.loads((root / plan.config_rel).read_text(encoding="utf-8"))
        text = (root / plan.output_rel).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    output = cfg.get("output") if isinstance(cfg, dict) else None
    output = output if isinstance(output, dict) else {}
    if output.get("style", "xml") != "xml" or output.get("files") is False:
        return None
    if not _XML_FILES_RE.search(text):
        return None
    return {html.unescape(path).replace("\\", "/") for path in _XML_FILE_RE.findall(text)}


def _left_out(root: Path, plan: PackPlan, members: dict[str, str]) -> list[str]:
    """Members the built pack does not contain. repomix drops them without a
    word (`--quiet`): its security check found credential-looking text in
    them, or a .gitignore / .ignore / .repomixignore hides them."""
    packed = _packed_paths(root, plan)
    return [] if packed is None else sorted(set(members) - packed)


def run_pack_index(
    root: Path,
    index_cfg: dict,
    *,
    force: bool = False,
    cfg: "kbc.KbConfig | None" = None,
) -> bool:
    """Build the pack-based index.

    Returns True when every planned pack is fresh or was rebuilt. Always
    records the outcome in ``.repomix/manifest.json`` and
    ``.repomix/PACKS_STATUS.md`` — also when nothing could be built.
    """
    cfg = cfg or kbc.load_config(root)
    ceiling = index_ceiling(index_cfg)
    ignore = forced_ignore_patterns(cfg)
    plans = plan_packs(root, index_cfg, ignore=ignore)
    previous = read_manifest(root)
    old_packs = _manifest_packs(previous)
    removed = remove_orphans(root, {p.name for p in plans}, previous)
    for name in removed:
        print(f"🧹 [reindex] removed orphan pack '{name}' (no longer in the plan)")
    write_audit_requests(root, plans)
    cmd = repomix_command(cfg)
    manifest: dict = {
        "generator": "kb_reindex.py",
        "engine_version": kbc.ENGINE_VERSION,
        "checked_at": kbc.now_iso(),
        "builder": _describe_builder(cmd),
        "mode": "packs",
        "ceiling": ceiling,
        "packs": {},
        "removed": removed,
    }
    if not plans:
        print("⚠️  [reindex] index.packs produced an empty plan; nothing to build")
        manifest["error"] = "index.packs produced an empty plan"
        _write_index_state(root, manifest)
        return False

    try:
        digests = write_pack_configs(root, plans, ignore=ignore)
    except RepomixConfigError as exc:
        _print_config_error(exc)
        manifest["error"] = str(exc)
        for plan in plans:
            old = old_packs.get(plan.name)
            entry = dict(old) if isinstance(old, dict) else {}
            entry.update(
                output=plan.output_rel,
                config=plan.config_rel,
                state="FAILED",
                tokens=plan.est_tokens,
                over_ceiling=plan.est_tokens > ceiling,
                when_to_load=plan.when_to_load,
                config_sha256=None,
                files=None,
            )
            manifest["packs"][plan.name] = entry
        _write_index_state(root, manifest)
        return False

    counts = {"rebuilt": 0, "fresh": 0, "FAILED": 0, "STALE": 0}
    announced_npx = False
    for plan in plans:
        old = old_packs.get(plan.name)
        entry = dict(old) if isinstance(old, dict) else {}
        output = root / plan.output_rel
        members = _membership(root, plan)
        ignore_sha = _ignore_digest(root, members)
        if not force and _pack_is_fresh(output, entry, digests[plan.name], members, ignore_sha):
            state = "fresh"
        elif cmd is None:
            state = "STALE"
        else:
            if not announced_npx:
                _announce_npx(cmd)
                announced_npx = True
            if _build_pack(root, plan, cmd):
                state = "rebuilt"
                # A fresh pack keeps the list of its last build.
                left_out = _left_out(root, plan, members)
                entry.update(
                    built_at=kbc.now_iso(),
                    config_sha256=digests[plan.name],
                    files=members,
                    ignore_sha256=ignore_sha,
                    left_out=left_out,
                )
                if left_out:
                    print(
                        f"⚠️  [reindex] pack '{plan.name}': repomix left out "
                        f"{len(left_out)} file(s) — {', '.join(left_out)}. Its security "
                        "check found credential-looking text (python3 scripts/kb_lint.py "
                        "names the lines), or an ignore file hides them."
                    )
            else:
                state = "FAILED"
                print(
                    f"❌ [reindex] pack '{plan.name}' failed to build or wrote no "
                    f"output ({plan.output_rel})"
                )
                # A copy from an earlier build is kept but is out of date.
                entry.update(config_sha256=None, files=None, ignore_sha256=None)
        counts[state] += 1
        tokens = _output_tokens(output) if state in ("fresh", "rebuilt") else plan.est_tokens
        entry.update(
            output=plan.output_rel,
            config=plan.config_rel,
            state=state,
            tokens=tokens,
            over_ceiling=tokens > ceiling,
            when_to_load=plan.when_to_load,
        )
        manifest["packs"][plan.name] = entry

    _write_index_state(root, manifest)
    print(
        f"📦 [reindex] packs: built {counts['rebuilt']}, fresh {counts['fresh']}, "
        f"failed {counts['FAILED']}, stale {counts['STALE']} → {PACKS_STATUS_REL}"
    )
    oversized = [
        f"{name} (~{entry['tokens']:,})"
        for name, entry in manifest["packs"].items()
        if entry["over_ceiling"]
    ]
    for warn in oversized:
        print(f"⚠️  [reindex] pack over ceiling ({ceiling:,}): {warn}")
    if oversized:
        print(
            "    Split it further: sub-split the section by subfolder or list "
            "explicit packs in kb.config.yml (index.packs)."
        )
    if counts["STALE"]:
        _print_missing_repomix(cfg)
    stale_monolith = root / ".repomix" / "output.xml"
    if stale_monolith.is_file():
        print(
            "ℹ️  [reindex] legacy .repomix/output.xml still on disk; "
            "packs replace it — safe to delete."
        )
    return counts["FAILED"] == 0 and counts["STALE"] == 0


def run_index(root: Path, cfg: "kbc.KbConfig", *, force: bool = False) -> bool:
    """Build the index only: packs when configured, legacy monolith otherwise.

    True when the index is complete and current.
    """
    index_cfg = cfg.index or {}
    if index_cfg and index_cfg.get("enabled", True):
        return run_pack_index(root, index_cfg, force=force, cfg=cfg)
    return run_repomix(root, cfg)


# ---------------------------------------------------------------------------
# Status, modes, CLI
# ---------------------------------------------------------------------------


def write_status(root: Path, cfg: "kbc.KbConfig") -> None:
    """Refresh STATUS.md through kb_status.py unless status.enabled is false."""
    if not cfg.status_enabled:
        return
    try:
        import kb_status
    except ImportError:
        return  # a deployment without kb_status.py
    try:
        path, items = kb_status.write_status(root, cfg=cfg)
    except OSError as exc:
        print(f"⚠️  [reindex] could not write {cfg.status_file}: {exc}")
        return
    if path is None:
        return  # kb_status explained why on stderr
    summary = f"{len(items)} item(s) need attention" if items else "all clear"
    print(f"📋 [reindex] {_rel(root, path) or path}: {summary}")


def reindex(
    root: Path,
    *,
    quick: bool = False,
    do_index: bool = True,
    do_ingest: bool = True,
    force_index: bool = False,
) -> int:
    cfg = kbc.load_config(root)
    rc = 0

    if do_ingest:
        print("🔄 [reindex] ingest pipeline...")
        code = _py("kb_ingest.py", root=root)
        if code != 0:
            print(f"⚠️  [reindex] kb_ingest.py exited with {code}; the other steps still run")
            rc = 1

    print("🧭 [reindex] routing pages...")
    _py("kb_route.py", root=root)

    print("🩺 [reindex] quick lint...")
    _py("kb_lint.py", "--quick", root=root)

    if not quick:
        _consolidate(root, cfg)

    if do_index and not run_index(root, cfg, force=force_index):
        rc = 1

    write_status(root, cfg)
    print("✅ [reindex] done" if rc == 0 else "⚠️  [reindex] done with problems (see above)")
    return rc


def index_only(root: Path, *, force: bool = False) -> int:
    """Index + STATUS.md, nothing else. 0 when the index is complete."""
    cfg = kbc.load_config(root)
    ok = run_index(root, cfg, force=force)
    write_status(root, cfg)
    return 0 if ok else 1


def run_hook(root: Path, *, force: bool = False) -> int:
    """Git-hook mode: index + STATUS.md only, never queues behind another run.

    Everything it prints goes to ``.kb-state/hooks.log``; it always returns 0
    so a hook never disturbs git.
    """
    try:
        log = open(kbc.state_dir(root) / HOOK_LOG, "a", encoding="utf-8")
    except OSError:
        return 0
    with log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        print(f"--- {kbc.now_iso()} kb_reindex --hook")
        try:
            with contextlib.ExitStack() as stack:
                try:
                    stack.enter_context(
                        kbc.kb_lock(root, "pipeline", timeout=HOOK_LOCK_TIMEOUT)
                    )
                except kbc.KbLockTimeout:
                    print(
                        "hook: another KB run holds the pipeline lock; skipped "
                        "(the next run catches up)"
                    )
                    return 0
                except OSError as exc:
                    print(f"hook: cannot take the pipeline lock ({exc}); skipped")
                    return 0
                code = index_only(root, force=force)
                print("hook: done" if code == 0 else "hook: index incomplete (see above)")
        except Exception:  # noqa: BLE001 — a hook must never fail the commit
            traceback.print_exc()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Engine — cross-platform reindex orchestrator"
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="skip the consolidation block (lint report, NLP batch, reflection request)",
    )
    parser.add_argument(
        "--no-watch", action="store_true", help="deprecated alias of --quick"
    )
    parser.add_argument("--no-index", action="store_true", help="skip the index step")
    parser.add_argument("--no-ingest", action="store_true", help="skip ingest step")
    parser.add_argument(
        "--force", action="store_true", help="rebuild all packs even if fresh"
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="only (re)generate the index and STATUS.md; skip ingest/routing/lint/consolidation",
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help=(
            "git-hook mode: like --index-only, but gives up when another run holds "
            "the pipeline lock, logs to .kb-state/hooks.log and always exits 0"
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root or kbc.find_kb_root()).resolve()
    if not kbc.kb_config_path(root).is_file():
        # Not a base: writing STATUS.md, .kb-state/ or a repomix run over the
        # folder here would create a phantom base.
        print(
            f"❌ [reindex] {root} is not a knowledge base (no "
            f"{kbc.DEFAULT_CONFIG_FILENAME}); nothing done. Run it from the base "
            "root or pass --root.",
            file=sys.stderr,
        )
        return 0 if args.hook else 2
    if args.no_watch:
        print(
            "⚠️  [reindex] --no-watch is deprecated (it always meant "
            "'skip consolidation'); use --quick",
            file=sys.stderr,
        )
        args.quick = True
    if args.hook:
        return run_hook(root, force=args.force)

    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(kbc.kb_lock(root, "pipeline", timeout=0))
        except kbc.KbLockTimeout:
            print(
                "⏳ [reindex] another KB run (watcher, git hook or reindex) holds the "
                f"pipeline lock; waiting up to {int(PIPELINE_LOCK_TIMEOUT)} s..."
            )
            try:
                stack.enter_context(
                    kbc.kb_lock(root, "pipeline", timeout=PIPELINE_LOCK_TIMEOUT)
                )
            except kbc.KbLockTimeout:
                print("❌ [reindex] the pipeline is still busy; try again later", file=sys.stderr)
                return 1
        except OSError as exc:
            print(f"⚠️  [reindex] cannot take the pipeline lock ({exc}); running without it")

        if args.index_only:
            return index_only(root, force=args.force)
        return reindex(
            root,
            quick=args.quick,
            do_index=not args.no_index,
            do_ingest=not args.no_ingest,
            force_index=args.force,
        )


if __name__ == "__main__":
    raise SystemExit(main())
