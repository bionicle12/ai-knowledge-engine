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
| `.docx` | `python-docx` or `pandoc` | `processed/markdown/` |
| `.pdf` | `pypdf`, `pdftotext`, OCR fallback | `processed/markdown/` or `processed/ocr/` |
| `.pptx` | `python-pptx` | `processed/markdown/` |
| `.xlsx`, `.csv` | `pandas`, `openpyxl` | `processed/tables/` |
| `.mp3`, `.wav`, `.mp4` | `ffmpeg` + STT (if available) | `processed/transcripts/` |
| `.png`, `.jpg`, scans | OCR (if `tesseract` is available) | `processed/ocr/` |
| chat exports | custom parsers | `processed/markdown/` + possibly `review/needs-redaction/` |
| `.zip`, `.tar.gz` | unpack | `review/needs-classification/` |

If STT or OCR is unavailable — route to `review/needs-ai-decision/` with a note.

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
