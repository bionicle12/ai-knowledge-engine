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

If no backend is available, :func:`ocr_image` raises :class:`OcrUnavailable`
with an OS-specific install hint; the ingest pipeline routes the file to
``review/needs-ai-decision/`` with that hint inlined.

Usage (standalone):
  python3 scripts/kb_ocr.py path/to/scan.png
  python3 scripts/kb_ocr.py --check
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}

DEFAULT_BACKENDS = ("rapidocr", "tesseract")


class OcrUnavailable(RuntimeError):
    """Raised when OCR cannot be performed (no usable backend)."""


@dataclass
class OcrResult:
    text: str
    markdown: str
    backend: str = ""
    lines: int = 0


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
            import shutil

            if shutil.which("tesseract"):
                usable.append(backend)
    return usable


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


def _render_markdown(source_name: str, text: str, backend: str) -> str:
    body = text.strip() or "_(no text detected)_"
    return (
        f"# OCR: {source_name}\n\n"
        f"> Extracted via `{backend}`. Machine-generated — verify before use.\n\n"
        f"{body}\n"
    )


def _ocr_rapidocr(src: Path) -> OcrResult:
    from rapidocr_onnxruntime import RapidOCR  # type: ignore[import-untyped]

    engine = RapidOCR()
    result, _elapsed = engine(str(src))
    lines = [item[1] for item in (result or []) if len(item) > 1]
    text = "\n".join(lines)
    return OcrResult(
        text=text,
        markdown=_render_markdown(src.name, text, "rapidocr"),
        backend="rapidocr",
        lines=len(lines),
    )


def _ocr_tesseract(src: Path, language: str | None) -> OcrResult:
    import pytesseract  # type: ignore[import-untyped]
    from PIL import Image  # type: ignore[import-untyped]

    lang = None if language in ("auto", "", None) else language
    text = pytesseract.image_to_string(Image.open(src), lang=lang)
    line_count = len([ln for ln in text.splitlines() if ln.strip()])
    return OcrResult(
        text=text,
        markdown=_render_markdown(src.name, text, "tesseract"),
        backend="tesseract",
        lines=line_count,
    )


def ocr_image(
    src: Path | str,
    *,
    cfg: kbc.KbConfig | None = None,
    language: str | None = None,
) -> OcrResult:
    """OCR an image with the first available backend.

    Raises :class:`OcrUnavailable` if no backend can be used.
    """
    src = Path(src)
    if not src.is_file():
        raise OcrUnavailable(f"file not found: {src}")

    ocr_cfg = cfg.ocr if cfg else {}
    language = language if language is not None else ocr_cfg.get("language", "auto")

    usable = available_backends(cfg)
    if not usable:
        raise OcrUnavailable(install_hint())

    last_error: Exception | None = None
    for backend in usable:
        try:
            if backend == "rapidocr":
                return _ocr_rapidocr(src)
            if backend == "tesseract":
                return _ocr_tesseract(src, language)
        except OcrUnavailable:
            raise
        except Exception as e:  # noqa: BLE001 — try the next backend
            last_error = e
            continue
    raise OcrUnavailable(
        f"all backends failed ({', '.join(usable)}): {last_error}\n\n{install_hint()}"
    )


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
