# 11 — Source provenance: tracing where knowledge comes from

> Every fact in the base must be verifiable. Provenance is the chain from a claim in `knowledge/` back to a specific spot in the original document.

---

## The problem

> *"An LLM Wiki is lossy compression. Summary errors become part of the knowledge base."*

When an LLM extracts knowledge it can simplify nuance, drop caveats, or distort wording. Without provenance there is no way to verify where a claim came from.

---

## Extended frontmatter

```yaml
---
source: "assets/documents/2026-05-06__q2-strategy.pdf"
source_hash: "sha256:a1b2c3d4e5f60718"   # sha256: + first 16 hex chars of the original
extracted_at: 2026-05-06
last_verified: 2026-05-06
confidence: high                         # high | medium | low
verification_method: "ai-review"         # manual-review | ai-review
extraction_model: "claude-opus-4"        # which model extracted
lifecycle: "evolving"                    # permanent | evolving | temporal
importance: 8                            # 1-10, value score (see below)
valid_from: 2026-05-06                   # when the fact became true
valid_until: null                        # null = current; a date = true until then
last_accessed: 2026-05-06                # last time the page influenced an answer
access_count: 0                          # how many answers it influenced
tags: [strategy, growth]
supersedes: null
citations:                               # span-level citations
  - claim: "Redis handles 100k ops/s on our profile"
    source_span: "assets/documents/2026-05-06__bench.pdf#page=3&para=2"
    confidence: high
  - claim: "DragonflyDB is 25x faster than Redis"
    source_span: "assets/documents/2026-05-06__dragonfly-bench.md#L15-L28"
    confidence: medium
    note: "Synthetic-load benchmark"
context_annotations: []                  # note evolution from related new knowledge
---
```

Required on every `knowledge/` page (lint `frontmatter`): `source`, `extracted_at`, `tags`, `lifecycle`. Everything else is optional. Ingest metadata (`processed/extracted-metadata/<name>.yml`) already holds `source_hash`, `extracted_at`, `valid_from`, a default `lifecycle` and `confidence` — copy them into the page you write.

---

## Importance scoring — how valuable is this knowledge

Every fact in `knowledge/` gets an importance score (1-10).

### Scale

| Score | Meaning | Examples |
|-------|---------|---------|
| 1-2 | Routine note | "Bumped a dependency", "configured the linter" |
| 3-4 | Useful knowledge | "Error-handling pattern", "Nginx configuration" |
| 5-6 | Significant knowledge | "Caching-layer architecture", "A/B test results" |
| 7-8 | Key knowledge | "Architecture decision with rationale", "growth strategy" |
| 9-10 | Critically important | "Foundational principle", "key lesson from a failure" |

### Who assigns it

- **At extraction** (`!review`, reflection): the agent scores the page it writes — "How important is this for long-term work? 1 = routine, 10 = key insight". Ingest scores nothing.
- **On query-writeback:** the agent scores based on the number of synthesized sources
- **The owner** can override any score

### How it is used

- **Routing:** during dynamic context loading the AI prefers high-importance pages
- **Reflection trigger:** `kb_reflect.py` weighs every edited page by its `importance` (3 when unset) and every ingest by the `importance` in its metadata (1 when unset); when the sum since the last reflection reaches the profile threshold, a reflection is due (see `kb-docs/07_INTERACTION_LOOP.md`)
- **Lint `low-importance`** (info): `importance` < 3 + effective lifecycle `temporal` + `last_accessed` more than 90 days ago (without `last_accessed`: the newer of `last_verified` / `extracted_at`) → suggests moving the page to `_archive/`
- **Context budget:** when context is tight — low-importance items are dropped first

---

## Access tracking — recency of access

### Recency decay

When a `knowledge/` page actually influenced an answer, the agent "freshens" it:

```yaml
last_accessed: 2026-05-06    # last time the page influenced an answer
access_count: 12             # how many answers it influenced
```

### Update

- **AI agent:** update `last_accessed` and `access_count += 1` only when the
  page actually influenced the answer — not on every glance or pack load
- These two fields are volatile: `!merge` does not count them as a content change

### Recency score

No script computes it; it is a ranking principle for the agent. Exponential
decay: `recency_score = 0.995 ^ (hours since last_accessed)`.

### Routing priority

All else equal, the AI prefers pages with **higher** `importance × recency_score`. Ranking formula (à la Generative Agents):

```
priority = importance/10 + recency_score + relevance_to_query
```

All three components are normalized to 0..1. The AI does not have to compute the formula, but the **principle** is: important + fresh + relevant → read first.

---

## Bi-temporal validity — temporal facts

### Concept (Zep/Graphiti)

Each fact carries two moments:
- `valid_from` — when the fact **became true**
- `valid_until` — when the fact **stopped being true** (`null` = still current)

### Example

```yaml
# knowledge/decisions/2026-01__redis-cache.md
valid_from: 2026-01-15
valid_until: 2026-03-20       # superseded by DragonflyDB
superseded_by: "knowledge/decisions/2026-03__dragonfly-migration.md"

# knowledge/decisions/2026-03__dragonfly-migration.md
valid_from: 2026-03-20
valid_until: null               # current
```

### Rules

- `valid_from` is set at extraction (the original date or `extracted_at`)
- `valid_until` is filled when the fact **is updated or replaced**
- For "what was true in February?" the AI filters by `valid_from <= feb AND (valid_until IS NULL OR valid_until > feb)`
- Files with `valid_until != null` **are not deleted** — that is history
- **Lint:** a page whose `valid_until` is today or later is never `stale` (the fact is known to hold until then). A past `valid_until` does not silence lint: a `temporal` page gets `expired-temporal` until it moves to `_archive/`; any other page follows the normal age rule — archive superseded history, or keep it where it is `permanent` (`decisions/` is, by default)

---

## Lifecycle: knowledge lifespan

### Types

| Type | Meaning | Lint behavior | Examples |
|------|---------|---------------|----------|
| `permanent` | **Immutable** — does not age, does not degrade | Never `stale`, no `source-hash` check, never suggested for archive | Song lyrics, writing voice, personal principles, creative works, profile, decisions |
| `evolving` | **Evolving** — refreshed as reality changes | `stale` after `lifecycle.stale_warning_days` (30) without verification | Tech stack, market data |
| `temporal` | **Temporary** — bound to a specific period | `stale` as above; `expired-temporal` once `valid_until` passes; `low-importance` archive suggestion | Quarterly strategies, current metrics, ongoing tasks |

**Effective lifecycle.** A page's own `lifecycle` wins when it is set to something other than `lifecycle.default` (`evolving`). A missing or default value yields to the folder policy `lifecycle.by_folder` in `kb.config.yml` — by default `decisions/`, `profile/` and `principles/` are `permanent` — and otherwise to `lifecycle.default`. Lint and the graph viewer use the same rule (`kb_common.stale_status`).

### Examples by category

```yaml
# knowledge/voice/songwriting-style.md — voice does not "age"
lifecycle: "permanent"

# knowledge/profile/expertise.md — permanent by folder policy,
# even with the template default:
lifecycle: "evolving"

# knowledge/domain/tech-stack.md — stack can change
lifecycle: "evolving"

# knowledge/decisions/2026-q1__pricing.md — bound to Q1; an explicit
# non-default value beats the folder policy
lifecycle: "temporal"
```

---

## Data preservation guarantees

### Never automatically removed

1. **Pages in `knowledge/`** — no script deletes a page the owner or the agent wrote. The one exception is generated: `kb_route.py` removes its own `knowledge/routing/<section>.md` (`generated_by: kb_route.py`) when that section no longer exists. `kb_import.py` may rewrite a page during a merge, after a backup (see `kb-docs/16_MERGE.md`)
2. **Files with effective lifecycle `permanent`** — protected from all staleness lint warnings
3. **Originals in `assets/`** — immutable, untouched
4. **Files in `raw/`** — ingest removes a file from `unsorted/` only after its copy in `assets/` and every derived file are written (a failed file stays); an exact duplicate moves to `ingest.duplicates_dir` (`raw/_duplicates/`); ignored, empty and too-large files are left where they are

### What lint does for each lifecycle

| Lint check (`kb-docs/09_LINT.md`) | `permanent` | `evolving` | `temporal` |
|-------------|------------|-----------|-----------|
| `stale` (older than `stale_warning_days`, default 30) | ❌ skipped | ✅ warned | ✅ warned |
| `expired-temporal` (`valid_until` < today, not in `_archive/`) | — | — | ✅ warned |
| `low-importance` (archive suggestion) | — | — | ✅ info |
| `superseded` (A `supersedes` B, B not in `_archive/`) | ❌ skipped | ✅ warned | ✅ warned |
| `broken-link` | ✅ checked | ✅ checked | ✅ checked |
| `source-hash` | ❌ skipped | ✅ checked | ✅ checked |
| `citation` (the span's file exists; `#Lx-Ly` ends inside it) | ✅ checked | ✅ checked | ✅ checked |

Lint never changes `confidence`, never moves and never deletes a page. `--fix` only adds missing frontmatter fields.

### Rule: archive only, never delete

Removing a file from `knowledge/` is **manual only**.

The AI agent **may suggest:**
- Archive (`knowledge/` → `knowledge/_archive/`) — for temporal/evolving
- Merge — for evolving with duplicates
- Update — for evolving with stale data

The AI agent **cannot:**
- Delete a file from `knowledge/`
- Change `lifecycle` without an explicit user request
- Downgrade lifecycle (`permanent` → `evolving`)
- Archive `permanent` files

---

## Span-link formats

| Format | When |
|--------|------|
| `file.pdf#page=3&para=2` | PDF documents |
| `file.md#L15-L28` | Markdown/text (lines) |
| `file.docx#section=3` | DOCX by section |
| `transcript.md#T00:15:30-T00:16:45` | Transcripts by timecode |

Lint `citation` checks that the file of every `source_span` exists inside the base; for `#Lx-Ly` also that the span ends within the file. The other formats are not parsed.

---

## Source hash

`kb_common.compute_source_hash()`: SHA-256 of the file's bytes, written as `sha256:` + the first 16 hex characters. Ingest records it in the metadata; copy it into the page's `source_hash`.

**Hash mismatch** = the original was updated, the knowledge was not → lint `source-hash` error (a missing source file is a warning). Hashes are cached in `.kb-state/lint-hash-cache.json` and recomputed only when the file's size or modification time changes.
**Exception:** effective lifecycle `permanent` — not checked.

A new version of an ingested document (same original name dropped at the same `raw_path` — same category and subfolder — with other content) is ingested as a new asset with `previous_version` in its metadata; its review package lists the pages citing the old version so the agent can move their `source` / `source_hash` over.

---

## Regression check: `eval/QUESTIONS.md`

There is no automatic assertion file. The regression measure is manual: `eval/QUESTIONS.md` holds three typical owner questions with the pages each answer must cite. It is answered in a fresh session before and after instruction changes — see `kb-docs/17_REFACTOR.md`.

---

## Confidence levels

| Level | When | Meaning |
|-------|------|---------|
| `high` | Manual verification, reliable primary source | Fact |
| `medium` | AI extraction without manual verification | Take with caveats |
| `low` | Guess, indirect data, stale source | Re-verify |

**Decay (agent rule):** when `last_verified` is older than `lifecycle.confidence_decay_days` (default 90), treat `confidence: high` as `medium` in answers; after re-verifying, update `last_verified` (and `confidence` if it changed). No script rewrites `confidence`.
**Exception:** `lifecycle: permanent` — confidence does **not** decay over time.

---

## Integration

- **03_PIPELINE:** ingest metadata carries `source_hash`, `valid_from`, the default `lifecycle` and `confidence`
- **04_REVIEW:** the agent writes the page — citations, `importance`, the lifecycle decision
- **09_LINT:** `source-hash`, `citation`, `stale`, `expired-temporal`, `superseded`, `low-importance` — lifecycle-aware
- **10_LOG:** provenance operations (`review`, `query-writeback`, `archive`) are recorded in the log
