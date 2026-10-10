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

# Better keyword extraction (KeyBERT pulls in PyTorch — see 01_PREREQUISITES.md)
pip install -r requirements-nlp.txt
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
2. Does its name match `ingest.ignore_globs` in `kb.config.yml` (default: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `~$*`, `._*`, `*.part`, `*.crdownload`, `*.tmp`, `*.swp`)? Such files are skipped on purpose.
3. `python3 scripts/kb_ingest.py --status` lists what is still in `raw/**/unsorted/` and why (for example a duplicate of an already ingested file, or a conversion error). The same count appears in `STATUS.md`.
4. `nlp.skip_extensions` does not skip a file: it only turns off NLP enrichment for those extensions; the file is still ingested.
5. Permission errors? Run with `--json` to see structured error output.

### Processed material never reaches `knowledge/`

Every ingested file is tracked in its metadata
(`processed/extracted-metadata/<name>.yml`) as `extraction: pending` until the
agent writes it into `knowledge/`.
`python3 scripts/kb_ingest.py --status` counts the pending items (and how old
the oldest one is); `!review` covers them along with the `review/` queues.
After writing the pages, the agent records the result with
`kb_ingest.py --mark-extracted <path> --to <knowledge page>` or
`--mark-skipped <path> --reason "<text>"`.

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

### Too many "stale" warnings

Lint and the `!view` viewer share one stale rule (`kb_common.stale_status`).
A page is stale when the newer of `last_verified` and `extracted_at` is older
than `lifecycle.stale_warning_days` (default 30). It is never stale when it is
under `_archive/`, carries `generated_by:` (script-written), is
`lifecycle: permanent`, has a `valid_until` date that has not passed, or has
no date at all. `lifecycle.by_folder` makes whole folders permanent — by
default `decisions/`, `profile/` and `principles/` — unless a page sets a
non-default lifecycle of its own.

To clear a warning, re-check the page and update `last_verified`. To change
the threshold, set `lifecycle.stale_warning_days`, or for one run:

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
3. **Path matches?** The watcher monitors the folders in `autorun.watch_dirs` (default `raw/*/unsorted/` and `knowledge/`), and only while `autorun.watch_enabled` is true. Files dropped into `raw/` itself (not a subfolder's `unsorted/`) are ignored.
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

Without a global `repomix`, `kb_reindex.py` runs the pinned
`npx repomix@<index.repomix_version>` while `index.npx_fallback` is true (the
default); that needs Node.js 20+ with `npx`. See `01_PREREQUISITES.md`.

### A pack is too large

Packs are split automatically (see `05_INDEX.md`). A pack still above its
token ceiling is marked OVER in `.repomix/PACKS_STATUS.md` and in `STATUS.md`.
Split the section into deeper subfolders or list packs explicitly under
`index.packs`, or choose a larger `index.window_profile` if your model's
context window allows it. Do not turn on Repomix `compress` or
`removeComments`: in a knowledge base the text is the payload, so the size
problem is solved by splitting harder, never by compressing.

### Sensitive data leaked into the index

Repomix's `enableSecurityCheck` leaves a file with credential-looking text out
of its pack without a word. `kb_reindex.py` notices the gap: the file is listed
under "Left out by repomix" in `.repomix/PACKS_STATUS.md` and counted on the
`index:` line of `STATUS.md`. `python3 scripts/kb_lint.py` (check `secret`)
names the kind and line of every credential-looking string in `knowledge/`,
never the value. `knowledge/` is committed, so a secret there is a leak even
when the index skipped the page:

1. Remove the value from the page (keep a placeholder such as `<redacted>`),
   or move the page from `knowledge/` to `review/needs-redaction/`
2. If the value was committed, rotate it — removing it from the page does not
   remove it from git history
3. Re-run `python3 scripts/kb_reindex.py`; the pack is rebuilt and the
   "Left out" line disappears

A file that must never be indexed at all: add its pattern to
`ignore.customPatterns` in `repomix.config.json`.

## Reflection (kb_reflect.py)

### `kb_reflect.py --check-threshold` always returns SKIP

It prints `THRESHOLD_MET`, `SKIP` or `STAGNANT` (see `13_AUTORUN.md`).

- No new ingests since last reflection? Run `python3 scripts/kb_reflect.py --count-changes` to confirm (in `super` mode zero changes is always `SKIP`)
- `importance_threshold` too high? Lower it in `kb.config.yml.mode_profiles.<mode>.reflection.importance_threshold`
- `min_interval_days` too long? Lower it (default 7)
- `STAGNANT` means the last two recorded reflections both produced 0 insights

### `kb_reflect.py --generate` doesn't actually do anything

Correct — the actual reflection (synthesizing higher-level insights) is done by the **AI agent** in your IDE. `--generate` only logs a `reflect-request` in `log.md`, and only when the threshold is met and no request is already pending. When the agent has finished, it runs `python3 scripts/kb_reflect.py --record-result N` (N = insights written, 0 is valid); only that updates the `.last_reflection` marker and the page snapshot `.kb-state/reflection-pages.json`, and logs the `reflect` operation. Every other mode is read-only.

## Translations

### `check_translations.py` says "❔ unknown"

The checker compares each EN source with its text at the translation's
`source_commit`, which needs git history. You get `unknown` in a copy without
`.git`, for an EN file that is not committed yet, or when `source_commit` is
missing from a shallow clone (`git fetch --unshallow`). `--strict` fails on it.

### I edited an EN file and its translation shows "uncommitted edits"

Expected: drift includes working-tree edits. Update the translation, commit
the EN change, then stamp with `python3 scripts/sync_translations.py
--to-source` (it skips a source that still has uncommitted edits).

### After a release, `i18n/ru/` files are marked stale

A version badge change alone is not drift. Files are stale when the EN text
itself changed since their `source_commit`: update the translations, then
`python3 scripts/sync_translations.py --to-source` and
`python3 scripts/check_translations.py --update-status`.

### `sync_translations.py` says "nothing to stamp"

It no longer stamps today's date and the repo version on every file by
default. Pass `--to-source` (the usual choice), `--to-commit <rev>`,
`--to-head`, or an explicit `--to-version` / `--to-date`. See
`docs/TRANSLATING.md`.

## Status, runtime docs and locks (0.16+)

### `STATUS.md` is missing or out of date

`STATUS.md` in the base root is written by `scripts/kb_status.py` at the end of
every `kb_reindex.py` run (the post-commit hook included) and by `!status`. It
lists only what needs attention, each line ending with the command that
resolves it, or `- all clear`. It is generated — do not edit it — and ignored
by git and by the index packs. Refresh it by hand:

```bash
python3 scripts/kb_status.py           # write STATUS.md
python3 scripts/kb_status.py --print   # show without writing
```

Also check `status.enabled` / `status.file` in `kb.config.yml` (defaults:
`true`, `STATUS.md`).

### The agent cannot find `kb-docs/NN_*.md`

Since 0.16 a base keeps its runtime instruction modules (`NN_*.md` and
`README.md` from the engine's `knowledge-base/`) in `<base>/kb-docs/`.
`finalize.sh` copies them at deploy time and `kb_upgrade.py` keeps them
current, so a base deployed earlier gets them on its next upgrade (see
`docs/UPGRADING.md`); `!heal` then moves pristine root-level
`17_REFACTOR.md` / `18_HEAL.md` into `kb-docs/` (a customized copy becomes an
assisted item). Do not edit files in `kb-docs/` — the next upgrade treats a
local edit as a customization to review. `kb-docs/` is excluded from lint and
the index packs.

### "`'pipeline' lock is busy (another kb_* process holds …)`"

Pipeline scripts take a lock in `.kb-state/locks/<name>.lock` so two runs
(say the watcher and a manual reindex) cannot write the same files at once.
Wait for the other run to finish. The operating system releases the lock when
its holder exits, even after a crash, so the `.lock` file left on disk is
harmless and needs no cleanup. A child process started by the holder (for
example `kb_reindex` → `kb_ingest`) shares the lock instead of waiting.

The post-commit hook waits only briefly: when the lock stays busy it exits
quietly and notes it in `.kb-state/hooks.log`.

If the lock fails immediately with an `OSError` such as `ENOLCK` or
`EOPNOTSUPP`, the base lives on a filesystem without file-lock support (some
network or sync-client folders). Move the base to a local disk.

### What is `.kb-state/`?

Machine-local state: locks, hash caches, the hook log, the lint summary
(`lint-summary.json`). It ignores itself in git (`.kb-state/.gitignore`) and
is recreated on demand, so deleting it while no `kb_*` script runs only drops
caches and logs — except `upgrade-backups/` (copies `kb_upgrade.py --accept` /
`--force` saved before overwriting a customized file), `upgrade-local.json`
(remembered `--accept-local` decisions and open `AGENTS.md` block merges) and
`refactor-backups/` (the files `!refactor` rewrote): keep those while you may
need them. Leave it out when you copy a base to another machine.

### `!view` says "Cannot keep the viewer state private", or `!view status` misses a running viewer

The background viewer keeps its URL and stop token outside the base, in a
folder only you can read: `$XDG_RUNTIME_DIR/ai-knowledge-engine-viewer/`, else
`<temp dir>/ai-knowledge-engine-viewer-<uid>/` (on Windows
`<temp dir>\ai-knowledge-engine-viewer\`, which is per user already). A folder
there that belongs to another user, or that other users can read or write, is
ignored for safety: `!view status` does not see the viewer, and a new `!view`
refuses to start. A folder of your own is tightened to mode 0700 by the next
`!view`. When it is not yours, point `TMPDIR` (or `XDG_RUNTIME_DIR`) at a
folder of your own and run `!view` again. `!view status` and `!view stop` also
find a viewer started by an engine before 0.16, which kept its state in the
shared `<temp dir>/ai-knowledge-engine-viewer/`.

## Cross-base merge (kb_export.py / kb_import.py)

### `kb_import.py` says "No bundle to import"

Bundles are picked up from `sync/inbox/`. Copy the `.zip` produced by the
other machine's export into `sync/inbox/` (or pass the path explicitly:
`python3 scripts/kb_import.py path/to/bundle.zip`).

### Import finished with exit code 1 — is that a failure?

No. Exit 1 means the merge worked but some pages changed on both sides:
they are waiting in `review/needs-merge/` with a unified diff each. Tell the
agent `!merge` to resolve them. Exit 2 is a real error (unreadable bundle,
missing manifest, unsupported format).

### "not a kb bundle" / "unreadable manifest.yml"

The zip was not produced by `kb_export.py`, or it was corrupted in transfer.
Re-export on the source machine and copy the file again. Bundles also refuse
to unpack when they exceed safety caps (20 000 files / 2 GiB unpacked).

### The same page keeps coming back as a conflict

Both bases keep editing the same file between exchanges. Resolve it once via
`!merge`, then export from the machine that now holds the merged version and
import on the other one — the next exchange fast-forwards instead of
conflicting.

### Where did my previous file go after an import?

Nothing is overwritten silently: every file the import touches is snapshotted
to `sync/backups/<timestamp>/` first. Applied bundles move to
`sync/applied/`.

## General

### `kb_doctor.py` reports an error but everything seems to work

Read the message carefully. Common false alarms:

- **`config: kb.config.yml not found`** — you ran the doctor outside the KB root. Pass `--root /path/to/kb`.
- **`opt:<package>: missing`** — these are warnings, not errors. Optional features just won't run. Warnings alone keep the exit code at 0.

If the error persists and is unclear, run with `--json` for structured output and file an issue.

### How do I migrate a base between machines?

See `08_PORTABLE.md` (knowledge-base module). TL;DR:

```bash
tar czf kb-portable.tar.gz \
  --exclude='.venv' \
  --exclude='.kb-state' \
  --exclude='assets/' \
  --exclude='.repomix/' \
  knowledge-base/
```

Move the tarball, extract, recreate venv, run `./reindex.sh`.
