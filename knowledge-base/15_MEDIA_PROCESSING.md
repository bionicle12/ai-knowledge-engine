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
2. **Local-first / private.** Transcription and OCR run on the machine. There
   is no cloud backend: `media.stt.allow_cloud` is reserved and nothing reads
   it yet.
3. **Graceful degradation.** If a backend is missing, the file still lands in
   `assets/`, and a review package is created with an OS-specific install hint —
   the pipeline never silently loses data and never crashes the run.
4. **Load once.** A Whisper model and the RapidOCR engine load on first use and
   stay loaded for the rest of the process, so one ingest run over many files
   pays the model start-up once.

## Install

```bash
pip install -r requirements-media.txt   # faster-whisper + rapidocr
```

For OCR of text that is not Chinese or English (Cyrillic, for example), also
install Tesseract with that language's data — see [OCR](#ocr-images--scans--screenshots).

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
    allow_cloud: false      # reserved for a future cloud STT backend (not implemented)
  ocr:
    enabled: true
    backends: ["rapidocr", "tesseract"]
    language: "auto"        # "auto" = language_policy.primary + English, or "ru", "ru+en", [ru, en]
  archives:
    enabled: true
    max_files: 200          # members unpacked per archive
    max_total_mb: 500       # uncompressed total per archive (0 = no limit)
    max_member_mb: 200      # per member (0 = no limit)
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
- If the installed backends fail, the message names each backend and its
  error — it does not claim a backend is missing — and says which kind of
  failure it was (see [Failure messages](#failure-messages)).

Supported inputs: `.mp3 .wav .m4a .flac .ogg .oga .aac .wma .opus` (audio) and
`.mp4 .mov .webm .mkv .avi .m4v .mpg .mpeg` (video — the audio track is
transcribed).

## OCR (images / scans / screenshots)

- **Default backend: `rapidocr-onnxruntime`** — ships its own ONNX models and
  runtime; no system dependencies.
- **Fallback backend: `tesseract`** via `pytesseract` (requires the system
  `tesseract` binary).
- **Language.** `media.ocr.language` takes ISO codes (`"ru"`, `"ru+en"`, or a
  YAML list `[ru, en]`; region tags such as `ru-RU` count as `ru`); `"auto"`
  means `language_policy.primary` plus English. Tesseract receives them as its
  own language names (`ru` → `rus`, `en` → `eng`, …; a Tesseract name such as
  `chi_tra` passes through), limited to the language data it has installed
  (`tesseract --list-langs`): a language without data is left out, with
  Tesseract's default (English) when none is left, and the result carries a
  warning line naming the missing data and the install command.
- RapidOCR's bundled model reads only Chinese and English and takes no language
  setting. When the language list has anything else, `tesseract` is tried first
  if it has that language's data; otherwise the configured order stays. A
  RapidOCR result on such text carries a warning line that it may be garbled.
- Tesseract language data (English ships with every install):
  `sudo apt install tesseract-ocr-rus` (Debian/Ubuntu; one package per
  language), `brew install tesseract-lang` (macOS), or tick the language under
  "Additional language data" in the Windows installer.
  `python3 scripts/kb_ocr.py --check` prints the languages in effect and the
  installed and missing Tesseract data; `python3 scripts/kb_doctor.py` shows
  its missing-data and install lines as a `media:ocr` warning.
- If the installed backends fail, the message names each backend's error
  instead of an install hint (see [Failure messages](#failure-messages)).
- Output: `processed/ocr/<slug>.md`.
- Supported inputs: `.png .jpg .jpeg .webp .tif .tiff .bmp`.

## Archives

- `.zip`, `.tar`, `.tar.gz`/`.tgz` are unpacked into the archive's own
  `raw/<category>/unsorted/` (member names flattened and prefixed with the
  archive name) and the members are ingested in the same run. A short listing
  is written to `processed/markdown/`; it gets no NLP enrichment.
- `.rar` is **not** unpacked by the standard library — it routes to review with
  a hint to extract manually (or install a tool like `unar`).
- Limits (zip-bomb safety), per archive: `media.archives.max_files`,
  `max_total_mb` (uncompressed total) and `max_member_mb`. Only one level is
  unpacked: an archive inside the archive is not, so nesting cannot multiply
  the limits. The archive then goes to `review/needs-ai-decision/`, whose
  package explains how to extract a nested archive by hand (it is then
  unpacked with its own limits). Members over a limit, nested archives,
  members already ingested and unreadable members are skipped and listed
  under "Not unpacked" in the listing.

## Failure messages

When a backend is installed but transcription/OCR still fails, the message in
the review package starts with one of:

| Message starts with | Meaning |
|---|---|
| `no … backend could be imported` | Broken install; the install hint follows. |
| `no … backend could start, so <file> was not read` | Setup problem, not the file: the model could not be downloaded (offline first run, proxy, Hugging Face rate limit) or loaded (disk, memory), the ONNX runtime did not start, or Tesseract lacks its binary or language data. |
| `every installed … backend failed on <file>` | At least one backend started and could not read this file, so the file is the likely cause (damaged, or a format the backend cannot decode). |

## Agent behavior (important)

When an audio/video/image file arrives and transcription/OCR is unavailable, the
review package in `review/needs-ai-decision/` contains the exact install command
for the user's OS. The agent should:

1. **Run `python3 scripts/kb_doctor.py` first** to confirm what's available.
2. **Surface the install hint** to the user (e.g. "run
   `pip install -r requirements-media.txt`"). Do **not** blindly call `ffmpeg`
   or assume system tools exist.
3. Only after the backend is installed, re-process the stored file:
   `python3 scripts/kb_ingest.py assets/<type>/<file>` (the review package
   names the asset). A plain ingest or reindex does not retry it — the file
   already left `raw/`. Do not hand-transcribe in chat unless the user
   explicitly prefers that.

When the message says a backend **could not start**, treat it like a missing
backend: show the user the error, run `python3 scripts/kb_doctor.py`, and
re-process the asset once the setup is fixed (a first model download needs
network access once).

When the message says every installed backend **failed on the file**, the file
is the likely cause: tell the user it may be damaged or in an unsupported
format. Suggest checking the backend (`kb_doctor.py`) only if other files of
the same type fail the same way.

## Exit behavior

Media steps never raise out of ingest: a missing backend is caught and turned
into a review routing with a hint. A run with only "backend missing" media files
still exits `0` (files were safely stored and queued), so automation/watchers
keep working.
