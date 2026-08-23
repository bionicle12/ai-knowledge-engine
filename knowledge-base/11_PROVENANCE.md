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
source_hash: "sha256:a1b2c3d4e5f6"       # SHA-256 of the original (16 chars)
extracted_at: 2026-05-06
last_verified: 2026-05-06
confidence: high                           # high | medium | low
verification_method: "ai-review"           # manual-review | ai-review | auto-extract
extraction_model: "claude-opus-4"          # which model extracted
lifecycle: "evolving"                      # permanent | evolving | temporal
importance: 8                              # 1-10, value score (see below)
valid_from: 2026-05-06                     # when the fact became true
valid_until: null                          # null = current; date = stale from this point
last_accessed: 2026-05-06                  # updated on every AI read
access_count: 0                            # access counter
tags: [strategy, growth]
supersedes: null
citations:                                 # span-level citations
  - claim: "Redis handles 100k ops/s on our profile"
    source_span: "assets/documents/2026-05-06__bench.pdf#page=3&para=2"
    confidence: high
  - claim: "DragonflyDB is 25x faster than Redis"
    source_span: "assets/documents/2026-05-06__dragonfly-bench.md#L15-L28"
    confidence: medium
    note: "Synthetic-load benchmark"
context_annotations: []                    # note evolution from related new knowledge
---
```

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

- **On auto-extract:** the LLM scores at ingest: "How important is this for long-term work? 1 = routine, 10 = key insight"
- **On manual review:** the user can override
- **On query-writeback:** the AI scores based on the number of synthesized sources

### How it is used

- **Routing:** during dynamic context loading the AI prefers high-importance pages
- **Reflection trigger:** when `sum(importance)` of recent N ingests > threshold → automatic reflection (see `07_INTERACTION_LOOP.md`)
- **Lint:** suggests archiving `importance < 3` + `lifecycle: temporal` + `last_accessed > 90 days`
- **Context budget:** when context is tight — low-importance items are dropped first

---

## Access tracking — recency of access

### Recency decay

When a `knowledge/` page actually influenced an answer, the agent "freshens" it:

```yaml
last_accessed: 2026-05-06    # date of last read
access_count: 12             # how many times read
```

### Update

- **AI agent:** update `last_accessed` and `access_count += 1` only when the
  page actually influenced the answer — not on every glance or pack load
- **Python script:** during reindex can compute `recency_score` for sorting

### Recency score

```python
import math
from datetime import datetime

def recency_score(last_accessed: str, decay_factor: float = 0.995) -> float:
    """Exponential decay: 0.995^(hours since last access)."""
    last = datetime.fromisoformat(last_accessed)
    hours = (datetime.now() - last).total_seconds() / 3600
    return decay_factor ** hours
```

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

- `valid_from` is set at ingest (the original date or `extracted_at`)
- `valid_until` is filled when the fact **is updated or replaced**
- For "what was true in February?" the AI filters by `valid_from <= feb AND (valid_until IS NULL OR valid_until > feb)`
- Files with `valid_until != null` **are not deleted** — that is history
- Lint treats files with `valid_until != null` as **not stale** (already marked historical)

---

## Lifecycle: knowledge lifespan

### Types

| Type | Meaning | Lint behavior | Examples |
|------|---------|---------------|----------|
| `permanent` | **Immutable** — does not age, does not degrade | Lint **never** suggests update/delete/archive | Song lyrics, writing voice, personal principles, creative works, profile |
| `evolving` | **Evolving** — refreshed as reality changes | Lint warns about staleness, suggests updates | Tech stack, architectural decisions, market data |
| `temporal` | **Temporary** — bound to a specific period | Lint suggests archive/update once expired | Quarterly strategies, current metrics, ongoing tasks |

**Default:** if `lifecycle` is not set — treated as `evolving`.

### Examples by category

```yaml
# knowledge/voice/songwriting-style.md — voice does not "age"
lifecycle: "permanent"

# knowledge/profile/expertise.md — expertise is foundational
lifecycle: "permanent"

# knowledge/domain/tech-stack.md — stack can change
lifecycle: "evolving"

# knowledge/decisions/2026-q1__pricing.md — bound to Q1
lifecycle: "temporal"
```

---

## Data preservation guarantees

### Never automatically removed

1. **Any files in `knowledge/`** — no module deletes files
2. **Files with `lifecycle: permanent`** — protected from all staleness lint warnings
3. **Originals in `assets/`** — immutable, untouched
4. **Files in `raw/`** — moved to assets at ingest, but not deleted before confirmation

### What lint does for each lifecycle

| Lint action | `permanent` | `evolving` | `temporal` |
|-------------|------------|-----------|-----------|
| Stale warning (last_verified > 30d) | ❌ skipped | ✅ warned | ✅ warned |
| Confidence degradation (>90d) | ❌ no decay | ✅ high→medium | ✅ high→medium→low |
| Suggest archive | ❌ never | 🟡 only if superseded | ✅ if expired |
| Suggest deletion | ❌ never | ❌ never | ❌ never |
| Broken wikilink check | ✅ checked | ✅ checked | ✅ checked |
| Source hash check | ❌ skipped | ✅ checked | ✅ checked |

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

---

## Source hash

```python
import hashlib

def compute_source_hash(filepath: str) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()[:16]}"
```

**Hash mismatch** = original was updated, knowledge was not → `⚠️ STALE SOURCE` in lint-report.
**Exception:** `lifecycle: permanent` — hash mismatches are skipped.

---

## Regression tests: `knowledge/_tests/assertions.yml`

```yaml
assertions:
  - id: "tech-stack-db"
    claim: "Primary DB is PostgreSQL 16"
    expected_in: "knowledge/domain/database.md"
    pattern: "PostgreSQL 16"
    severity: error

  - id: "cache-layer"
    claim: "Cache layer is DragonflyDB"
    expected_in: "knowledge/domain/caching.md"
    pattern: "DragonflyDB"
    severity: error
```

Lint checks assertions on each run. Pattern not found → regression.

---

## Confidence levels

| Level | When | Meaning |
|-------|------|---------|
| `high` | Manual verification, reliable primary source | Fact |
| `medium` | AI extraction without manual verification | Take with caveats |
| `low` | Guess, indirect data, stale source | Re-verify |

**Decay:** `last_verified` > 90 days + `confidence: high` → lint downgrades to `medium`.
**Exception:** `lifecycle: permanent` — confidence does **not** decay over time.

---

## Integration

- **03_PIPELINE:** ingest writes `source_hash`, initial confidence and lifecycle
- **04_REVIEW:** AI review adds citations and decides lifecycle on extraction
- **09_LINT:** checks hash mismatch, citation validity, assertions — lifecycle-aware
- **10_LOG:** provenance operations are recorded in the log
