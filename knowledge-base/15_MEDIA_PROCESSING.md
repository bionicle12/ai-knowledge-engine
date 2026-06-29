# 15 — Media processing (transcription, OCR, archives)

> Contract for turning **non-text inputs** — audio, video, images, archives —
> into text the pipeline can route, enrich, and index.
>
> **Reference implementations:** `scripts/kb_stt.py` (speech-to-text),
> `scripts/kb_ocr.py` (OCR), and the `_run_archive` helper in
> `scripts/kb_ingest.py`. These are wired into `kb_ingest.py` and run
> automatically during ingest.

---

## Design goals

1. **Out of the box, every platform.** No reliance on system tools that are
   easy to get wrong. The defaults install via `pip` and carry their own codecs
   and models. In particular: **no system `ffmpeg` is required.**
2. **Local-first / private.** Transcription and OCR run on the machine. Cloud
   backends are **off by default** and only used if the user opts in.
3. **Graceful degradation.** If a backend is missing, the file still lands in
   `assets/`, and a review package is created with an OS-specific install hint —
   the pipeline never silently loses data and never crashes the run.

## Install

```bash
pip install -r requirements-media.txt   # faster-whisper + rapidocr
```

Verify:

```bash
python3 scripts/kb_stt.py --check
python3 scripts/kb_ocr.py --check
python3 scripts/kb_doctor.py            # STT/OCR/ffmpeg appear in the report
```

## Configuration (`kb.config.yml` → `media`)

```yaml
media:
  stt:
    enabled: true
    backends: ["faster-whisper", "openai-whisper"]
    model: "small"          # tiny | base | small | medium | large-v3
    language: "auto"        # "auto" or ISO code ("ru", "en", …)
    device: "auto"          # auto | cpu | cuda
    compute_type: "int8"    # int8 (fast CPU) | float16 (GPU) | float32
    timestamps: true        # add [mm:ss] markers per segment
    allow_cloud: false      # never send audio to a cloud API unless true
  ocr:
    enabled: true
    backends: ["rapidocr", "tesseract"]
    language: "auto"
  archives:
    enabled: true
    max_files: 200
```

## Speech-to-text (STT)

- **Default backend: `faster-whisper`.** Audio is decoded with PyAV, which
  bundles the FFmpeg libraries — so **no system `ffmpeg`** is needed on macOS,
  Windows, or Linux.
- **Fallback backend: `openai-whisper`.** Used only if listed in `backends` and
  a system `ffmpeg` is found. `kb_common.find_ffmpeg()` looks beyond `PATH`
  (e.g. `/opt/homebrew/bin`) to dodge the macOS GUI-PATH trap.
- Output: `processed/transcripts/<slug>.md`, with a header noting backend,
  model, detected language, and duration; segments listed with `[mm:ss]`
  timestamps when enabled.
- Metadata: the extracted-metadata YAML gains `stt_backend`, `stt_model`,
  `stt_language`, `stt_duration_seconds`, `stt_segments`.

Supported inputs include `.mp3 .wav .m4a .flac .ogg .aac .opus` (audio) and
`.mp4 .mov .webm .mkv .avi .m4v` (video — the audio track is transcribed).

## OCR (images / scans / screenshots)

- **Default backend: `rapidocr-onnxruntime`** — ships its own ONNX models and
  runtime; no system dependencies.
- **Fallback backend: `tesseract`** via `pytesseract` (requires the system
  `tesseract` binary).
- Output: `processed/ocr/<slug>.md`.
- Supported inputs: `.png .jpg .jpeg .webp .tiff .bmp`.

## Archives

- `.zip`, `.tar`, `.tar.gz`/`.tgz` are unpacked into `raw/unsorted/unsorted/`
  (member names flattened and prefixed with the archive name) so each file is
  re-ingested on the next pass. A short listing is written to
  `processed/markdown/`.
- `.rar` is **not** unpacked by the standard library — it routes to review with
  a hint to extract manually (or install a tool like `unar`).
- `media.archives.max_files` caps how many members are extracted (zip-bomb
  safety).

## Agent behavior (important)

When an audio/video/image file arrives and transcription/OCR is unavailable, the
review package in `review/needs-ai-decision/` contains the exact install command
for the user's OS. The agent should:

1. **Run `python3 scripts/kb_doctor.py` first** to confirm what's available.
2. **Surface the install hint** to the user (e.g. "run
   `pip install -r requirements-media.txt`"). Do **not** blindly call `ffmpeg`
   or assume system tools exist.
3. Only after the backend is installed, re-run ingest (`./shell/reindex.sh` or
   `python3 scripts/kb_reindex.py`) — do not hand-transcribe in chat unless the
   user explicitly prefers that.

## Exit behavior

Media steps never raise out of ingest: a missing backend is caught and turned
into a review routing with a hint. A run with only "backend missing" media files
still exits `0` (files were safely stored and queued), so automation/watchers
keep working.
