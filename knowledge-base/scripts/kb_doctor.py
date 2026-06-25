#!/usr/bin/env python3
"""kb_doctor — post-deployment smoke-test for AI Knowledge Engine.

Verifies that:
  1. Required Python packages are importable
  2. Mandatory directory structure exists
  3. kb.config.yml is parseable and has the expected shape
  4. (Optional) spaCy model loads
  5. Frontmatter helpers work on a sample fixture
  6. Filesystem is writable (log.md append works)

Exit codes:
  0 — all checks passed (or only soft warnings)
  1 — one or more soft checks failed (warnings)
  2 — at least one critical check failed (errors)

Usage:
  python3 scripts/kb_doctor.py
  python3 scripts/kb_doctor.py --self-test       # run on this script's own repo
  python3 scripts/kb_doctor.py --skip-nlp        # don't try to load spaCy
  python3 scripts/kb_doctor.py --json            # machine-readable output
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# kb_common is a sibling module
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402


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
                    f"Optional package missing: {package_name} (some features will be unavailable)",
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


def check_log_writable(root: Path, *, ephemeral: bool = False) -> CheckResult:
    """Verify that log.md can be appended to.

    When `ephemeral=True` (used by --self-test), uses a temporary directory so
    the source repo is not polluted with a log.md.
    """
    if ephemeral:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="kb_doctor_") as tmp:
            try:
                kbc.append_log(
                    operation="doctor",
                    title="kb_doctor self-test (ephemeral)",
                    details=["log writability verified in temporary directory"],
                    root=Path(tmp),
                )
                return CheckResult("log:writable", "ok", "ephemeral write succeeded")
            except Exception as e:  # noqa: BLE001
                return CheckResult("log:writable", "error", f"cannot write log.md: {e}")
    try:
        kbc.append_log(
            operation="doctor",
            title="kb_doctor smoke-test",
            details=["if you see this, log.md is writable"],
            root=root,
        )
        return CheckResult("log:writable", "ok", f"appended to {kbc.log_path(root)}")
    except Exception as e:  # noqa: BLE001
        return CheckResult("log:writable", "error", f"cannot write to log.md: {e}")


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
            results.append(
                CheckResult("media:ocr", "ok", f"available: {', '.join(ocr_usable)}")
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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_all_checks(
    root: Path,
    *,
    skip_nlp: bool = False,
    ephemeral_log: bool = False,
    self_test: bool = False,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(check_python_version())
    results.extend(check_required_packages())
    results.extend(check_optional_packages())
    results.extend(check_structure(root))

    cfg_res = check_config(root, self_test=self_test)
    results.append(cfg_res)

    if not skip_nlp:
        try:
            cfg = kbc.load_config(root)
            results.append(check_spacy(cfg.spacy_model, cfg.spacy_model_fallback))
        except Exception as e:  # noqa: BLE001
            results.append(
                CheckResult("nlp:spacy", "warn", f"could not test spaCy (config error): {e}")
            )

    results.append(check_frontmatter_roundtrip())
    results.extend(check_media(root))
    results.append(check_repomix_config(root))
    results.append(check_log_writable(root, ephemeral=ephemeral_log))
    return results


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
    lines.append(
        f"Summary: {counts['ok']} ok, {counts['warn']} warn, {counts['error']} error"
    )
    return "\n".join(lines)


def exit_code(results: list[CheckResult], *, warnings_ok: bool = False) -> int:
    if any(r.severity == "error" for r in results):
        return 2
    if not warnings_ok and any(r.severity == "warn" for r in results):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — post-deploy smoke-test")
    parser.add_argument("--root", type=Path, default=None, help="KB root (default: auto-detect)")
    parser.add_argument("--self-test", action="store_true", help="Run on this script's own repo")
    parser.add_argument("--skip-nlp", action="store_true", help="Skip spaCy model check")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args(argv)

    if args.self_test:
        # Run from the parent of this script's directory (the knowledge-base/ folder)
        root = SCRIPT_DIR.parent
        ephemeral_log = True
    else:
        root = args.root or kbc.find_kb_root()
        ephemeral_log = False

    results = run_all_checks(
        root,
        skip_nlp=args.skip_nlp,
        ephemeral_log=ephemeral_log,
        self_test=args.self_test,
    )

    # In --self-test we validate that the scripts are wired and importable;
    # warnings about optional deps / missing deployed config are expected and
    # must not fail the run (e.g. in CI with only core deps installed).
    code = exit_code(results, warnings_ok=args.self_test)

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
    raise SystemExit(main())
