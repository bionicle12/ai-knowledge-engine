#!/usr/bin/env python3
"""kb_doctor — post-deployment smoke-test for AI Knowledge Engine.

Verifies that:
  1. Required Python packages are importable (optional ones: warnings)
  2. Mandatory directory structure exists
  3. kb.config.yml is parseable and has the expected shape
  4. Codex / Claude Code instruction environment (AGENTS.md placement,
     32 KiB budget, AGENTS.override.md, CLAUDE.md import — expected when
     index.primary_agent is claude-code)
  5. (Optional) spaCy model loads; NLTK data for RAKE is downloaded
  6. Frontmatter helpers work on a sample fixture
  7. log.md is writable — checked without writing to it
  8. Index: repomix (or the pinned `npx` fallback) and the last build in
     .repomix/PACKS_STATUS.md (FAILED / not rebuilt / over-ceiling packs,
     knowledge/ changed since the last reindex)
  9. Engine scripts: every scripts/kb_*.py imports, and every kb_common name
     they use exists (a partial upgrade breaks this)
 10. Upgrade leftovers: unmerged `.new` sidecars
 11. Runtime docs: kb-docs/ holds every module AGENTS.md & co. point to
 12. The base venv: nested .venv/.venv, a moved venv (activate / pip point
     elsewhere), doctor itself running outside the venv

Doctor never writes to the base (no log.md entry).

Exit codes:
  0 — doctor passes: no errors (warnings are advice and do not fail it)
  2 — at least one error

Usage:
  python3 scripts/kb_doctor.py
  python3 scripts/kb_doctor.py --self-test       # run on this script's own repo
  python3 scripts/kb_doctor.py --skip-nlp        # don't load spaCy / NLTK data
  python3 scripts/kb_doctor.py --json            # machine-readable output
"""
from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

# kb_common is a sibling module
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    import kb_common as kbc  # noqa: E402
except Exception as _exc:  # noqa: BLE001 — a broken install still gets a verdict
    if __name__ != "__main__":
        raise
    print(
        f"❌ scripts:consistency: scripts/kb_common.py does not import "
        f"({type(_exc).__name__}: {_exc}) — install the requirements "
        "(pip install -r requirements.txt) or merge scripts/kb_common.py.new\n\n"
        "Summary: 0 ok, 0 warn, 1 error — FAIL (exit 2): fix the errors above",
        file=sys.stderr,
    )
    raise SystemExit(2) from None

# Doctor is what diagnoses a partial upgrade, so it must run against an older
# kb_common.py too: no 0.16-only kb_common name is used at import time, and
# `scripts:consistency` names what is missing.
KB_DOCS_DIR = getattr(kbc, "KB_DOCS_DIR", "kb-docs")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    severity: str            # "ok" | "warn" | "error"
    message: str = ""
    details: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


REQUIRED_PACKAGES = [
    ("yaml", "pyyaml"),
    ("slugify", "python-slugify"),
]

OPTIONAL_PACKAGES = [
    ("docx", "python-docx"),
    ("pptx", "python-pptx"),
    ("pypdf", "pypdf"),
    ("pandas", "pandas"),
    ("openpyxl", "openpyxl"),
    ("watchdog", "watchdog"),
    ("rake_nltk", "rake-nltk"),
    ("keybert", "keybert"),
]

# How to get an optional package that requirements.txt does not install.
OPTIONAL_PACKAGE_HINTS = {
    "keybert": (
        "ingest uses RAKE keywords without it. Install: pip install -r requirements-nlp.txt "
        "(CPU torch first: pip install torch --index-url https://download.pytorch.org/whl/cpu)"
    ),
}


def check_python_version() -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        return CheckResult(
            "python-version",
            "error",
            f"Python 3.11+ required, found {major}.{minor}",
        )
    return CheckResult("python-version", "ok", f"Python {major}.{minor}")


def check_required_packages() -> list[CheckResult]:
    results: list[CheckResult] = []
    for module_name, package_name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(module_name)
            results.append(CheckResult(f"req:{package_name}", "ok"))
        except ImportError as e:
            results.append(
                CheckResult(
                    f"req:{package_name}",
                    "error",
                    f"Required package missing: {package_name}. Install: pip install -r requirements.txt",
                    details=[str(e)],
                )
            )
    return results


def check_optional_packages() -> list[CheckResult]:
    results: list[CheckResult] = []
    for module_name, package_name in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(module_name)
            results.append(CheckResult(f"opt:{package_name}", "ok"))
        except ImportError:
            results.append(
                CheckResult(
                    f"opt:{package_name}",
                    "warn",
                    f"Optional package missing: {package_name} — "
                    + OPTIONAL_PACKAGE_HINTS.get(package_name, "some features will be unavailable"),
                )
            )
    return results


def check_structure(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    expected_top = ["raw", "processed", "knowledge", "assets-index", "review"]
    for d in expected_top:
        path = root / d
        if path.is_dir():
            results.append(CheckResult(f"struct:{d}/", "ok"))
        else:
            results.append(
                CheckResult(
                    f"struct:{d}/",
                    "warn",
                    f"Directory missing: {d}/ (will be created by kb_ingest.py on first run)",
                )
            )
    return results


# Codex loads every AGENTS.md from git-root down to cwd, then stops once the
# combined size hits project_doc_max_bytes (32 KiB by default). See
# https://learn.chatgpt.com/docs/agent-configuration/agents-md
KIB = 1024
AGENTS_SIZE_WARN_BYTES = 10 * KIB
CODEX_BUDGET_WARN_BYTES = 24 * KIB   # 75% of the default 32 KiB cap
CODEX_BUDGET_MAX_BYTES = 32 * KIB


def find_git_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_codex_home(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env)
    return Path.home() / ".codex"


def _codex_global_agents(codex_home: Path) -> Path | None:
    """File Codex actually loads at global scope: override, else AGENTS.md."""
    override = codex_home / "AGENTS.override.md"
    if override.is_file() and override.stat().st_size > 0:
        return override
    agents = codex_home / "AGENTS.md"
    if agents.is_file() and agents.stat().st_size > 0:
        return agents
    return None


def _byte_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def check_agent_env(
    root: Path,
    *,
    codex_home: Path | None = None,
) -> list[CheckResult]:
    """Six cheap checks for silent Codex / Claude Code instruction failures."""
    root = root.resolve()
    home = resolve_codex_home(codex_home)
    results: list[CheckResult] = []

    git_root = find_git_root(root)
    agents_at_root = root / "AGENTS.md"
    if not agents_at_root.is_file():
        results.append(
            CheckResult(
                "agent-env:agents-at-git-root",
                "error",
                "AGENTS.md is missing from the base root — Codex has nothing "
                "to load for this knowledge base",
            )
        )
    elif git_root is None:
        results.append(
            CheckResult(
                "agent-env:agents-at-git-root",
                "warn",
                "not a git repository — Codex will only look in the current "
                "directory for AGENTS.md",
            )
        )
    elif git_root == root:
        results.append(
            CheckResult(
                "agent-env:agents-at-git-root",
                "ok",
                f"AGENTS.md is at git-root ({git_root})",
            )
        )
    elif (git_root / "AGENTS.md").is_file():
        results.append(
            CheckResult(
                "agent-env:agents-at-git-root",
                "ok",
                f"AGENTS.md is at git-root ({git_root}) and in this base",
            )
        )
    else:
        # Pre-finalize layout: base lives in knowledge-base/, git-root is the
        # project. Codex started from the repo root will miss this file;
        # finalize.sh promotes it. Warn, do not fail the deploy smoke-test.
        results.append(
            CheckResult(
                "agent-env:agents-at-git-root",
                "warn",
                "AGENTS.md is not at the git-root "
                f"({git_root}) — Codex started from the repo root will not "
                "load it. After finalize.sh the base should sit at the "
                "project root",
            )
        )

    agents_path = agents_at_root if agents_at_root.is_file() else git_root / "AGENTS.md" if git_root else None
    agents_bytes = _byte_size(agents_path) if agents_path and agents_path.is_file() else 0
    if agents_bytes > AGENTS_SIZE_WARN_BYTES:
        results.append(
            CheckResult(
                "agent-env:agents-size",
                "warn",
                f"AGENTS.md is {agents_bytes} B (>{AGENTS_SIZE_WARN_BYTES} B / 10 KiB) "
                "— approaching the Codex instruction budget; consider !refactor",
            )
        )
    else:
        results.append(
            CheckResult(
                "agent-env:agents-size",
                "ok",
                f"AGENTS.md is {agents_bytes} B",
            )
        )

    global_agents = _codex_global_agents(home)
    global_bytes = _byte_size(global_agents) if global_agents else 0
    combined = agents_bytes + global_bytes
    global_label = str(global_agents) if global_agents else "no global AGENTS.md"
    if combined > CODEX_BUDGET_WARN_BYTES:
        results.append(
            CheckResult(
                "agent-env:codex-budget-75",
                "warn",
                f"combined AGENTS.md size is {combined} B "
                f"(>{CODEX_BUDGET_WARN_BYTES} B / 75% of 32 KiB) "
                f"[{global_label} + base]",
            )
        )
    else:
        results.append(
            CheckResult(
                "agent-env:codex-budget-75",
                "ok",
                f"combined AGENTS.md size is {combined} B",
            )
        )
    if combined > CODEX_BUDGET_MAX_BYTES:
        results.append(
            CheckResult(
                "agent-env:codex-budget-cap",
                "error",
                f"combined AGENTS.md size is {combined} B "
                f"(>{CODEX_BUDGET_MAX_BYTES} B / 32 KiB) — Codex will stop "
                "adding instruction files and may drop this base's AGENTS.md",
            )
        )
    else:
        results.append(
            CheckResult(
                "agent-env:codex-budget-cap",
                "ok",
                f"combined AGENTS.md size is {combined} B (under 32 KiB)",
            )
        )

    override = root / "AGENTS.override.md"
    if override.is_file():
        results.append(
            CheckResult(
                "agent-env:agents-override",
                "error",
                "AGENTS.override.md is in the base root — Codex will load it "
                "instead of AGENTS.md and ignore this base's instructions",
            )
        )
    else:
        results.append(
            CheckResult("agent-env:agents-override", "ok", "no AGENTS.override.md")
        )

    claude = root / "CLAUDE.md"
    if claude.is_file():
        try:
            claude_text = claude.read_text(encoding="utf-8")
        except OSError as e:
            results.append(
                CheckResult(
                    "agent-env:claude-md-import",
                    "warn",
                    f"CLAUDE.md exists but could not be read: {e}",
                )
            )
        else:
            if "@AGENTS.md" in claude_text:
                results.append(
                    CheckResult(
                        "agent-env:claude-md-import",
                        "ok",
                        "CLAUDE.md imports @AGENTS.md",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "agent-env:claude-md-import",
                        "warn",
                        "CLAUDE.md exists but does not contain @AGENTS.md — "
                        "Claude Code will not load this base's instructions",
                    )
                )
    elif str(_config_or_defaults(root).index.get("primary_agent") or "").lower() == "claude-code":
        results.append(
            CheckResult(
                "agent-env:claude-md-import",
                "warn",
                "index.primary_agent is claude-code but there is no CLAUDE.md — "
                "Claude Code will not load AGENTS.md; create CLAUDE.md with the "
                "single line @AGENTS.md",
            )
        )
    else:
        results.append(
            CheckResult(
                "agent-env:claude-md-import",
                "ok",
                "no CLAUDE.md (optional; create on finalize if you use Claude Code)",
            )
        )

    return results


def check_config(root: Path, *, self_test: bool = False) -> CheckResult:
    cfg_path = kbc.kb_config_path(root)
    if not cfg_path.is_file():
        # In --self-test (running against the source repo, not a deployed base)
        # there is intentionally no kb.config.yml — that's a soft warning, not a
        # deployment error.
        severity = "warn" if self_test else "error"
        return CheckResult(
            "config",
            severity,
            f"{kbc.DEFAULT_CONFIG_FILENAME} not found in {root}"
            + (" (expected in --self-test)" if self_test else ""),
        )
    try:
        cfg = kbc.load_config(root)
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            "config",
            "error",
            f"Failed to parse {kbc.DEFAULT_CONFIG_FILENAME}: {e}",
        )
    notes = []
    if cfg.mode not in ("default", "super"):
        notes.append(f"unexpected mode={cfg.mode}")
    if not cfg.raw.get("knowledge_base"):
        notes.append("missing 'knowledge_base' top-level key")
    if not cfg.raw.get("mode_profiles"):
        notes.append("missing 'mode_profiles' (mode-aware features won't work)")
    if notes:
        return CheckResult(
            "config",
            "warn",
            "Config loaded but has issues: " + "; ".join(notes),
        )
    return CheckResult(
        "config", "ok",
        f"mode={cfg.mode}, language={cfg.primary_language}, instructions_version={cfg.instructions_version}",
    )


def check_spacy(model_name: str, fallback: str) -> CheckResult:
    try:
        import spacy  # type: ignore[import-untyped]
    except ImportError:
        return CheckResult(
            "nlp:spacy",
            "warn",
            "spaCy not installed (optional). NLP enrichment will be skipped.",
        )
    try:
        spacy.load(model_name)
        return CheckResult("nlp:spacy", "ok", f"loaded {model_name}")
    except Exception:
        try:
            spacy.load(fallback)
            return CheckResult(
                "nlp:spacy",
                "warn",
                f"primary model '{model_name}' not available, fallback '{fallback}' loaded",
            )
        except Exception as e:  # noqa: BLE001
            return CheckResult(
                "nlp:spacy",
                "warn",
                f"No spaCy model available. Install: python3 -m spacy download {model_name}",
                details=[str(e)],
            )


def check_frontmatter_roundtrip() -> CheckResult:
    sample = "---\nfoo: bar\nlist:\n  - 1\n  - 2\n---\nbody text\n"
    meta, body = kbc.parse_frontmatter(sample)
    if meta != {"foo": "bar", "list": [1, 2]} or body != "body text\n":
        return CheckResult(
            "frontmatter:parse",
            "error",
            f"unexpected parse: meta={meta!r}, body={body!r}",
        )
    rendered = kbc.render_frontmatter(meta, body)
    meta2, body2 = kbc.parse_frontmatter(rendered)
    if meta2 != meta or body2 != body:
        return CheckResult(
            "frontmatter:roundtrip",
            "error",
            "render→parse not stable",
        )
    return CheckResult("frontmatter", "ok")


def check_log_writable(root: Path) -> CheckResult:
    """log.md (or, before the first entry, the base root) accepts writes.

    Read-only: doctor used to append a smoke-test entry on every run.
    """
    log = kbc.log_path(root)
    probe = log if log.exists() else root
    if os.access(probe, os.W_OK):
        if log.exists():
            return CheckResult("log:writable", "ok", f"{log} is writable")
        return CheckResult(
            "log:writable", "ok",
            f"{root} is writable (log.md is created by the first logged operation)",
        )
    return CheckResult("log:writable", "error", f"cannot write to {probe}")


def check_media(root: Path) -> list[CheckResult]:
    """Report transcription (STT) and OCR readiness. Soft checks only.

    These are warnings, never errors: media support is optional. The goal is to
    surface problems (notably the macOS ffmpeg-PATH trap) BEFORE the user drops
    an audio file and the agent tries to transcribe it blindly.
    """
    results: list[CheckResult] = []
    try:
        cfg = kbc.load_config(root)
    except Exception:  # noqa: BLE001
        cfg = None

    # ffmpeg (only needed by the openai-whisper fallback, not faster-whisper)
    ffmpeg = kbc.find_ffmpeg()
    if ffmpeg:
        results.append(CheckResult("media:ffmpeg", "ok", f"found at {ffmpeg}"))
    else:
        results.append(
            CheckResult(
                "media:ffmpeg",
                "ok",
                "not found — fine, the default STT backend (faster-whisper) "
                "does not need it",
            )
        )

    # STT backends
    try:
        import kb_stt  # noqa: WPS433

        stt_usable = kb_stt.available_backends(cfg)
        if stt_usable:
            results.append(
                CheckResult("media:stt", "ok", f"available: {', '.join(stt_usable)}")
            )
        else:
            results.append(
                CheckResult(
                    "media:stt",
                    "warn",
                    "no transcription backend. Install: pip install -r requirements-media.txt",
                )
            )
    except Exception as e:  # noqa: BLE001
        results.append(CheckResult("media:stt", "warn", f"could not probe STT: {e}"))

    # OCR backends
    try:
        import kb_ocr  # noqa: WPS433

        ocr_usable = kb_ocr.available_backends(cfg)
        if ocr_usable:
            # The languages to read vs. what the backends can read (the same
            # lines as `kb_ocr.py --check`): missing Tesseract data is a setup
            # problem the OCR failure messages send the owner here for.
            notes = kb_ocr.language_report(kb_ocr.ocr_languages(cfg), ocr_usable)
            gaps = [n for n in notes if " — missing " in n or "install Tesseract" in n]
            results.append(
                CheckResult(
                    "media:ocr",
                    "warn" if gaps else "ok",
                    f"available: {', '.join(ocr_usable)}"
                    + ("; some languages cannot be read — see below" if gaps else ""),
                    details=gaps,
                )
            )
        else:
            results.append(
                CheckResult(
                    "media:ocr",
                    "warn",
                    "no OCR backend. Install: pip install rapidocr-onnxruntime",
                )
            )
    except Exception as e:  # noqa: BLE001
        results.append(CheckResult("media:ocr", "warn", f"could not probe OCR: {e}"))

    return results


def check_sync(root: Path) -> list[CheckResult]:
    """Cross-base import/export readiness (see kb-docs/16_MERGE.md)."""
    results: list[CheckResult] = []

    missing_scripts = [
        name for name in ("kb_export.py", "kb_import.py")
        if not (root / "scripts" / name).is_file()
    ]
    if missing_scripts:
        results.append(
            CheckResult(
                "sync:scripts",
                "warn",
                f"missing: {', '.join(missing_scripts)} "
                "(run kb_update.py to pull them into this base)",
            )
        )
    else:
        results.append(CheckResult("sync:scripts", "ok"))

    sync_root = kbc.sync_dir(root)
    if not sync_root.is_dir():
        results.append(
            CheckResult(
                "sync:workspace",
                "warn",
                "sync/ not created yet (kb_ingest.py --init-dirs or the first "
                "export/import will create it)",
            )
        )
    else:
        missing_dirs = [d for d in kbc.SYNC_DIRS if not (sync_root / d).is_dir()]
        results.append(
            CheckResult("sync:workspace", "warn", f"missing sub-dirs: {', '.join(missing_dirs)}")
            if missing_dirs
            else CheckResult("sync:workspace", "ok")
        )

    queue = root / "review" / "needs-merge"
    if queue.is_dir():
        pending = [p for p in queue.glob("*.md")]
        if pending:
            results.append(
                CheckResult(
                    "sync:pending-merges",
                    "warn",
                    f"{len(pending)} unresolved merge package(s) in review/needs-merge/ "
                    "— run !merge in the AI chat",
                    details=[p.name for p in pending[:10]],
                )
            )
        else:
            results.append(CheckResult("sync:pending-merges", "ok"))

    inbox = kbc.sync_dir(root, "inbox")
    if inbox.is_dir():
        waiting = list(inbox.glob("*.zip"))
        if waiting:
            results.append(
                CheckResult(
                    "sync:inbox",
                    "warn",
                    f"{len(waiting)} bundle(s) waiting in sync/inbox/ — run scripts/kb_import.py",
                    details=[p.name for p in waiting[:10]],
                )
            )
    return results


def check_heal(root: Path) -> list[CheckResult]:
    """Warn when upgrade moved the version but heal did not run, or a stage stalled."""
    results: list[CheckResult] = []
    cfg = kbc.load_config(root)
    heal = (cfg.raw.get("heal") or {}) if cfg.raw else {}
    last = heal.get("last_run") or {}
    if isinstance(last, str):
        last = {"at": last, "version": ""}
    last_ver = str(last.get("version") or "").strip().strip('"')
    current = str(cfg.instructions_version or "").strip().strip('"')
    if last_ver and current and last_ver != current:
        results.append(
            CheckResult(
                "heal:after-upgrade",
                "warn",
                f"instructions_version is {current} but heal.last_run.version "
                f"is {last_ver} — say !heal (or re-run kb_upgrade without --no-heal)",
            )
        )
    else:
        results.append(
            CheckResult(
                "heal:after-upgrade",
                "ok",
                "heal last_run matches instructions_version"
                if last_ver
                else "heal last_run not set (fresh base or heal has not run)",
            )
        )

    try:
        stage = int(heal.get("stage") or 1)
    except (TypeError, ValueError):
        stage = 1
    last_at = last.get("at")
    parsed = None
    if last_at:
        try:
            parsed = _dt.date.fromisoformat(str(last_at)[:10])
        except ValueError:
            parsed = None
    stuck = False
    if stage in (2, 3, 4) and parsed is not None:
        stuck = (_dt.date.today() - parsed).days > 14
    if stuck:
        results.append(
            CheckResult(
                "heal:stage-stuck",
                "warn",
                f"heal.stage is {stage} and last_run.at is {last_at} "
                "(older than 14 days) — resume !heal or close the stage",
            )
        )
    else:
        results.append(
            CheckResult("heal:stage-stuck", "ok", f"heal.stage={stage}")
        )
    return results


def check_repomix_config(root: Path) -> CheckResult:
    p = root / "repomix.config.json"
    if not p.is_file():
        return CheckResult(
            "repomix:config",
            "warn",
            "repomix.config.json not found (run kb_doctor after deploying)",
        )
    try:
        kbc.read_json(p)
    except Exception as e:  # noqa: BLE001
        return CheckResult("repomix:config", "error", f"invalid JSON: {e}")
    return CheckResult("repomix:config", "ok")


def _config_or_defaults(root: Path) -> kbc.KbConfig:
    try:
        return kbc.load_config(root)
    except Exception:  # noqa: BLE001 — check_config reports the parse error
        return kbc.KbConfig(raw={}, root=root)


def check_repomix(root: Path) -> CheckResult:
    """kb_reindex needs `repomix`, or `npx` + `node` for the pinned fallback."""
    cfg = _config_or_defaults(root)
    # getattr: a pre-0.16 kb_common.py (partial upgrade) has no typed keys.
    index = cfg.index if isinstance(cfg.index, dict) else {}
    version = getattr(cfg, "index_repomix_version", None) or index.get(
        "repomix_version", "1.14.0"
    )
    npx_fallback = getattr(cfg, "index_npx_fallback", index.get("npx_fallback", True))
    repomix = shutil.which("repomix")
    if repomix:
        return CheckResult("index:repomix", "ok", f"repomix at {repomix}")
    npx, node = shutil.which("npx"), shutil.which("node")
    if npx and node and npx_fallback:
        return CheckResult(
            "index:repomix", "ok",
            f"repomix not installed; kb_reindex uses `npx --yes repomix@{version}` "
            "(the first run downloads it)",
        )
    if npx and node:
        reason = "the npx fallback is off (index.npx_fallback: false)"
    else:
        reason = "neither npx nor node is on PATH"
    install = f"npm install -g repomix@{version}"
    if not node:
        install = f"Node.js 18+ (https://nodejs.org), then {install}"
    return CheckResult(
        "index:repomix", "error",
        f"repomix not found and {reason} — kb_reindex cannot build the index "
        f"packs. Install: {install}",
    )


_PACK_CEILING_RE = re.compile(r"Pack ceiling:\s*(\d[\d,]*)")
_PACK_TOKENS_RE = re.compile(r"~?\s*(\d[\d,]*)")
_INDEX_NOT_BUILT_RE = re.compile(r"^\*\*Index not built:\*\*\s*(.*)$", re.M)


def _pack_columns(cells: list[str]) -> dict[str, int | None] | None:
    """Column positions from a PACKS_STATUS.md header row, else ``None``."""
    heads = [c.casefold() for c in cells]
    if not heads or heads[0] != "pack":
        return None

    def find(word: str) -> int | None:
        return next((i for i, h in enumerate(heads) if word in h), None)

    cols = {"tokens": find("token"), "ceiling": find("ceiling"), "build": find("last build")}
    return cols if cols["tokens"] is not None and cols["build"] is not None else None


def _pack_rows(text: str) -> list[tuple[str, int, bool, str]]:
    """``(name, tokens, marked OVER, last-build cell)`` for every pack row of
    PACKS_STATUS.md. Columns are found by the header row: kb_reindex writes
    ``| Pack | ~Tokens | Last build | Load when |`` (the token cell ends in
    ``⚠ OVER`` for a pack over the ceiling); a separate ``Ceiling`` column
    holding ``⚠ OVER`` is read too."""
    rows: list[tuple[str, int, bool, str]] = []
    cols: dict[str, int | None] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
        header = _pack_columns(cells)
        if header is not None:
            cols = header
            continue
        if cols is None or len(cells) <= max(i for i in cols.values() if i is not None):
            continue
        tokens = _PACK_TOKENS_RE.match(cells[cols["tokens"]])
        if not tokens:
            continue  # the |---|---| separator
        marks = cells[cols["tokens"]]
        if cols["ceiling"] is not None:
            marks += " " + cells[cols["ceiling"]]
        rows.append((
            cells[0], int(tokens.group(1).replace(",", "")),
            "OVER" in marks, cells[cols["build"]],
        ))
    return rows


def check_packs_status(root: Path) -> CheckResult:
    """The last reindex as recorded in .repomix/PACKS_STATUS.md."""
    status = root / ".repomix" / "PACKS_STATUS.md"
    if not status.is_file():
        return CheckResult(
            "index:packs", "warn",
            "no .repomix/PACKS_STATUS.md — the index has not been built yet; "
            "run ./shell/reindex.sh (or python3 scripts/kb_reindex.py)",
        )
    text = status.read_text(encoding="utf-8", errors="replace")
    not_built_at_all = _INDEX_NOT_BUILT_RE.search(text)
    if not_built_at_all:
        return CheckResult(
            "index:packs", "error",
            f"the last reindex built no index: {not_built_at_all.group(1).strip()} "
            "— fix it, then re-run ./shell/reindex.sh",
        )
    ceiling_match = _PACK_CEILING_RE.search(text)
    ceiling = int(ceiling_match.group(1).replace(",", "")) if ceiling_match else None
    rows = _pack_rows(text)
    if not rows:
        return CheckResult(
            "index:packs", "warn",
            "no pack rows could be read from .repomix/PACKS_STATUS.md — re-run "
            "./shell/reindex.sh",
        )
    failed = [name for name, _t, _o, built in rows if re.search(r"\bFAILED\b", built)]
    not_built = [name for name, _t, _o, built in rows if re.search(r"\bSTALE\b", built)]
    over = [
        f"{name} (~{tokens:,} tokens)"
        for name, tokens, marked, _b in rows
        if marked or (ceiling and tokens > ceiling)
    ]
    if failed:
        return CheckResult(
            "index:packs", "error",
            f"{len(failed)} pack(s) FAILED in the last reindex — the agent cannot "
            "load them; re-run ./shell/reindex.sh and read its output",
            details=failed,
        )
    warnings: list[str] = []
    if not_built:
        warnings.append(
            f"{len(not_built)} pack(s) not rebuilt in the last reindex (repomix "
            "unavailable, see index:repomix)"
        )
    knowledge = root / "knowledge"
    newest = 0.0
    if knowledge.is_dir():
        newest = max(
            (p.stat().st_mtime for p in knowledge.rglob("*.md") if p.is_file()),
            default=0.0,
        )
    if newest > status.stat().st_mtime + 1:
        warnings.append(
            "knowledge/ changed after the last reindex — the packs are stale; "
            "run ./shell/reindex.sh"
        )
    if over:
        warnings.append(
            f"{len(over)} pack(s) over the ceiling — split them (see kb-docs/05_INDEX.md)"
        )
    left_out = [line for line in text.splitlines() if line.startswith("Left out by repomix")]
    if left_out:
        warnings.append(
            "repomix left files out of a pack (security check or an ignore file) — "
            "python3 scripts/kb_lint.py names credential-looking lines"
        )
    if warnings:
        return CheckResult(
            "index:packs", "warn", "; ".join(warnings), details=over + not_built + left_out
        )
    return CheckResult("index:packs", "ok", f"{len(rows)} pack(s) built, none failed")


_SIDECAR_DIRS = ("scripts", "shell", "templates", KB_DOCS_DIR)


def check_sidecars(root: Path) -> CheckResult:
    """`.new` files kb_upgrade left for the agent to merge."""
    found = [p for p in root.glob("*.new") if p.is_file()]
    for name in _SIDECAR_DIRS:
        folder = root / name
        if folder.is_dir():
            found.extend(
                p for p in folder.rglob("*.new")
                if p.is_file() and "__pycache__" not in p.parts
            )
    if not found:
        return CheckResult("upgrade:sidecars", "ok", "no unmerged .new sidecars")
    return CheckResult(
        "upgrade:sidecars", "warn",
        f"{len(found)} unmerged upgrade sidecar(s) — say !heal: the agent merges "
        "each into the live file, then deletes the .new",
        details=sorted(p.relative_to(root).as_posix() for p in found),
    )


_UPGRADE_HINT = "the engine repo's scripts/kb_upgrade.py --kb-root <this base>"

# Runs in a child interpreter so the base's own scripts/ are imported, not the
# modules this doctor process already holds.
_SCRIPTS_PROBE = r"""
import importlib, json, re, sys
from pathlib import Path
scripts = Path(sys.argv[1])
sys.path.insert(0, str(scripts))
out = {"broken": {}, "optional": {}, "missing": {}}
try:
    import kb_common
    names = set(dir(kb_common))
except Exception as exc:
    out["broken"]["kb_common"] = f"{type(exc).__name__}: {exc}"
    names = None
for path in sorted(scripts.glob("kb_*.py")):
    mod = path.stem
    if mod != "kb_common":
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as exc:
            top = (exc.name or "").split(".")[0]
            ours = top.startswith("kb_") or (scripts / (top + ".py")).exists()
            if top and not ours:
                out["optional"][mod] = top
            else:
                out["broken"][mod] = f"{type(exc).__name__}: {exc}"
        except BaseException as exc:
            out["broken"][mod] = f"{type(exc).__name__}: {exc}"
    if names is not None:
        text = path.read_text(encoding="utf-8", errors="replace")
        used = set(re.findall(r"\bkbc\.([A-Za-z_]\w*)", text))
        if used - names:
            out["missing"][mod] = sorted(used - names)
print(json.dumps(out))
"""


def check_scripts(root: Path) -> CheckResult:
    """Every scripts/kb_*.py imports and finds the kb_common names it uses.

    A customized kb_common.py kept by an upgrade (`kb_common.py.new` beside it)
    next to updated scripts fails here instead of at the first real run.
    """
    scripts = root / "scripts"
    if not scripts.is_dir():
        return CheckResult(
            "scripts:consistency", "warn", f"no scripts/ in {root} — nothing to check"
        )
    if not (scripts / "kb_common.py").is_file():
        return CheckResult(
            "scripts:consistency", "error", "scripts/kb_common.py is missing"
        )
    try:
        proc = subprocess.run(
            [sys.executable, "-B", "-c", _SCRIPTS_PROBE, str(scripts.resolve())],
            cwd=root, capture_output=True, text=True, timeout=120,
        )
        probe = json.loads(proc.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        return CheckResult(
            "scripts:consistency", "warn", f"could not probe scripts/: {e}"
        )
    problems = [
        f"scripts/{mod}.py does not import: {why}"
        for mod, why in sorted(probe["broken"].items())
    ] + [
        f"scripts/{mod}.py uses kb_common.{', kb_common.'.join(names)} "
        "— not in scripts/kb_common.py"
        for mod, names in sorted(probe["missing"].items())
    ]
    if problems:
        return CheckResult(
            "scripts:consistency", "error",
            "engine scripts do not match each other (a partial upgrade?) — merge "
            f"any scripts/*.py.new, or re-run {_UPGRADE_HINT} (add "
            "`--accept kb_common.py` to take the engine's kb_common.py over a kept "
            "local copy)",
            details=problems,
        )
    optional = sorted(set(probe["optional"].values()))
    note = f" (optional modules not installed: {', '.join(optional)})" if optional else ""
    return CheckResult("scripts:consistency", "ok", f"all scripts/kb_*.py import{note}")


_KB_DOCS_REF_RE = re.compile(r"kb-docs/((?:\d\d_[A-Za-z0-9_]+|README)\.md)")
_KB_DOCS_READERS = ("AGENTS.md", "CLAUDE.md", "START_HERE.md", "KNOWLEDGE_STRUCTURE.md")


def check_kb_docs(root: Path) -> CheckResult:
    """kb-docs/ holds the runtime modules the agent's files point to."""
    docs = root / KB_DOCS_DIR
    wanted: dict[str, str] = {}
    for name in _KB_DOCS_READERS:
        reader = root / name
        if reader.is_file():
            text = reader.read_text(encoding="utf-8", errors="replace")
            for ref in _KB_DOCS_REF_RE.findall(text):
                wanted.setdefault(ref, name)
    missing = sorted(ref for ref in wanted if not (docs / ref).is_file())
    if missing:
        return CheckResult(
            "kb-docs", "error",
            f"{len(missing)} runtime module(s) the agent files point to are missing "
            f"from kb-docs/ — run {_UPGRADE_HINT} (or copy them from the "
            "engine's knowledge-base/)",
            details=[f"kb-docs/{ref} (referenced by {wanted[ref]})" for ref in missing],
        )
    if not docs.is_dir():
        return CheckResult(
            "kb-docs", "warn",
            "no kb-docs/ — the runtime modules (!heal, !merge, !refactor "
            f"procedures) are not in this base; run {_UPGRADE_HINT}",
        )
    count = sum(1 for p in docs.glob("*.md") if p.is_file())
    return CheckResult("kb-docs", "ok", f"kb-docs/: {count} module(s)")


def _base_venv(root: Path) -> Path | None:
    """The venv the shell wrappers use (same rule as shell/_kbpy.sh)."""
    own = root / ".venv"
    if own.is_dir():
        return own
    project = root.parent / ".venv"
    if (root.parent / "setup" / "scripts" / "kb_common.py").is_file() and project.is_dir():
        return project  # deploy layout, before finalize.sh
    return None


_VIRTUAL_ENV_RE = re.compile(
    r"""^\s*(?:export\s+)?VIRTUAL_ENV=(["']?)([^"'\n]+)\1\s*$""", re.MULTILINE
)
_SHEBANG_PYTHON_RE = re.compile(r"(/\S*python[\d.]*)\b")


def check_venv(root: Path) -> list[CheckResult]:
    """The base venv is where the wrappers expect it and still works."""
    venv = _base_venv(root)
    if venv is None:
        # The wrappers, launchers and git hook fall back to python3: without
        # a base venv the optional packages (NLP, media) silently go unused.
        create = (
            "create .venv at the base root and install the requirements there "
            "(kb-docs/01_PREREQUISITES.md)"
        )
        stranded = root / "knowledge-base" / ".venv"
        running = Path(sys.prefix).resolve()
        if (stranded / "pyvenv.cfg").is_file():
            return [
                CheckResult(
                    "venv:stranded", "warn",
                    "knowledge-base/.venv is left from the build folder; the shell "
                    "wrappers, launchers and git hook never use it — they run "
                    f"python3; {create}, then delete knowledge-base/.venv",
                )
            ]
        if sys.prefix != sys.base_prefix and not running.is_relative_to(root.resolve()):
            return [
                CheckResult(
                    "venv:stranded", "warn",
                    f"doctor runs in the venv {running}, which the shell wrappers, "
                    f"launchers and git hook never use — they run python3; {create}",
                )
            ]
        return [
            CheckResult(
                "venv:missing", "warn",
                "no .venv for this base — the shell wrappers, launchers and git hook "
                f"run python3 ({shutil.which('python3') or 'not on PATH'}); {create}",
            )
        ]
    results: list[CheckResult] = []
    rel = ".venv" if venv.parent == root else "../.venv"
    recreate = (
        f"python3 -m venv --clear {rel} && {rel}/bin/pip install -r requirements.txt"
    )
    if (venv / ".venv").is_dir():
        results.append(
            CheckResult(
                "venv:nested", "warn",
                f"{rel}/.venv exists — a venv was moved inside another one "
                f"(finalize.sh without --force). The wrappers use the outer {rel}: "
                f"install the requirements there, then delete {rel}/.venv "
                "(kb-docs/01_PREREQUISITES.md)",
            )
        )
    bindir = venv / ("Scripts" if os.name == "nt" else "bin")
    activate = bindir / "activate"
    if activate.is_file():
        text = activate.read_text(encoding="utf-8", errors="replace")
        # Skip shell expansions such as the Cygwin branch's $(cygpath …).
        created_at = next(
            (m.group(2) for m in _VIRTUAL_ENV_RE.finditer(text) if "$" not in m.group(2)),
            None,
        )
        if created_at and Path(created_at).resolve() != venv.resolve():
            results.append(
                CheckResult(
                    "venv:moved", "warn",
                    f"{rel} was created at {created_at} and moved — `activate` "
                    f"still points there. Recreate it in place: {recreate}",
                )
            )
    pip = bindir / "pip"
    if os.name != "nt" and pip.is_file():
        head = pip.read_text(encoding="utf-8", errors="replace")[:600]
        target = _SHEBANG_PYTHON_RE.search(head)
        if target and not Path(target.group(1)).exists():
            results.append(
                CheckResult(
                    "venv:pip", "warn",
                    f"{rel}/bin/pip runs {target.group(1)}, which does not exist "
                    f"(the venv was moved) — pip is broken until you recreate it: {recreate}",
                )
            )
    if Path(sys.prefix).resolve() != venv.resolve():
        results.append(
            CheckResult(
                "venv:active", "warn",
                f"doctor runs on {sys.executable}, not the base venv {rel} — the "
                "package checks above describe that interpreter. Use "
                f"./shell/doctor.sh or {rel}/bin/python scripts/kb_doctor.py",
            )
        )
    if not results:
        results.append(CheckResult("venv", "ok", f"{rel} is in place and in use"))
    return results


def check_nltk_data() -> CheckResult | None:
    """RAKE (rake-nltk) needs the NLTK stopwords and punkt data; without them
    keyword extraction silently returns nothing. None when RAKE is absent."""
    try:
        importlib.import_module("rake_nltk")
    except ImportError:
        return None
    try:
        corpus = importlib.import_module("nltk.corpus")
        tokenize = importlib.import_module("nltk.tokenize")
        corpus.stopwords.words("english")
        tokenize.sent_tokenize("One. Two.")
    except LookupError:
        return CheckResult(
            "nlp:nltk-data", "warn",
            "rake-nltk is installed but NLTK data is missing — keywords come out "
            "empty. Run: python3 -m nltk.downloader stopwords punkt punkt_tab",
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult("nlp:nltk-data", "warn", f"could not probe NLTK data: {e}")
    return CheckResult("nlp:nltk-data", "ok", "NLTK stopwords and punkt available")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _guarded(
    name: str, fn: Callable[[], CheckResult | list[CheckResult] | None]
) -> list[CheckResult]:
    """One crashing check becomes one error result, not a dead doctor."""
    try:
        result = fn()
    except Exception as e:  # noqa: BLE001
        return [CheckResult(name, "error", f"check crashed: {type(e).__name__}: {e}")]
    if result is None:
        return []
    return result if isinstance(result, list) else [result]


def run_all_checks(
    root: Path,
    *,
    skip_nlp: bool = False,
    ephemeral_log: bool = False,
    self_test: bool = False,
) -> list[CheckResult]:
    """All default checks. `ephemeral_log` is accepted for callers written
    before 0.16 and ignored: doctor no longer writes log.md at all."""
    del ephemeral_log
    results: list[CheckResult] = []
    results.append(check_python_version())
    results.extend(check_required_packages())
    results.extend(check_optional_packages())
    results.extend(check_structure(root))
    results.extend(_guarded("config", lambda: check_config(root, self_test=self_test)))

    # Source-repo self-test is not a deployed base; skip the deployment checks
    # (Codex environment, index, kb-docs, venv, heal) so a missing root
    # AGENTS.md or index does not fail the smoke test.
    if not self_test:
        results.extend(_guarded("agent-env", lambda: check_agent_env(root)))

    if not skip_nlp:
        try:
            cfg = kbc.load_config(root)
            results.append(check_spacy(cfg.spacy_model, cfg.spacy_model_fallback))
        except Exception as e:  # noqa: BLE001
            results.append(
                CheckResult("nlp:spacy", "warn", f"could not test spaCy (config error): {e}")
            )
        results.extend(_guarded("nlp:nltk-data", check_nltk_data))

    results.extend(_guarded("frontmatter", check_frontmatter_roundtrip))
    results.extend(_guarded("media", lambda: check_media(root)))
    results.extend(_guarded("sync", lambda: check_sync(root)))
    results.extend(_guarded("repomix:config", lambda: check_repomix_config(root)))
    results.extend(_guarded("scripts:consistency", lambda: check_scripts(root)))
    results.extend(_guarded("upgrade:sidecars", lambda: check_sidecars(root)))
    results.extend(_guarded("log:writable", lambda: check_log_writable(root)))
    if not self_test:
        results.extend(_guarded("index:repomix", lambda: check_repomix(root)))
        results.extend(_guarded("index:packs", lambda: check_packs_status(root)))
        results.extend(_guarded("kb-docs", lambda: check_kb_docs(root)))
        results.extend(_guarded("venv", lambda: check_venv(root)))
        results.extend(_guarded("heal", lambda: check_heal(root)))
    return results


def check_mutations(root: Path) -> CheckResult:
    try:
        import kb_mutate
    except ImportError:
        return CheckResult("mutate:l1", "warn", "kb_mutate.py is not importable")
    report = kb_mutate.run_mutations(root)
    if report.survivors:
        return CheckResult(
            "mutate:l1",
            "error",
            f"{report.line} — survivors: {', '.join(report.survivors)}",
        )
    return CheckResult("mutate:l1", "ok", report.line)


def render_text(results: list[CheckResult]) -> str:
    icon = {"ok": "✅", "warn": "⚠️ ", "error": "❌"}
    lines = ["kb_doctor — health check", "=" * 30]
    for r in results:
        lines.append(f"{icon.get(r.severity, '?')} {r.name}: {r.message}")
        for d in r.details:
            lines.append(f"    {d}")
    counts = {"ok": 0, "warn": 0, "error": 0}
    for r in results:
        counts[r.severity] = counts.get(r.severity, 0) + 1
    lines.append("")
    verdict = (
        "FAIL (exit 2): fix the errors above" if counts["error"]
        else "PASS (exit 0; warnings are advice)"
    )
    lines.append(
        f"Summary: {counts['ok']} ok, {counts['warn']} warn, {counts['error']} error "
        f"— {verdict}"
    )
    return "\n".join(lines)


def exit_code(results: list[CheckResult]) -> int:
    """0 = doctor passes (warnings allowed), 2 = at least one error."""
    return 2 if any(r.severity == "error" for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — post-deploy smoke-test")
    parser.add_argument("--root", type=Path, default=None, help="KB root (default: auto-detect)")
    parser.add_argument("--self-test", action="store_true", help="Run on this script's own repo")
    parser.add_argument(
        "--skip-nlp", action="store_true", help="Skip the spaCy model and NLTK data checks"
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument(
        "--with-mutation",
        action="store_true",
        help="also run kb_mutate.py (seven L1 defects; slower; not default)",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        # Run from the parent of this script's directory (the knowledge-base/ folder)
        root = SCRIPT_DIR.parent
    else:
        root = args.root or kbc.find_kb_root()

    results = run_all_checks(root, skip_nlp=args.skip_nlp, self_test=args.self_test)
    if args.with_mutation and not args.self_test:
        results.append(check_mutations(root))

    code = exit_code(results)

    if args.json:
        print(
            json.dumps(
                {
                    "root": str(root),
                    "results": [asdict(r) for r in results],
                    "exit_code": code,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_text(results))

    return code


if __name__ == "__main__":
    try:
        code = main()
    except Exception:  # noqa: BLE001 — a crash is a failed doctor (2), not 1
        traceback.print_exc()
        code = 2
    raise SystemExit(code)
