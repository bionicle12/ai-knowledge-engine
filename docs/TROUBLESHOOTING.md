# Troubleshooting

> Common problems and solutions when deploying or running an AI Knowledge Engine base.

## Installation

### `pip install -r requirements.txt` fails on `spacy`

Some platforms need extra build tools.

**Linux/Debian/Ubuntu:**
```bash
sudo apt install -y build-essential python3-dev
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

**macOS:**
```bash
xcode-select --install
pip install --upgrade pip wheel setuptools
pip install -r requirements.txt
```

**Windows:**
- Install Visual Studio Build Tools (C++ workload)
- Or use spaCy's pre-built wheels: `pip install spacy --only-binary=:all:`

### `python3 -m spacy download ru_core_news_md` fails

Possible causes:

1. **Network blocking GitHub releases.** spaCy downloads models from GitHub. Use a mirror or download the wheel manually:
   ```bash
   pip install https://github.com/explosion/spacy-models/releases/download/ru_core_news_md-3.7.0/ru_core_news_md-3.7.0-py3-none-any.whl
   ```
2. **Wrong spaCy major version.** Match model version to spaCy version (3.7.x model with 3.7.x spaCy).
3. **Disk space.** Models are 40–500 MB. Free up space and retry.

### `kb_doctor.py` reports missing optional packages

This is fine for many features. Watchdog, OCR, STT, KeyBERT, RAKE are optional. Install only what you need:

```bash
# Watchdog (file watcher)
pip install 'watchdog>=4.0,<5.0'

# Transcription (STT) + OCR, out of the box, no system tools:
pip install -r requirements-media.txt

# Better keyword extraction
pip install 'keybert>=0.8,<1.0'
```

## Pipeline (kb_ingest.py)

### "conversion failed: <ext>"

The pipeline can convert: `.md`, `.txt`, `.docx`, `.pdf`, `.pptx`, `.xlsx`, `.csv` out of the box, plus audio/video (STT) and images (OCR) once `requirements-media.txt` is installed (see "Transcription & OCR" below). For anything else it routes to `review/needs-ai-decision/` and the AI agent handles it in chat.

If a supported type fails:

- **`.docx`** → install `python-docx` (`pip install python-docx`)
- **`.pdf`** → install `pypdf`. For scanned PDFs you also need OCR (see Installation)
- **`.pptx`** → install `python-pptx`
- **`.xlsx`/`.csv`** → install `openpyxl` and/or `pandas`

### Pipeline ignores a file

Check:

1. Is the file in `raw/<sub>/unsorted/`? Files placed elsewhere in `raw/` are not picked up by default.
2. Is the extension in `nlp.skip_extensions` of `kb.config.yml`? It will be skipped intentionally.
3. Is the file already ingested? `kb_ingest.py` is idempotent; if the same hash is in `processed/extracted-metadata/`, the file is skipped.
4. Permission errors? Run with `--json` to see structured error output.

### Files appear in `review/needs-ai-decision/` for trivial input

The complexity threshold may be too low. In `kb.config.yml`:

```yaml
nlp:
  complexity_threshold: 0.7   # raise this if too many files end up in review
```

## Transcription & OCR (media)

### Audio/video files end up in review with "conversion unavailable"

The media backends aren't installed. Install them (works on all platforms, no
system tools needed):

```bash
pip install -r requirements-media.txt
python3 scripts/kb_stt.py --check      # should list "faster-whisper"
```

Then re-run ingest: `./reindex.sh` (or `python3 scripts/kb_reindex.py`).

### macOS: "ffmpeg not found" even though `brew install ffmpeg` succeeded

This is the classic Homebrew PATH trap on Apple Silicon: `ffmpeg` lives in
`/opt/homebrew/bin`, which is **not** on the PATH that your IDE hands to its
child processes. Two fixes:

1. **Preferred — don't use ffmpeg at all.** The default STT backend
   (`faster-whisper`) decodes audio via bundled PyAV and never calls system
   `ffmpeg`:
   ```bash
   pip install -r requirements-media.txt
   ```
2. If you specifically want the `openai-whisper` backend, ensure
   `/opt/homebrew/bin` is on PATH for the IDE, or launch the IDE from a
   terminal. `kb_common.find_ffmpeg()` also probes `/opt/homebrew/bin` directly,
   so `kb_doctor.py` will report ffmpeg as found even when `which ffmpeg` fails
   in the IDE's environment.

### Transcription is slow or low quality

Tune `media.stt` in `kb.config.yml`:

- **Faster:** `model: "base"` or `"tiny"`, `compute_type: "int8"`.
- **Higher quality:** `model: "medium"` or `"large-v3"` (slower; a GPU with
  `device: "cuda"`, `compute_type: "float16"` helps a lot).
- **Force a language** instead of auto-detect: `language: "ru"`.

### OCR backend not found

```bash
pip install rapidocr-onnxruntime    # no system dependency
python3 scripts/kb_ocr.py --check
```

The Tesseract backend additionally needs the system `tesseract` binary
(`brew install tesseract` / `sudo apt install tesseract-ocr` /
`winget install UB-Mannheim.TesseractOCR`).

### `.rar` archive not unpacked

The standard library can't read `.rar`. Extract it manually into
`raw/<category>/unsorted/` and re-run ingest, or install a tool like `unar`.
`.zip`, `.tar`, and `.tar.gz` are unpacked automatically.

## Lint (kb_lint.py)

### Many false-positive "stale" warnings on first run

Right after deploy, `last_verified` may equal `extracted_at` for everything. This is fine — they will hit the staleness threshold (30 days by default) only after a month. Adjust if needed:

```bash
python3 scripts/kb_lint.py --stale-days 60
```

### "broken-link" on a wikilink that exists

- Check the slug exactly matches the filename (without `.md`)
- Multiple files with the same slug? Use the explicit path: `[[domain/caching]]` instead of `[[caching]]`
- Lint scans `knowledge/**/*.md` only — wikilinks to files outside `knowledge/` are not resolved

### "duplicate-slug" error

Two files in different `knowledge/` subfolders share a name. Either rename one or always use the full path in wikilinks.

## Watcher (kb_watch.py)

### Watcher does not pick up new files

1. **Check it's running:** `./watcher.sh --status`
2. **Watchdog installed?** `pip install watchdog`
3. **Path matches?** The watcher monitors `raw/*/unsorted/` and `knowledge/`. Files dropped into `raw/` itself (not a subfolder's `unsorted/`) are ignored.
4. **Debounce:** there is a 5-second wait after file creation to ensure it's fully written. New files won't process instantly.
5. **Polling fallback:** if watchdog is missing, the script switches to polling every 2 seconds. Slower, but works.

### Watcher dies unexpectedly

Check `.watcher.log`:

```bash
tail -50 .watcher.log
```

Common causes: NLP model crash, disk full, killed by OOM. Restart with `--verbose`:

```bash
./watcher.sh --stop
./watcher.sh --verbose
```

## Repomix

### `repomix: command not found`

```bash
npm install -g repomix
```

If `npm` itself is missing, install Node.js 20+. See `01_PREREQUISITES.md`.

### Index is too large

In `repomix.config.json`:

```json
{
  "output": {
    "compress": true,
    "removeComments": true,
    "removeEmptyLines": true
  }
}
```

This reduces token count by 50–70%. If still too large, split into profiles (see `quick-start/INIT_GUIDE.md`).

### Sensitive data leaked into the index

The Repomix `enableSecurityCheck` should catch most secrets. If it didn't:

1. Add the file pattern to `ignore.customPatterns`
2. Move the file from `knowledge/` to `review/needs-redaction/`
3. Re-run `repomix` after cleanup

## Reflection (kb_reflect.py)

### `kb_reflect.py --check-threshold` always returns SKIP

- No new ingests since last reflection? Run `python3 scripts/kb_reflect.py --count-changes` to confirm
- `importance_threshold` too high? Lower it in `kb.config.yml.mode_profiles.<mode>.reflection.importance_threshold`
- `min_interval_days` too long? Lower it (default 7)

### `kb_reflect.py --generate` doesn't actually do anything

Correct — the actual reflection (synthesizing higher-level insights) is done by the **AI agent** in your IDE. The script only updates the `.last_reflection` marker and logs the trigger. The agent picks up the trigger from `log.md` next session.

## Translations

### `check_translations.py` reports everything as "in_sync" right after I edited a file

The drift checker reads from git history. If you have uncommitted changes in `knowledge-base/`, they aren't visible to git. Commit first, then re-run the check.

### After a release, all `i18n/ru/` files are marked stale

This is expected. The canonical EN files moved to a new commit, so the recorded `source_commit` in RU frontmatter lags. Update the translations and bump their `source_commit` to the latest commit SHA.

## General

### `kb_doctor.py` reports an error but everything seems to work

Read the message carefully. Common false alarms:

- **`config: kb.config.yml not found`** — you ran the doctor outside the KB root. Pass `--root /path/to/kb`.
- **`opt:<package>: missing`** — these are warnings, not errors. Optional features just won't run.

If the error persists and is unclear, run with `--json` for structured output and file an issue.

### How do I migrate a base between machines?

See `08_PORTABLE.md` (knowledge-base module). TL;DR:

```bash
tar czf kb-portable.tar.gz \
  --exclude='.venv' \
  --exclude='assets/' \
  --exclude='.repomix/' \
  knowledge-base/
```

Move the tarball, extract, recreate venv, run `./reindex.sh`.
