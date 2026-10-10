# 03 — Python pipeline contract

> Specification of `scripts/kb_ingest.py` — the script that processes raw materials.
>
> **Reference implementation:** `knowledge-base/scripts/kb_ingest.py` (+ shared utilities in `kb_common.py`).
> When deploying, the agent **copies these files** rather than writing them from scratch.
> The contract below describes what the script does; the implementation matches it.

---

## Purpose

`kb_ingest.py` does not have to be smart. Its job is **safe mechanics**: find files, detect their type, convert them to text, move the originals, and queue every file for extraction by the agent. It makes no LLM calls and no semantic decisions — deciding what becomes knowledge is the agent's job in `!review` (see `kb-docs/04_REVIEW.md`).

## Input

Scans every `unsorted/` folder under `raw/` — `raw/<category>/unsorted/` and the catch-all `raw/unsorted/` — **including subfolders** (`raw/work/unsorted/Project X/notes.md`). A `raw/` or `raw/<category>/` that is a symlink to a synced folder (Dropbox, iCloud) works.

Files are left where they are, untouched, when they:

- match `ingest.ignore_globs` (default: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `~$*`, `._*`, `*.part`, `*.crdownload`, `*.tmp`, `*.swp` — OS junk, Office lock files, unfinished downloads);
- are empty (0 bytes);
- are larger than `ingest.max_file_mb` (default 200; `0` or less = no limit).

`--status` lists the empty and too-large ones so the owner can delete, fix or split them.

Files attached/uploaded in chat are not pipeline input until the user confirms they should be added to the main knowledge base and the AI agent stages them into the best matching `raw/<category>/unsorted/` folder.

## Commands

```bash
python3 scripts/kb_ingest.py                    # process everything waiting in raw/**/unsorted/
python3 scripts/kb_ingest.py <file>             # one file under raw/**/unsorted/
python3 scripts/kb_ingest.py assets/<type>/<f>  # re-process an existing asset
python3 scripts/kb_ingest.py --dry-run          # list what would be picked up and where, change nothing
python3 scripts/kb_ingest.py --no-nlp           # skip NLP enrichment
python3 scripts/kb_ingest.py --json             # machine-readable result
python3 scripts/kb_ingest.py --status [--json]  # what waits where (changes nothing)
python3 scripts/kb_ingest.py --mark-extracted <path> --to knowledge/<category>/<slug>.md [--to …]
python3 scripts/kb_ingest.py --mark-skipped <path> --reason "<why>"
python3 scripts/kb_ingest.py --set-category <category> assets/<type>/<f>  # re-process as coming from raw/<category>/
python3 scripts/kb_ingest.py --init-dirs        # create the folder layout and exit
```

`--dry-run` prints each file with the `assets/…` path it would get and flags duplicates (of an ingested file or of another file in the batch). It converts nothing, so the review routing and an archive's members show up only in a real run.

Ingest, re-processing and `--mark-*` take the pipeline lock (`.kb-state/locks/pipeline.lock`, shared with reindex and the watcher). While another run holds it, ingest waits up to 10 minutes, then exits with code 2 and changes nothing. `--dry-run`, `--status` and `--init-dirs` do not lock.

## Per-file processing

1. **Hash** the original: `source_hash` = `sha256:<first 16 hex>` (see `11_PROVENANCE.md`).
2. **Exact duplicate** of an already-ingested file (same `source_hash`) → moved to `ingest.duplicates_dir` (default `raw/_duplicates/<category>/…`) and logged as `ingest-duplicate`. Nothing else happens. Inside one folder the shorter name is kept as the original (`report.md` beats `report (1).md`).
3. **Detect the type** from the extension (`.tar.gz` counts as one extension). A file without an extension, or with an unknown one, is recognised by its magic bytes: PDF, PNG, JPEG, GIF, RTF, DOCX/XLSX/PPTX, ZIP, TAR, TAR.GZ. Only a name without an extension, or one ending in a bare `.gz` (older versions named `.tar.gz` assets `…-tar.gz`), can become an archive this way — zip-based formats such as `.jar` or `.pages` are never unpacked.
4. **Stable name** `YYYY-MM-DD__slug.ext`. The date is the one written in the file name (`2026-09-15`, `2026_09_15`, `20260915`) when there is one, else the file's modification date. When the name is taken — by different content, or by an asset whose derived files would share the name (`plan.md` and `plan.txt` on the same day) — the new asset gets a `__<hash8>` suffix.
5. **Copy** the original to `assets/<type>/`.
6. **Convert** to Markdown (matrix below). Text is decoded whatever its encoding (UTF-8, UTF-16, cp1251, …) and always stored as UTF-8; a non-UTF-8 source is recorded as `source_encoding`.
7. **NLP enrichment** (see `kb-docs/12_NLP_PREPROCESS.md`) → `processed/nlp-meta/<name>.yml`. Skipped with `--no-nlp`, `nlp.enabled: false`, for extensions in `nlp.skip_extensions` (the file is still ingested), and for archives.
8. **Complexity** score 0.0–1.0 (see `12`).
9. **Route** (next section) and write a review package when needed.
10. **Update `assets-index/<type>.md`**.
11. **Write the metadata** `processed/extracted-metadata/<name>.yml` — last, so a file without metadata was never ingested.
12. **Append to `log.md`** (operation `ingest`, or `reprocess` for an asset; see `kb-docs/10_LOG.md`).
13. **Remove the original** from `unsorted/` (and any subfolder that became empty).

All writes of one file are all-or-nothing: if any step fails — Ctrl+C included — everything written for that file is rolled back and the original stays in `unsorted/`. The next run retries it; `--status` shows it as `error` until then.

`<name>` is the asset's stable name without its extension; the processed copy, metadata, NLP metadata, review package and assets-index block of one asset all share it.

### What the script does not do

- **Importance.** The script does not score importance. The agent assigns `importance` (1–10) in the frontmatter of the `knowledge/` page it writes during extraction; reflection weighs page changes by it (see `kb-docs/13_AUTORUN.md`).
- **Surprise filter.** Not implemented yet (see the engine repository's `docs/ROADMAP.md`); ingest writes no `is_surprise`.
- **Language detection.** `language` in the NLP metadata is `language_policy.primary`.

## Routing

Checked in this order; the first match wins.

| Condition | Destination |
|---|---|
| Archive (`.zip`, `.tar`, `.tar.gz`, `.tgz`, `.rar`) | `processed/` (its member listing; damaged members are noted there). The members are unpacked into the archive's own `raw/<category>/unsorted/` and each goes through this table, privacy rows included, in the same run. An archive inside the archive is not unpacked → `review/needs-ai-decision/` (reason `N nested archive(s) not unpacked — unpack manually`). When unpacking is off (`media.archives.enabled: false`) or the format is unsupported (`.rar`) → `review/needs-ai-decision/` with the reason |
| The file came from `raw/<category>/` with `<category>` in `privacy.redact_categories` (default `chats`, `personal-context`) while `privacy.require_redaction_for_chats` is true | `review/needs-redaction/` |
| `privacy.secret_scan` (default true) finds credential-looking strings — GitHub, AWS, Slack, Stripe and OpenAI-style tokens, `password=` / `secret:` assignments (JSON/YAML keys too; not `true`/`null`, `$VAR` or `{{ template }}` values), PEM/OpenSSH/PGP private keys — in the converted text or, for a file of unknown type up to 8 MB (`id_rsa`, `*.pem`, `.env`, `*.json`, …), in the file read as text; or the file name is a credential store: `.env`, `*.env`, `.env.*` (not `*.example`, `*.sample`, `*.template`, `*.dist`), `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `*.kdbx` | `review/needs-redaction/` |
| Unknown type and nothing converted | `review/needs-classification/` |
| Known type but no text (no converter for the format, converter library missing, conversion failed, STT/OCR unavailable) | `review/needs-ai-decision/` with the reason (and install hint) |
| An AI review trigger (below) | `review/needs-ai-decision/` |
| Everything else | `processed/` only |

Routing only decides whether a review package is written, and in which queue. Converted text always goes to `processed/`, and every file (archives aside) waits with `extraction: pending` in its metadata until the agent records the result — see [Extraction registry](#extraction-registry).

### AI review triggers

A file gets a package in `review/needs-ai-decision/` when it:

- scores `complexity >= nlp.complexity_threshold` (default 0.7);
- is a meeting/call transcript (STT output);
- is a chat export from `raw/chats/` longer than 500 lines;
- mentions decisions or hypotheses ("we decided", "decided to", "decision:", "hypothesis", "мы решили", "решение:", "гипотез…");
- is a new version of an ingested file (same original name dropped at the same `raw_path` — same category and subfolder — with other content; metadata written before 0.16 has no `raw_path` and matches by name and category alone): the metadata gets `previous_version` (the latest version, even if an older one was re-processed since), and the package lists the `knowledge/` pages that cite the old version. `Project X/README.md` and `Project Y/README.md` are different files, not versions;
- looks like a long-form reference book (see the last section).

Without spaCy NER the complexity score cannot exceed 0.55, so the threshold is reached only with NER. Such metadata carries `complexity_basis` and the log line says `(no NER)`. Nothing is lost either way: files below the threshold still wait in the extraction registry.

## Conversion matrix

| Type | Handling | Output |
|------|----------|--------|
| `.md`, `.txt` | read as text (encoding detected) | `processed/markdown/` |
| `.rtf` | `striprtf` | `processed/markdown/` |
| `.docx` | `python-docx` (tables → Markdown tables) | `processed/markdown/` |
| `.pdf` | `pypdf`, one `## Page N` section per page (no OCR fallback) | `processed/markdown/` |
| `.pptx` | `python-pptx`, one `## Slide N` section per slide | `processed/markdown/` |
| `.xlsx` | `openpyxl`, one table per sheet | `processed/tables/` |
| `.csv` | standard `csv` module; delimiter (`,` `;` tab `|`) and encoding detected | `processed/tables/` |
| audio: `.mp3` `.wav` `.m4a` `.flac` `.ogg` `.aac` `.opus` … | STT via `kb_stt.py` (faster-whisper, **no system ffmpeg**) | `processed/transcripts/` |
| video: `.mp4` `.mov` `.webm` `.mkv` `.avi` `.m4v` … | STT via `kb_stt.py` (audio stream decoded by PyAV) | `processed/transcripts/` |
| images/scans: `.png` `.jpg` `.webp` `.tiff` `.bmp` | OCR via `kb_ocr.py` (RapidOCR, no system deps) | `processed/ocr/` |
| `.zip`, `.tar`, `.tar.gz`, `.tgz` | unpacked into the archive's own `raw/<category>/unsorted/` (one level: nested archives are not unpacked); the members are ingested in the same run | `processed/markdown/` (listing) |
| `.rar` | not unpacked (needs an external tool such as `unar`) | review package with the hint |
| `.doc`, `.odt`, `.epub`, `.xls`, `.ods`, `.ppt`, `.odp`, `.gif`, `.svg` | no converter | review package only |

Chat exports have no special parser: a `.txt`/`.md` export is read as text; one dropped in `raw/chats/` goes to `review/needs-redaction/` (see Routing).

Archives obey `media.archives`: `max_files` (200), `max_total_mb` (500, uncompressed total), `max_member_mb` (200), per archive. Only one level is unpacked: an archive inside the archive (by extension, or by content for a member without one) is not unpacked, so nesting cannot multiply these limits; the archive goes to review, and its package says how to extract a nested one by hand. Members over a limit, nested archives, members already ingested and unreadable members are skipped and listed under "Not unpacked" in the listing. Long member names are shortened (with a hash) to fit the filesystem. The archive itself needs no extraction (`extraction: skipped`).

STT/OCR run automatically **when `pip install -r requirements-media.txt` has been
done** (see `01_PREREQUISITES.md` and `15_MEDIA_PROCESSING.md`). They degrade
gracefully: if no backend is available, the file is routed to
`review/needs-ai-decision/` with an OS-specific install hint inlined in the
review package — the agent should surface that hint, **not** blindly invoke
`ffmpeg`.

## Metadata format

For every ingested file, `processed/extracted-metadata/<name>.yml` is created:

```yaml
original_filename: "Q2 Strategy Draft v3.docx"
stable_filename: "2026-05-06__q2-strategy-draft-v3.docx"
asset_path: "assets/documents/2026-05-06__q2-strategy-draft-v3.docx"
processed_path: "processed/markdown/2026-05-06__q2-strategy-draft-v3.md"   # null when nothing converted
source_hash: "sha256:a1b2c3d4e5f60718"
file_type: "docx"
asset_type: "documents"
strategy: "docx"                   # converter used (passthrough, csv, stt, ocr, archive, unknown, …)
raw_category: "work"               # raw/<category>/ the file came from
processing_date: "2026-05-06T10:30:00+03:00"
raw_path: "raw/work/unsorted/Q2 Strategy Draft v3.docx"   # where it was dropped (since 0.16)
extracted_at: "2026-05-06"
valid_from: "2026-05-06"
lifecycle: "evolving"              # lifecycle.default
confidence: "medium"
complexity: 0.72
long_book_hint: false
needs_ai_review: true              # a review package exists
review_queue: "review/needs-ai-decision/"   # null → processed/ only
review_reason: "complexity 0.72 >= 0.7"
nlp_meta_path: "processed/nlp-meta/2026-05-06__q2-strategy-draft-v3.yml"
extraction: "pending"              # pending | done | skipped
extracted_to: []                   # knowledge/ pages, filled by --mark-extracted
```

Written only when they apply: `complexity_basis` (no NER), `source_encoding` (non-UTF-8 text), `previous_version` (new version of an ingested file), `redaction: pending|resolved` + `redaction_reasons` (privacy review; only the kind and line number of a secret, never its value), `stt_*` (transcripts), `archive_extracted_files` / `archive_notes` (archives), `extraction_note` (skipped).

Re-processing an asset recomputes these mechanical fields and keeps everything else — the extraction record, `importance`, notes the agent added.

## assets-index entry format

Ingest adds or updates one block per asset in `assets-index/<type>.md`:

```markdown
## 2026-05-06__q2-strategy-draft-v3

- Type: documents
- Original: `assets/documents/2026-05-06__q2-strategy-draft-v3.docx`
- Converted: `processed/markdown/2026-05-06__q2-strategy-draft-v3.md`
- Extracted knowledge: `knowledge/domain/growth-channels.md`, `knowledge/decisions/2026-05-06__q2-budget-shift.md`
- Description: Draft Q2 growth strategy — channels, hypotheses, budget
```

The script manages the `Type`, `Original`, `Converted`, `Category`, `Status` and `Extracted knowledge` lines. It writes the `Description` placeholder once; the agent replaces it with a one-line summary during review, and re-processing never overwrites it or any other line the agent added.

A **private** asset (privacy category or secret-scan hit) never shows its file name or paths in the index or in `log.md`, which get indexed. Its block is titled `<category> item <sha8>` (hash prefix of the original) and shows `Type`, `Category` and `Status` (privacy review pending / done).

**Bases ingested before 0.16** recorded no `raw_category`, so their chats and personal files still have named blocks. Re-process each such asset with its category:

```bash
python3 scripts/kb_ingest.py --set-category chats assets/documents/2026-03-02__chat-with-ivan.txt
```

This records `raw_category`, replaces the named block (with its Description, which may name the file) by the neutral one and opens a privacy review in `review/needs-redaction/`. Older `log.md` entries (and `log-archive/`) still name the file; edit them by hand if the base is shared. A path outside `assets/` → exit 2.

## Extraction registry

Every ingested file waits for the agent: its metadata says `extraction: pending` until the agent records what became of it. `!review` covers the `review/needs-*` queues **and** the files in `processed/` whose metadata is pending (`--status` counts them).

After extracting a file:

```bash
# Knowledge went into one or more pages → extraction: done, pages added to extracted_to
python3 scripts/kb_ingest.py --mark-extracted assets/documents/2026-05-06__q2.docx \
  --to knowledge/domain/growth-channels.md --to knowledge/decisions/2026-05-06__q2-budget-shift.md

# Nothing worth keeping → extraction: skipped, reason in extraction_note
python3 scripts/kb_ingest.py --mark-skipped processed/markdown/2026-05-06__q2.md --reason "duplicate of the Q1 memo"
```

- The path may be the asset, the processed copy, the metadata or NLP-metadata file, or the review package. `--to` pages must exist (`domain/x.md` is read as `knowledge/domain/x.md`).
- Both commands update the assets-index block, log a `review` entry, and turn `redaction: pending` into `resolved`. Delete the review package yourself.
- Unknown path or page → exit 2, nothing changed.

Metadata written before 0.16 has no `extraction` field. It counts as pending unless a `knowledge/` page cites its asset (or processed copy) in `source:`. The heal migration `extraction-registry` fills the field in (`done` + `extracted_to` when cited, else `pending`).

## Status

`python3 scripts/kb_ingest.py --status` changes nothing in the base (it may refresh the metadata cache in `.kb-state/`) and reports:

- files waiting in `raw/**/unsorted/` by reason: `new` (not ingested yet), `empty`, `too-large`, `error` (the last run failed on this very file and it has not changed since);
- the number of files with `extraction: pending` and the age of the oldest;
- each `review/needs-*` queue with its size and oldest item.

`--status --json` prints the same data that `kb_ingest.collect_status(root)` returns (`STATUS.md` is built from it):

```json
{"unsorted": {"total": 2, "by_reason": {"new": 1, "error": 1}},
 "extraction_pending": 9, "extraction_pending_oldest_days": 30,
 "review": {"needs-ai-decision": {"count": 3, "oldest_days": 12}}}
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All files processed (skipped and duplicate files count as processed) |
| `1` | Some files failed (listed on stderr; they stay in `unsorted/`) |
| `2` | Environment or usage error: no or invalid `kb.config.yml`, pipeline lock busy, unknown `--mark-*` path or page, missing path argument, `--set-category` path outside `assets/` |

A missing converter library is not an error: the file goes to review with the reason.

## Idempotency

Re-running is safe. Content that is already ingested is recognised by its hash and moved to the duplicates folder, never copied to `assets/` twice. Re-processing an asset (`kb_ingest.py assets/<type>/<file>`) rewrites its derived files and keeps what the agent recorded. The metadata registry is cached in `.kb-state/ingest-registry.json` (only changed metadata files are re-read). The files the last run failed on are listed in `.kb-state/ingest-errors.json`.

---

## Handling long reference materials (books, courses, manuals)

Some inputs are **long-form reference texts**, not raw notes — published books on writing craft, programming textbooks, business strategy books, research methodology manuals. The pipeline can extract their text, but doing so risks three things:

1. **Token cost:** a 300-page book ≈ 70-90K words. The agent burns ~50-100K tokens trying to summarize it during review.
2. **Copyright greyness:** the full text of a copyrighted book ending up inside `knowledge/` (and from there in the Repomix index) is uncomfortable even for personal use, and dangerous if the base is ever shared.
3. **Voice / style contamination:** for writer or content-creator roles especially, the prose of a famous author inside `voice/` or `principles/` will quietly seep into the AI's tone, displacing the user's own voice.

A converted `.pdf` or `.docx` with at least 25,000 words (or a PDF with at least 80 pages) is flagged `long_book_hint: true` and gets a review package with the long-book flow below.

### Recommended pattern: PDF as reference, notes as knowledge

```
raw/documents/unsorted/Save-the-Cat.pdf
        ↓ pipeline
assets/documents/2026-05-16__save-the-cat.pdf   ← stays here, NOT indexed
assets-index/documents.md                        ← contains a one-line entry, IS indexed

raw/reference/unsorted/save-the-cat-my-takeaways.md
        ↓ pipeline → processed/ (extraction pending) → !review → knowledge/
knowledge/principles/save-the-cat-beats.md       ← your interpretation, IS indexed
```

The user (or the agent during review) writes a **companion note** that captures *the rules as the user understands them*, in the user's own words. The note is what the AI reads daily. The original book stays in `assets/` and is consulted on demand when the user needs an exact quote or page reference.

### When the agent processes a long reference book in review

If a book ends up in `review/needs-ai-decision/`, the agent should:

1. **Check copyright/length first.** If the file is the full text of a copyrighted book, do NOT extract its prose into `knowledge/`. Instead:
   - Confirm the original is in `assets/`
   - Describe the book in its `assets-index/documents.md` entry (the pipeline created the entry)
   - Ask the user: *"Would you like me to draft a 'takeaways for you' note based on this book? I'll keep it to your own words and reference the source."*
2. **If yes, draft the takeaway note.** 5-15 bullet points or short paragraphs in `knowledge/principles/<book-slug>-takeaways.md`. Cite the source via frontmatter `source:` and span citations (see `11_PROVENANCE.md`).
3. **Maintain a bookshelf index.** For roles where this happens repeatedly (writer, researcher, programmer reading textbooks, founder reading business books), keep `knowledge/principles/<role>-bookshelf.md` as a one-line catalog of every reference book + a link to the takeaway note + a status flag (`read` / `partially read` / `to read`).
4. **Record the result** with `--mark-extracted … --to <takeaways page>` or `--mark-skipped … --reason "reference only"`.

### When extraction IS appropriate

- **Public-domain books** (out of copyright)
- **Open licenses** (CC-BY, etc.) — original text is safe to extract
- **Excerpts within fair use** (a paragraph, not a chapter) — already handled via the `influences` artifact pattern
- **The user's own writing** — drafts, manuscripts, published work they own

### Quick decision tree

```
File in raw/documents/unsorted/ is detected as a long PDF/EPUB/DOCX
      ↓
Is it a copyrighted book the user did not write?
      ├─ Yes → asset stays in assets/, agent offers to write a takeaway note
      └─ No  → standard review: extract into knowledge/, then --mark-extracted
```
