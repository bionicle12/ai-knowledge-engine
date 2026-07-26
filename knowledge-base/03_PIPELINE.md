# 03 — Python pipeline contract

> Specification of `scripts/kb_ingest.py` — the script that processes raw materials.
>
> **Reference implementation:** `knowledge-base/scripts/kb_ingest.py` (+ shared utilities in `kb_common.py`).
> When deploying, the agent **copies these files** rather than writing them from scratch.
> The contract below describes what the script should do; the implementation already matches.

---

## Purpose

`kb_ingest.py` does not have to be smart. Its job is **safe mechanics**: find files, detect type, convert to text, move originals, and route complex things to review.

## Input

Scans every directory under `raw/**/unsorted/`.

Files attached/uploaded in chat are not pipeline input until the user confirms they should be added to the main knowledge base and the AI agent stages them into the best matching `raw/<category>/unsorted/` folder.

## Per-file processing

1. Detect file type (extension + magic bytes)
2. Rename to a stable format: `YYYY-MM-DD__short-slug.ext`
   - If the date is unknown: `unknown-date__short-slug.ext`
3. Move the original to `assets/<type>/`
4. Compute the `source_hash` of the original (SHA-256, see `11_PROVENANCE.md`)
5. Convert to text/markdown when possible
6. **NLP enrichment** (see `12_NLP_PREPROCESS.md`):
   - NER (spaCy) → entities
   - Keyword extraction (RAKE + KeyBERT) → keywords
   - Entity resolution → linkage to existing `knowledge/` pages
   - Complexity estimation → score 0.0–1.0
   - Result → `processed/nlp-meta/<slug>.yml`
7. **Surprise filter** (mode-aware, see `07_INTERACTION_LOOP.md`):
   - `mode: default` → Python NLP entity overlap ≥80% → "not a surprise" (0 tokens)
   - `mode: super` → AI semantic analysis of **every** ingest (~2–5K tokens): "is this fact predictable from the base?" + contradiction detection
8. **Importance scoring** (mode-aware):
   - `mode: default` → LLM scores value 1–10 (~500 tokens)
   - `mode: super` → LLM scores 1–10 **with rationale** + suggested routing (~1–2K tokens)
9. Create a metadata file (YAML) — including source_hash, NLP data, importance, valid_from
10. **Routing by complexity:**
    - `complexity < threshold` → `processed/<format>/` (auto-processed)
    - `complexity >= threshold` → `review/needs-ai-decision/` (with review package + NLP meta)
11. Sensitive materials → `review/needs-redaction/`
12. Update `assets-index/<type>.md`
13. **Append to `log.md`** (see `10_LOG.md`) — including importance for the reflection trigger

## Conversion matrix

| Type | Handling | Output |
|------|----------|--------|
| `.md`, `.txt` | direct read | `processed/markdown/` |
| `.rtf` | `striprtf` | `processed/markdown/` |
| `.docx` | `python-docx` or `pandoc` | `processed/markdown/` |
| `.pdf` | `pypdf`, `pdftotext`, OCR fallback | `processed/markdown/` or `processed/ocr/` |
| `.pptx` | `python-pptx` | `processed/markdown/` |
| `.xlsx`, `.csv` | `pandas`, `openpyxl` | `processed/tables/` |
| audio: `.mp3` `.wav` `.m4a` `.flac` `.ogg` `.aac` `.opus` … | STT via `kb_stt.py` (faster-whisper, **no system ffmpeg**) | `processed/transcripts/` |
| video: `.mp4` `.mov` `.webm` `.mkv` `.avi` `.m4v` … | STT via `kb_stt.py` (audio stream decoded by PyAV) | `processed/transcripts/` |
| images/scans: `.png` `.jpg` `.webp` `.tiff` `.bmp` | OCR via `kb_ocr.py` (RapidOCR, no system deps) | `processed/ocr/` |
| chat exports | custom parsers | `processed/markdown/` + possibly `review/needs-redaction/` |
| `.zip`, `.tar`, `.tar.gz` | unpack into `raw/unsorted/` for re-ingestion | `processed/markdown/` (listing) |

STT/OCR run automatically **when `pip install -r requirements-media.txt` has been
done** (see `01_PREREQUISITES.md` and `15_MEDIA_PROCESSING.md`). They degrade
gracefully: if no backend is available, the file is routed to
`review/needs-ai-decision/` with an OS-specific install hint inlined in the
review package — the agent should surface that hint, **not** blindly invoke
`ffmpeg`.

## Metadata format

For every processed file, `processed/extracted-metadata/YYYY-MM-DD__slug.yml` is created:

```yaml
original_filename: "Q2 Strategy Draft v3.docx"
stable_filename: "2026-05-06__q2-strategy-draft.docx"
asset_path: "assets/documents/2026-05-06__q2-strategy-draft.docx"
processed_path: "processed/markdown/2026-05-06__q2-strategy-draft.md"
source_hash: "sha256:a1b2c3d4e5f6"
file_type: "docx"
detected_content_type: "strategy"
processing_date: "2026-05-06T10:30:00"
confidence: "medium"
importance: 7                      # 1-10, LLM-assigned
valid_from: "2026-05-06"           # when the fact became true
lifecycle: "evolving"              # permanent | evolving | temporal
complexity: 0.72
is_surprise: true                  # false = predictable from the base; suggest context_annotations
surprise_engine: "python"          # python | ai (driven by mode in kb.config.yml)
importance_reasoning: null         # null in default; rationale string in super
nlp_meta_path: "processed/nlp-meta/2026-05-06__q2-strategy-draft.yml"
needs_ai_review: true
review_reason: "complexity >= threshold (0.72 >= 0.7)"
```

## assets-index entry format

When processing — update `assets-index/<type>.md`:

```markdown
## 2026-05-06__q2-strategy-draft.docx

- Type: document
- Original: assets/documents/2026-05-06__q2-strategy-draft.docx
- Conversion: processed/markdown/2026-05-06__q2-strategy-draft.md
- Summary: Draft Q2 growth strategy — channels, hypotheses, budget
- Extracted knowledge:
  - knowledge/domain/growth-channels.md
  - knowledge/decisions/2026-05-06__q2-budget-shift.md
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All files processed |
| `1` | Some files failed (listed on stderr) |
| `2` | Environment error (missing dependency) |

## Idempotency

Re-running on already-processed files must be safe — skip or update metadata, but never duplicate files in `assets/`.

## AI review triggers

A file is routed to `review/needs-ai-decision/` if it:

- Contains strategic decisions or hypotheses
- Is a long chat export (> 500 lines)
- Is a meeting/call transcript
- Is a high-value presentation
- Has conflicting claims
- Has ambiguous type detection

---

## Handling long reference materials (books, courses, manuals)

Some inputs are **long-form reference texts**, not raw notes — published books on writing craft, programming textbooks, business strategy books, research methodology manuals. The pipeline can extract their text, but doing so risks three things:

1. **Token cost:** a 300-page book ≈ 70-90K words. The agent burns ~50-100K tokens trying to summarize it during review.
2. **Copyright greyness:** the full text of a copyrighted book ending up inside `knowledge/` (and from there in the Repomix index) is uncomfortable even for personal use, and dangerous if the base is ever shared.
3. **Voice / style contamination:** for writer or content-creator roles especially, the prose of a famous author inside `voice/` or `principles/` will quietly seep into the AI's tone, displacing the user's own voice.

### Recommended pattern: PDF as reference, notes as knowledge

```
raw/documents/unsorted/Save-the-Cat.pdf
        ↓ pipeline
assets/documents/2026-05-16__save-the-cat.pdf   ← stays here, NOT indexed
assets-index/documents.md                        ← contains a one-line entry, IS indexed

raw/reference/unsorted/save-the-cat-my-takeaways.md
        ↓ pipeline → review (low complexity → auto-extract) → knowledge/
knowledge/principles/save-the-cat-beats.md       ← your interpretation, IS indexed
```

The user (or the agent during review) writes a **companion note** that captures *the rules as the user understands them*, in the user's own words. The note is what the AI reads daily. The original book stays in `assets/` and is consulted on demand when the user needs an exact quote or page reference.

### When the agent processes a long reference book in review

If a book ends up in `review/needs-ai-decision/`, the agent should:

1. **Check copyright/length first.** If the file is the full text of a copyrighted book, do NOT extract its prose into `knowledge/`. Instead:
   - Confirm the original is in `assets/`
   - Add a one-line entry to `assets-index/documents.md` (already done by the pipeline)
   - Ask the user: *"Would you like me to draft a 'takeaways for you' note based on this book? I'll keep it to your own words and reference the source."*
2. **If yes, draft the takeaway note.** 5-15 bullet points or short paragraphs in `knowledge/principles/<book-slug>-takeaways.md`. Cite the source via frontmatter `source:` and span citations (see `11_PROVENANCE.md`).
3. **Maintain a bookshelf index.** For roles where this happens repeatedly (writer, researcher, programmer reading textbooks, founder reading business books), keep `knowledge/principles/<role>-bookshelf.md` as a one-line catalog of every reference book + a link to the takeaway note + a status flag (`read` / `partially read` / `to read`).

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
      └─ No  → standard pipeline (extract → process → review if complex)
```
