#!/usr/bin/env python3
"""kb_ocr — optical character recognition for AI Knowledge Engine.

Cross-platform OCR for scanned images, screenshots, and photos of text.

The **default backend is RapidOCR** (``rapidocr-onnxruntime``), which ships its
own ONNX models and runtime — **no system dependencies** on macOS, Windows, or
Linux. The alternative is Tesseract via ``pytesseract``, which requires the
system ``tesseract`` binary on PATH.

Backends are tried in the order configured in ``kb.config.yml`` →
``media.ocr.backends`` (default: rapidocr, then tesseract):

  1. ``rapidocr``  — pip-only, no system deps (recommended, all platforms)
  2. ``tesseract`` — requires a system ``tesseract`` binary + ``pytesseract``

``media.ocr.language`` ("ru", "ru+en", ["ru", "en"]; "auto" = the base's
primary language plus English) goes to Tesseract as its language codes, limited
to the language data Tesseract has installed (``tesseract --list-langs``).
RapidOCR's bundled model reads only Chinese and English and takes no language
setting, so for any other language Tesseract is tried first when it has that
language's data. A result that may be garbled (RapidOCR on such text, or
Tesseract without the data) carries a warning line.

If no backend is available, :func:`ocr_image` raises :class:`OcrUnavailable`
with an OS-specific install hint. When the installed backends fail, the message
names each backend's error and says whether a backend could not start (a setup
problem) or started and could not read the file (the file is the likely cause).
The ingest pipeline routes the file to ``review/needs-ai-decision/`` with that
message inlined. The RapidOCR engine loads once per process.

Usage (standalone):
  python3 scripts/kb_ocr.py path/to/scan.png
  python3 scripts/kb_ocr.py --check
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}

DEFAULT_BACKENDS = ("rapidocr", "tesseract")

# What the bundled RapidOCR (PP-OCR Chinese) model reads: Chinese and Latin letters.
RAPIDOCR_LANGUAGES = {"zh", "ch", "chi_sim", "en", "eng"}

# ISO 639-1 → Tesseract language data; other values (already Tesseract names
# such as "rus" or "chi_tra") pass through unchanged.
TESSERACT_LANGUAGES = {
    "be": "bel", "cs": "ces", "de": "deu", "en": "eng", "es": "spa", "fr": "fra",
    "it": "ita", "ja": "jpn", "kk": "kaz", "ko": "kor", "nl": "nld", "pl": "pol",
    "pt": "por", "ru": "rus", "uk": "ukr", "zh": "chi_sim",
}


class OcrUnavailable(RuntimeError):
    """Raised when OCR cannot be performed (no usable backend, or every usable
    backend failed on the file)."""


class _StartFailed(Exception):
    """A backend could not start (engine load, runtime, binary, language
    data); the file itself was not read."""

    def __init__(self, error: Exception):
        super().__init__(f"{type(error).__name__}: {error}")
        self.error = error


@dataclass
class OcrResult:
    text: str
    markdown: str
    backend: str = ""
    lines: int = 0
    warning: str = ""


def ocr_enabled(cfg: kbc.KbConfig | None) -> bool:
    if cfg is None:
        return True
    return bool(cfg.ocr.get("enabled", True))


def _configured_backends(cfg: kbc.KbConfig | None) -> list[str]:
    if cfg is None:
        return list(DEFAULT_BACKENDS)
    backends = cfg.ocr.get("backends") or list(DEFAULT_BACKENDS)
    return [str(b).lower() for b in backends]


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def available_backends(cfg: kbc.KbConfig | None = None) -> list[str]:
    usable: list[str] = []
    for backend in _configured_backends(cfg):
        if backend == "rapidocr" and _module_available("rapidocr_onnxruntime"):
            usable.append(backend)
        elif backend == "tesseract" and _module_available("pytesseract"):
            if shutil.which("tesseract"):
                usable.append(backend)
    return usable


def _language_code(value: object) -> str:
    """"ru-RU" / "ru_RU" / "RU" → "ru"; Tesseract names ("chi_sim",
    "script/Cyrillic") pass through unchanged."""
    code = str(value).strip()
    match = re.fullmatch(r"([A-Za-z]{2,3})(?:-[A-Za-z0-9]+|_[A-Za-z]{2})?", code)
    return match.group(1).lower() if match else code


def ocr_languages(
    cfg: kbc.KbConfig | None, language: str | list[str] | None = None
) -> list[str]:
    """Languages to read: ``language`` or ``media.ocr.language`` ("ru", "ru+en",
    a YAML list); "auto" = the base's primary language plus English."""
    if language is None:
        language = (cfg.ocr if cfg else {}).get("language") or "auto"
    values = language if isinstance(language, (list, tuple)) else re.split(r"[+,\s]+", str(language))
    codes = [_language_code(v) for v in values if str(v).strip()]
    if codes and [c.lower() for c in codes] != ["auto"]:
        return list(dict.fromkeys(codes))
    primary = _language_code((cfg.primary_language if cfg else "") or "en") or "en"
    return [primary] if primary == "en" else [primary, "en"]


def _unread_by_rapidocr(languages: list[str]) -> list[str]:
    return [lang for lang in languages if lang not in RAPIDOCR_LANGUAGES]


def _tesseract_names(languages: list[str]) -> list[str]:
    return list(dict.fromkeys(TESSERACT_LANGUAGES.get(c, c) for c in languages))


def tesseract_installed_languages() -> set[str] | None:
    """Language data Tesseract has (``tesseract --list-langs``); ``None`` when
    it cannot be listed (no binary, pytesseract < 0.3.8)."""
    try:
        import pytesseract  # type: ignore[import-untyped]

        return set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 — unknown, not an error
        return None


def _tesseract_plan(
    languages: list[str], installed: set[str] | None
) -> tuple[str | None, list[str]]:
    """Tesseract's ``lang`` for ``languages`` and the names it has no data for.

    Only installed data is requested (a missing one makes Tesseract fail on
    every image); ``None`` = Tesseract's default (English) when it has none.
    """
    wanted = _tesseract_names(languages)
    if installed is None:
        return "+".join(wanted), []
    have = [name for name in wanted if name in installed]
    return "+".join(have) or None, [name for name in wanted if name not in installed]


def _tesseract_reads(languages: list[str], installed: set[str] | None) -> bool:
    """Tesseract has data for any of ``languages`` (``None`` = unknown: assume so)."""
    return installed is None or bool(set(_tesseract_names(languages)) & installed)


def tesseract_data_hint(missing: list[str]) -> str:
    """Per-OS command that installs Tesseract language data."""
    if sys.platform == "darwin":
        return "brew install tesseract-lang"
    if sys.platform == "win32":
        return (
            "re-run the Tesseract installer and tick " + ", ".join(missing)
            + " under 'Additional language data'"
        )
    packages = " ".join(f"tesseract-ocr-{name.replace('_', '-')}" for name in missing)
    return f"sudo apt install -y {packages} (Debian/Ubuntu)"


def install_hint() -> str:
    tesseract_hint = kbc.os_install_hint("tesseract")
    return (
        "No OCR backend available.\n"
        "Recommended (all platforms, NO system deps):\n"
        "    pip install rapidocr-onnxruntime\n"
        "\n"
        "Alternative (Tesseract) also needs a system binary:\n"
        f"    pip install pytesseract Pillow   &&   {tesseract_hint}"
    )


def _render_markdown(source_name: str, text: str, backend: str, warning: str = "") -> str:
    body = text.strip() or "_(no text detected)_"
    note = f"> ⚠️ {warning}\n\n" if warning else ""
    return (
        f"# OCR: {source_name}\n\n"
        f"> Extracted via `{backend}`. Machine-generated — verify before use.\n\n"
        f"{note}{body}\n"
    )


@functools.lru_cache(maxsize=1)
def _rapidocr_engine():
    from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-untyped]

    return RapidOCR()


def _ocr_rapidocr(src: Path, warning: str = "") -> OcrResult:
    try:
        engine = _rapidocr_engine()
    except ImportError:
        raise
    except Exception as e:  # noqa: BLE001 — models / onnxruntime session
        raise _StartFailed(e) from e
    result, _elapsed = engine(str(src))
    lines = [item[1] for item in (result or []) if len(item) > 1]
    text = "\n".join(lines)
    return OcrResult(
        text=text,
        markdown=_render_markdown(src.name, text, "rapidocr", warning),
        backend="rapidocr",
        lines=len(lines),
        warning=warning,
    )


def _missing_data_warning(missing: list[str]) -> str:
    return (
        f"Tesseract has no language data for {', '.join(missing)}; text in that "
        "language may be garbled. Install it (kb-docs/15_MEDIA_PROCESSING.md): "
        f"{tesseract_data_hint(missing)}."
    )


def _ocr_tesseract(
    src: Path, languages: list[str], installed: set[str] | None = None
) -> OcrResult:
    import pytesseract  # type: ignore[import-untyped]
    from PIL import Image  # type: ignore[import-untyped]

    lang, missing = _tesseract_plan(languages, installed)
    warning = _missing_data_warning(missing) if missing else ""
    try:
        with Image.open(src) as image:
            text = pytesseract.image_to_string(image, lang=lang)
    except Exception as e:
        # No binary or no language data: Tesseract never read the file.
        if type(e).__name__ == "TesseractNotFoundError" or "Failed loading language" in str(e):
            raise _StartFailed(e) from e
        raise
    line_count = len([ln for ln in text.splitlines() if ln.strip()])
    return OcrResult(
        text=text,
        markdown=_render_markdown(src.name, text, "tesseract", warning),
        backend="tesseract",
        lines=line_count,
        warning=warning,
    )


def _describe(error: Exception) -> str:
    error = error.error if isinstance(error, _StartFailed) else error
    return f"{type(error).__name__}: {error}"


def _failed_message(src: Path, errors: list[tuple[str, Exception]]) -> str:
    """Why OCR of ``src`` failed on every installed backend.

    A backend that cannot be imported is a broken install (→ install hint); one
    that could not start (engine load, runtime, binary, language data) is a
    setup problem — the file was not read. Only when a backend started and
    failed on the file is the file the likely cause.
    """
    details = "; ".join(f"{name}: {_describe(e)}" for name, e in errors)
    if all(isinstance(e, ImportError) for _, e in errors):
        return f"no OCR backend could be imported — {details}\n\n{install_hint()}"
    if all(isinstance(e, (_StartFailed, ImportError)) for _, e in errors):
        return (
            f"no OCR backend could start, so {src.name} was not read — {details}\n"
            "This is a setup problem, not the file: check the backend with "
            "`python3 scripts/kb_ocr.py --check` and `python3 scripts/kb_doctor.py` "
            "(RapidOCR needs a working onnxruntime; Tesseract needs its binary and "
            "the language data; both need free memory)."
        )
    return (
        f"every installed OCR backend failed on {src.name} — {details}\n"
        "A backend started and could not read this file, so the file is the likely "
        "cause (damaged, or not an image the backend can read). If other images fail "
        "the same way, the backend is the problem: run `python3 scripts/kb_doctor.py`."
    )


def ocr_image(
    src: Path | str,
    *,
    cfg: kbc.KbConfig | None = None,
    language: str | None = None,
) -> OcrResult:
    """OCR an image with the first available backend.

    Raises :class:`OcrUnavailable` if no backend can be used or every usable
    backend failed on the file.
    """
    src = Path(src)
    if not src.is_file():
        raise OcrUnavailable(f"file not found: {src}")

    languages = ocr_languages(cfg, language)
    unread = _unread_by_rapidocr(languages)
    rapidocr_warning = (
        f"RapidOCR's bundled model reads only Chinese and English; text in "
        f"{', '.join(unread)} may be garbled. Install Tesseract with that language "
        "data for a better result (kb-docs/15_MEDIA_PROCESSING.md)."
        if unread else ""
    )

    usable = available_backends(cfg)
    if not usable:
        raise OcrUnavailable(install_hint())
    installed = tesseract_installed_languages() if "tesseract" in usable else None
    if unread and _tesseract_reads(unread, installed):
        usable.sort(key=lambda backend: backend != "tesseract")

    errors: list[tuple[str, Exception]] = []
    for backend in usable:
        try:
            if backend == "rapidocr":
                return _ocr_rapidocr(src, rapidocr_warning)
            if backend == "tesseract":
                return _ocr_tesseract(src, languages, installed)
        except OcrUnavailable:
            raise
        except Exception as e:  # noqa: BLE001 — try the next backend
            errors.append((backend, e))
    raise OcrUnavailable(_failed_message(src, errors))


def language_report(languages: list[str], usable: list[str]) -> list[str]:
    """What ``--check`` says about reading ``languages`` with ``usable``."""
    lines: list[str] = []
    installed = tesseract_installed_languages() if "tesseract" in usable else None
    wanted = _tesseract_names(languages)
    if installed is not None:
        missing = [name for name in wanted if name not in installed]
        lines.append(
            "Tesseract language data: " + (", ".join(sorted(installed)) or "(none)")
            + (f" — missing {', '.join(missing)}: {tesseract_data_hint(missing)}" if missing else "")
        )
    unread = _unread_by_rapidocr(languages)
    if unread:
        readable = "tesseract" in usable and _tesseract_reads(unread, installed)
        lines.append(
            f"RapidOCR's bundled model cannot read {', '.join(unread)}: "
            + ("Tesseract is tried first." if readable
               else "install Tesseract with that language's data (kb-docs/15_MEDIA_PROCESSING.md).")
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — OCR")
    parser.add_argument("path", nargs="?", type=Path, help="Image file to OCR")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--language", default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("-o", "--output", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        cfg = kbc.load_config(args.root) if args.root else kbc.load_config()
    except Exception:  # noqa: BLE001
        cfg = None

    if args.check:
        usable = available_backends(cfg)
        print("OCR backends configured:", ", ".join(_configured_backends(cfg)))
        print("OCR backends available: ", ", ".join(usable) if usable else "(none)")
        languages = ocr_languages(cfg, args.language)
        print(f"OCR languages: {'+'.join(languages)}")
        for line in language_report(languages, usable):
            print(f"  {line}")
        if not usable:
            print("\n" + install_hint())
            return 1
        return 0

    if not args.path:
        parser.error("path is required unless --check is used")

    try:
        result = ocr_image(args.path, cfg=cfg, language=args.language)
    except OcrUnavailable as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    if args.output:
        args.output.write_text(result.markdown, encoding="utf-8")
        print(f"✅ wrote {args.output} ({result.lines} lines, {result.backend})")
    else:
        sys.stdout.write(result.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
