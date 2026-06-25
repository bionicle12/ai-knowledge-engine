#!/usr/bin/env python3
"""kb_stt — speech-to-text for AI Knowledge Engine.

Cross-platform, out-of-the-box transcription of audio and video.

The **default backend is faster-whisper**, which decodes audio via PyAV
(bundled FFmpeg libraries). This means **no system ffmpeg is required** on
macOS, Windows, or Linux — a plain ``pip install -r requirements-media.txt``
is enough. This deliberately avoids the most common failure on macOS, where
ffmpeg is installed via Homebrew into ``/opt/homebrew/bin`` but is invisible to
the PATH that an IDE hands to its child processes.

Backends are tried in the order configured in ``kb.config.yml`` →
``media.stt.backends`` (default: faster-whisper, then openai-whisper):

  1. ``faster-whisper`` — pip-only, no system deps (recommended, all platforms)
  2. ``openai-whisper`` — requires a system ``ffmpeg`` on PATH
  3. ``cloud``          — disabled unless ``media.stt.allow_cloud: true`` (privacy)

If no backend is available, :func:`transcribe` raises :class:`SttUnavailable`
with an OS-specific install hint; the ingest pipeline catches it and routes the
file to ``review/needs-ai-decision/`` with that hint inlined.

Usage (standalone):
  python3 scripts/kb_stt.py path/to/audio.mp3
  python3 scripts/kb_stt.py path/to/video.mp4 --model small --language ru
  python3 scripts/kb_stt.py --check          # report available backends
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import kb_common as kbc  # noqa: E402


AUDIO_EXTS = {
    ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".oga", ".aac", ".wma", ".opus",
}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg"}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS

DEFAULT_BACKENDS = ("faster-whisper", "openai-whisper")
DEFAULT_MODEL = "small"


class SttUnavailable(RuntimeError):
    """Raised when transcription cannot be performed (no usable backend)."""


@dataclass
class TranscriptResult:
    text: str
    markdown: str
    language: str = ""
    backend: str = ""
    model: str = ""
    duration: float = 0.0
    segments: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def stt_enabled(cfg: kbc.KbConfig | None) -> bool:
    if cfg is None:
        return True
    return bool(cfg.stt.get("enabled", True))


def _configured_backends(cfg: kbc.KbConfig | None) -> list[str]:
    if cfg is None:
        return list(DEFAULT_BACKENDS)
    backends = cfg.stt.get("backends") or list(DEFAULT_BACKENDS)
    return [str(b).lower() for b in backends]


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def available_backends(cfg: kbc.KbConfig | None = None) -> list[str]:
    """Return the configured backends that are actually usable right now."""
    usable: list[str] = []
    allow_cloud = bool(cfg.stt.get("allow_cloud", False)) if cfg else False
    for backend in _configured_backends(cfg):
        if backend == "faster-whisper" and _module_available("faster_whisper"):
            usable.append(backend)
        elif backend == "openai-whisper" and _module_available("whisper"):
            # openai-whisper additionally needs a system ffmpeg
            if kbc.find_ffmpeg() is not None:
                usable.append(backend)
        elif backend == "cloud" and allow_cloud:
            usable.append(backend)
    return usable


def install_hint() -> str:
    """Human-readable, OS-aware guidance for enabling transcription."""
    ffmpeg_hint = kbc.os_install_hint("ffmpeg")
    return (
        "No speech-to-text backend available.\n"
        "Recommended (all platforms, NO system ffmpeg needed):\n"
        "    pip install -r requirements-media.txt\n"
        "  This installs faster-whisper, which decodes audio via bundled PyAV.\n"
        "\n"
        "Alternative (openai-whisper) also needs a system ffmpeg:\n"
        f"    pip install openai-whisper   &&   {ffmpeg_hint}\n"
        "\n"
        "On macOS, if ffmpeg is installed via Homebrew but 'not found', it is\n"
        "likely a PATH issue (/opt/homebrew/bin not visible to the IDE). Prefer\n"
        "faster-whisper, which sidesteps this entirely."
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_ts(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def render_markdown(
    *,
    source_name: str,
    language: str,
    segments: list[dict],
    timestamps: bool,
    backend: str,
    model: str,
    duration: float,
) -> str:
    lines = [
        f"# Transcript: {source_name}",
        "",
        f"> Auto-transcribed via `{backend}` (model `{model}`), "
        f"language `{language or 'unknown'}`, duration {_fmt_ts(duration)}.",
        "> Machine-generated — verify before extracting durable knowledge.",
        "",
    ]
    if not segments:
        lines.append("_(empty transcript — no speech detected)_")
        return "\n".join(lines) + "\n"
    if timestamps:
        for seg in segments:
            ts = _fmt_ts(seg.get("start", 0.0))
            text = (seg.get("text") or "").strip()
            if text:
                lines.append(f"- **[{ts}]** {text}")
    else:
        paragraph = " ".join((seg.get("text") or "").strip() for seg in segments)
        lines.append(paragraph.strip())
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _transcribe_faster_whisper(
    src: Path,
    *,
    model_size: str,
    language: str | None,
    device: str,
    compute_type: str,
    timestamps: bool,
) -> TranscriptResult:
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        str(src),
        language=(language or None),
        vad_filter=True,
    )
    segments: list[dict] = []
    for seg in segments_iter:
        segments.append(
            {"start": float(seg.start or 0.0), "end": float(seg.end or 0.0), "text": seg.text or ""}
        )
    detected_lang = getattr(info, "language", "") or (language or "")
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    text = " ".join(s["text"].strip() for s in segments).strip()
    md = render_markdown(
        source_name=src.name,
        language=detected_lang,
        segments=segments,
        timestamps=timestamps,
        backend="faster-whisper",
        model=model_size,
        duration=duration,
    )
    return TranscriptResult(
        text=text,
        markdown=md,
        language=detected_lang,
        backend="faster-whisper",
        model=model_size,
        duration=duration,
        segments=segments,
    )


def _transcribe_openai_whisper(
    src: Path,
    *,
    model_size: str,
    language: str | None,
    timestamps: bool,
) -> TranscriptResult:
    import whisper  # type: ignore[import-untyped]

    if kbc.find_ffmpeg() is None:
        raise SttUnavailable(install_hint())
    model = whisper.load_model(model_size)
    result = model.transcribe(str(src), language=(language or None))
    segments: list[dict] = []
    for seg in result.get("segments", []) or []:
        segments.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": seg.get("text", ""),
            }
        )
    detected_lang = result.get("language", "") or (language or "")
    text = (result.get("text") or "").strip()
    if not segments and text:
        segments = [{"start": 0.0, "end": 0.0, "text": text}]
    duration = segments[-1]["end"] if segments else 0.0
    md = render_markdown(
        source_name=src.name,
        language=detected_lang,
        segments=segments,
        timestamps=timestamps,
        backend="openai-whisper",
        model=model_size,
        duration=duration,
    )
    return TranscriptResult(
        text=text,
        markdown=md,
        language=detected_lang,
        backend="openai-whisper",
        model=model_size,
        duration=duration,
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def transcribe(
    src: Path | str,
    *,
    cfg: kbc.KbConfig | None = None,
    model: str | None = None,
    language: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    timestamps: bool | None = None,
) -> TranscriptResult:
    """Transcribe an audio/video file using the first available backend.

    Raises :class:`SttUnavailable` if no backend can be used.
    """
    src = Path(src)
    if not src.is_file():
        raise SttUnavailable(f"file not found: {src}")

    stt_cfg = cfg.stt if cfg else {}
    model_size = model or stt_cfg.get("model", DEFAULT_MODEL)
    language = language if language is not None else stt_cfg.get("language", "auto")
    if language in ("auto", "", None):
        language = None
    device = device or stt_cfg.get("device", "auto")
    compute_type = compute_type or stt_cfg.get("compute_type", "int8")
    if timestamps is None:
        timestamps = bool(stt_cfg.get("timestamps", True))

    usable = available_backends(cfg)
    if not usable:
        raise SttUnavailable(install_hint())

    last_error: Exception | None = None
    for backend in usable:
        try:
            if backend == "faster-whisper":
                return _transcribe_faster_whisper(
                    src,
                    model_size=model_size,
                    language=language,
                    device=device,
                    compute_type=compute_type,
                    timestamps=timestamps,
                )
            if backend == "openai-whisper":
                return _transcribe_openai_whisper(
                    src,
                    model_size=model_size,
                    language=language,
                    timestamps=timestamps,
                )
        except SttUnavailable:
            raise
        except Exception as e:  # noqa: BLE001 — try the next backend
            last_error = e
            continue
    raise SttUnavailable(
        f"all backends failed ({', '.join(usable)}): {last_error}\n\n{install_hint()}"
    )


def transcript_metadata(result: TranscriptResult) -> dict:
    """Compact metadata block describing how a transcript was produced."""
    return {
        "stt_backend": result.backend,
        "stt_model": result.model,
        "stt_language": result.language,
        "stt_duration_seconds": round(result.duration, 1),
        "stt_segments": len(result.segments),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Knowledge Engine — speech-to-text")
    parser.add_argument("path", nargs="?", type=Path, help="Audio/video file to transcribe")
    parser.add_argument("--root", type=Path, default=None, help="KB root (for config)")
    parser.add_argument("--model", default=None, help="Whisper model size")
    parser.add_argument("--language", default=None, help="Language code or 'auto'")
    parser.add_argument("--device", default=None, help="auto | cpu | cuda")
    parser.add_argument("--no-timestamps", action="store_true")
    parser.add_argument("--check", action="store_true", help="Report available backends and exit")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write markdown here")
    args = parser.parse_args(argv)

    try:
        cfg = kbc.load_config(args.root) if args.root else kbc.load_config()
    except Exception:  # noqa: BLE001
        cfg = None

    if args.check:
        usable = available_backends(cfg)
        ffmpeg = kbc.find_ffmpeg()
        print("STT backends configured:", ", ".join(_configured_backends(cfg)))
        print("STT backends available: ", ", ".join(usable) if usable else "(none)")
        print("ffmpeg:", ffmpeg or "(not found — fine for faster-whisper)")
        if not usable:
            print("\n" + install_hint())
            return 1
        return 0

    if not args.path:
        parser.error("path is required unless --check is used")

    try:
        result = transcribe(
            args.path,
            cfg=cfg,
            model=args.model,
            language=args.language,
            device=args.device,
            timestamps=not args.no_timestamps,
        )
    except SttUnavailable as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    if args.output:
        args.output.write_text(result.markdown, encoding="utf-8")
        print(f"✅ wrote {args.output} ({len(result.segments)} segments, {result.backend})")
    else:
        sys.stdout.write(result.markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
