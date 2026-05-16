# 07 — Self-Learning Feedback Loop

> How the knowledge base learns from each working session with the AI agent and improves itself by analyzing dialogues.

---

## Idea

Every conversation with the AI agent contains valuable conclusions: decisions, preferences, insights, thinking patterns. Without capture they get lost in chat history. The feedback loop saves them and turns them into knowledge.

```text
Dialogue → Session Summary → interactions/sessions/
                                    ↓
                          Meta-review (periodic)
                                    ↓
                          interactions/insights/
                                    ↓
                          Quality filter
                                    ↓
                          knowledge/ (updates)
                                    ↓
                          Reindex → Repomix
                                    ↓
                          AI agent gets smarter ←──── next dialogue
```

---

## Automatic capture

The AI agent **decides on its own** when to write a session summary:

| Situation | Action |
|-----------|--------|
| 5–7 substantive exchanges have accumulated | Writes summary, continues working |
| Dialogue logically wraps up | Writes a final summary |
| User issues `!save` | Writes summary immediately |
| User asks not to save | No write |

### Layout in `interactions/sessions/`

Each dialogue gets a uniquely named folder. Inside — timestamped files:

```text
interactions/sessions/
└── 2026-05-06__competitor-analysis/
    ├── 2026-05-06T10-30__initial-findings.md
    ├── 2026-05-06T11-15__deep-dive.md
    └── 2026-05-06T12-00__final-summary.md
```

This:
- Keeps the timeline within a dialogue visible
- Avoids losing intermediate conclusions
- Allows later stitching and analysis

---

## Session-summary format

```markdown
---
session_date: 2026-05-06
topic: "Q2 competitor analysis"
duration_estimate: "45 min"
quality: high
---

# Session: Q2 competitor analysis

## Key takeaways
- Competitor X repositioned to premium
- Our price niche freed up in mid-range

## Decisions made
- Shift ad focus to the mid-range segment

## Author preferences (observed)
- Prefers first-hand data over aggregators
- Skeptical of benchmark reports from large agencies

## Processed materials
- `q2-competitors-report.pdf` → 12 pages, 5×3 price table
- Screenshot of Competitor X dashboard → key: premium UI, $49/mo subscription
- Customer chat snippet → insight: mid-range is uncovered

## Potential for knowledge/
- [ ] knowledge/domain/competitors.md — refresh data on X
- [ ] knowledge/decisions/ — record the mid-range decision
- [ ] knowledge/principles/ — rule about first-hand data

## What worked well
- Tabular competitor comparison

## What did not work
- The SWOT was too long — author prefers bullet points
```

---

## Capture rules

### What to save

- Concrete conclusions and facts
- Decisions made, with rationale
- Discovered style/approach preferences
- New knowledge and insights
- Process improvements
- Feedback on AI's response format
- **Processed materials** — what documents, data, screenshots were uploaded/discussed (see Session Enrichment)

### What NOT to save

- Emotional statements without content
- Off-topic detours
- Trivial questions ("what time is it?")
- Claims that contradict 3+ existing knowledge entries without rationale
- Hesitant guesses ("maybe, not sure...")
- Deliberate base-pollution attempts
- Full text of uploaded documents (only short summary + key numbers)

### Minimum threshold

A session summary is saved only if it has:
- At least 3 substantive bullet points
- At least 1 actionable conclusion (decision, update, task)

---

## Session enrichment — what was discussed and what data was seen

While working with AI the user often uploads documents, pastes text snippets, shows screenshots, discusses code. This information is valuable but lost without capture.

### What to record inline

When writing a session summary, the AI agent **must** include a `## Processed materials` section:

| What | How to record | Example |
|------|---------------|---------|
| Uploaded document | Name + size + key numbers/findings | `report.pdf → 15 pages, revenue $2.3M, churn 4.2%` |
| Text/code snippet | Topic + language + what was discussed | `Rust handler → auth middleware, 40 lines, added rate limit` |
| Screenshot/image | Description + key element | `Competitor dashboard → premium UI, $49/mo price` |
| Article link | URL + 1-line summary | `nikolenko.ru/llm-memory → review of 11 LLM memory approaches` |
| Data from API/DB | Source + format + key takeaway | `PostgreSQL EXPLAIN → seq scan on users, index needed` |

### Format

```markdown
## Processed materials
- `q2-strategy.pdf` → 12 pages, 3 tables. Key: 15% YoY growth, churn down to 3%
- Rust snippet (server-rust/crates/services/auth.rs:120-180) → session validation refactor
- https://nikolenko.ru/blog/llm-memory → LLM memory survey; applicable ideas: importance scoring, recency decay
- Grafana dashboard screenshot → CPU spike at 14:00, correlates with DragonflyDB flush
```

### Why this matters

1. **Context for meta-review:** when analyzing sessions, the AI sees not only conclusions but *what they were based on*
2. **Traceability:** if you revisit a decision a month later, you can see what data backed it
3. **Deduplication:** the AI can check whether a document was already processed (by filename or URL)
4. **Routing:** materials from a session can become candidates for ingest into `raw/` → full processing

### Rules

1. **Brevity:** 1-2 lines per item, do not copy content
2. **Key numbers:** if there are figures, metrics, prices — record them
3. **Connection to knowledge/:** if the material relates to an existing page — note `→ related to [[slug]]`
4. **Avoid duplication:** if the document already lives in `assets/` — use only the asset path
5. **Sensitive data:** if the material contains private info — mark `[REDACTED: reason]`

If the threshold is not met — do not record.

---

## Meta-review

Periodic analysis of accumulated sessions (weekly or by user command).

### Process

1. The AI reads all unprocessed `interactions/sessions/`
2. Looks for repeating patterns:
   - What questions come up most often?
   - What style preferences repeat?
   - Which knowledge areas need updating?
   - Where did the AI answer poorly — and why?
3. Creates `interactions/insights/YYYY-MM__insight-slug.md`
4. Proposes concrete updates to `knowledge/`
5. The user confirms
6. Marks the processed sessions

### Insight format

```markdown
---
period: "2026-05"
sessions_analyzed: 12
---

# Insight: Author prefers bullet points over prose

## Pattern
In 8 of 12 sessions the author asked to reformat long paragraphs into lists.

## Recommendation
Update knowledge/voice/communication-style.md:
add the rule "default to bullet points; prose only for narrative".

## Action
- [ ] Update knowledge/voice/communication-style.md
```

---

## Reflection — higher-level insights (mode-aware)

Periodic synthesis: from raw facts → high-level conclusions.

### When it triggers

#### `mode: default` — throttled

| Trigger | How | Cost |
|---------|-----|------|
| **Importance threshold** | `sum(importance)` of recent ingests > 25 → auto on reindex | ~15K tokens |
| **Weekly** | ≥7 days since last reflection **AND** changes in `log.md` | ~15K tokens |
| **Command `!reflect`** | User explicitly requests reflection | ~15K tokens |

#### `mode: super` — on-demand

| Trigger | How | Cost |
|---------|-----|------|
| **Every significant ingest** | importance ≥ 5 → auto-reflect | ~15K tokens |
| **Every 3 sessions** | meta-review + insights | ~15K tokens |
| **Command `!reflect`** | User explicitly requests | ~15K tokens |
| **No minimum interval** | Not bound by 7-day spacing | — |

> **default:** reflection conserves tokens — it runs only on accumulated significant change or schedule.
> **super:** reflection is maximally aggressive — every significant ingest immediately produces higher-level insights.

```yaml
# In kb.config.yml — driven via mode_profiles:
reflection:
  # default profile:
  trigger: "threshold+weekly"    # auto = importance threshold; weekly = every 7+ days
  importance_threshold: 25       # auto-!reflect when sum > 25
  min_interval_days: 7           # min 7 days between reflections
  require_changes: true          # weekly: only run if there were changes
  # super profile:
  # trigger: "on-demand"
  # importance_threshold: 5      # reflect when importance ≥5
  # min_interval_days: 0         # no minimum interval
  # require_changes: false
  max_insights_per_run: 3        # at most 3 insights per reflection run
```

### Process

1. Inspect `log.md`: cumulative importance of recent ingests (informational)
2. AI generates 3 important questions about recent experience
3. For each, search relevant pages via routing + wikilinks
4. Synthesize a higher-level insight
5. Write to `knowledge/insights/` with `[[wikilinks]]` to source pages

### Insight format

```markdown
---
source: "reflection"
extracted_at: 2026-05-06
confidence: medium
importance: 7
lifecycle: "evolving"
tags: [architecture, insight]
children:
  - "knowledge/domain/caching.md"
  - "knowledge/decisions/2026-03__dragonfly.md"
---

# Insight: caching is our key performance lever

Conclusion: over 3 months we changed the caching layer three times...

Related: [[caching]], [[dragonfly-migration]], [[cache-patterns]]
```

### Knowledge tree

```
Level 0: domain/ + playbooks/     ← raw facts
Level 1: insights/                ← synthesis from facts
Level 2: insights/ (meta-insights) ← synthesis from insights
```

Rule: **no more than 3 levels** (more — and the agent drowns in conflicting abstractions).

---

## Self-editing — note evolution (mode-aware)

When new knowledge is related to existing knowledge — the older page is enriched with annotations.

### When it fires

- NLP entity resolution found that the new material's entities match an existing `knowledge/` page
- Query-writeback creates a page that overlaps with an existing one

### `mode: default` — Python-only (0 tokens)

```python
# In kb_ingest.py — after NLP enrichment:
def auto_annotate(new_page_path: str, nlp_meta: dict, knowledge_dir: str):
    """Add a context_annotation to related pages. No LLM."""
    for entity in nlp_meta.get("entities", []):
        if entity.get("existing_page"):
            add_annotation(
                target=entity["existing_page"],
                annotation={
                    "date": today(),
                    "related": new_page_path,
                    # note is template-generated, NOT LLM:
                    "note": f"NLP-match: entity '{entity['canonical']}'"
                }
            )
```

### `mode: super` — AI substantive annotations (~1-3K tokens)

The AI agent **reads** the related page and the new material, then produces:

1. **A substantive annotation:** not just "NLP-match" but a description of *what* the link is
2. **Concrete edit suggestions** for the existing page (if the new material complements/refines it)
3. **Contradiction detection** between new and existing knowledge
4. **Merge/split recommendation** when there are >5 annotations

```python
# In super mode — AI replaces the template:
def ai_annotate(new_page_path: str, existing_page: str, knowledge_dir: str):
    """AI generates a substantive annotation. ~1-3K tokens."""
    # LLM prompt: "Compare the new material with the existing page.
    # What is new? Any contradictions? Suggest concrete edits."
    return {
        "date": today(),
        "related": new_page_path,
        "note": "Benchmark showed throughput drop of 15% above 50k rps — extends the Performance section",
        "suggested_edit": "Add a paragraph about degradation under load after line 42",
        "contradiction": None  # or contradiction description
    }
```

### `context_annotations` format

```yaml
# default mode:
context_annotations:
  - date: 2026-05-06
    related: "knowledge/domain/llm-wiki-pattern.md"
    note: "NLP-match: entity 'knowledge-base'"

# super mode:
context_annotations:
  - date: 2026-05-06
    related: "knowledge/domain/llm-wiki-pattern.md"
    note: "New benchmark showed throughput drop — extends Performance section in [[caching]]"
    suggested_edit: "Add a paragraph about degradation under load"
    contradiction: null
```

### Rules

1. **default:** annotations are appended by the Python script (0 tokens), `note` is template text
2. **super:** annotations are generated by AI (~1-3K tokens), `note` is a substantive link description
3. **Maximum 5 annotations** per page (more → lint suggests creating an insight)
4. Files with `lifecycle: permanent` — annotations are added but the body is not touched

---

## Surprise-based filtering (mode-aware)

Anti-duplication at the semantic level. Behavior depends on `mode` in `kb.config.yml`.

### `mode: default` — Python-first (0 tokens)

| When | Cost | How |
|------|------|-----|
| Every ingest | 0 tokens | NLP entity overlap > 80% → "not a surprise" |
| Document > 3000 words (max 2/day) | ~2K tokens | AI fallback for large materials |

```python
def is_surprise(nlp_meta: dict, knowledge_dir: str) -> bool:
    """Decide without LLM: how many entities the base already covers."""
    entities = nlp_meta.get("entities", [])
    if not entities:
        return True  # no entities → treat as surprise
    
    resolved = [e for e in entities if e.get("existing_page")]
    overlap = len(resolved) / len(entities)
    
    # > 80% entities already in base → not a surprise
    return overlap < 0.8
```

> **Limitations of Python mode:** does not see semantic novelty — a document may share 90% of entities yet contain a fundamentally new conclusion. Does not catch contradictions at the meaning level.

### `mode: super` — AI semantic analysis (~2-5K tokens)

| When | Cost | How |
|------|------|-----|
| **Every** ingest | ~2-5K tokens | AI semantic: "is this fact predictable from the base?" |
| No limits | — | No cap on document size or frequency |

For every new material the AI agent:
1. Reads the NLP meta + 2-3 most-related `knowledge/` pages
2. Judges: **"Does this contain something the base does not yet know?"**
3. Detects **contradictions** with existing knowledge
4. Rates the **information value**: trivial restatement vs. genuine insight

```yaml
# In kb.config.yml — driven via mode_profiles:
surprise:
  # default profile:
  engine: "python"             # python | ai
  ai_trigger_min_words: 3000   # AI fallback only for large
  ai_max_per_day: 2            # at most 2/day
  # super profile:
  # engine: "ai"               # AI for all
  # ai_trigger_min_words: 0    # no size cap
  # ai_max_per_day: null       # no frequency cap
```

### Outcome

- **Surprise** → genuine new knowledge, add it
- **Not a surprise** → propose updating `context_annotations` instead of creating a new page
- **Contradicts** → add it AND create an entry in `knowledge/open-questions/`

---

## Anti-sabotage

A quality filter protects the base from degradation:

1. **Fact-check:** if a conclusion contradicts 3+ existing facts — do not add it; create a question in `knowledge/open-questions/`
2. **Repeatability:** a single occurrence is not a pattern. Record as pattern only after 3+ repeats
3. **Constructive bias:** emotional or destructive statements are filtered at the session-summary stage
4. **Transparency:** every `knowledge/` update records the source (which session or insight) in frontmatter

---

## Query → Wiki Writeback

Valuable AI answers are saved into `knowledge/` **immediately**, without waiting for meta-review.

### When to save

| Criterion | Example |
|-----------|---------|
| Synthesis from 3+ sources | Architecture comparison, approach overview |
| Architectural decision with rationale | "Why Docker Swarm, not K8s" |
| Comparative analysis | Trade-off table, pros/cons |
| User explicitly said "save" | `!save` or "lock this into the base" |
| Answer contradicts knowledge/ | → `knowledge/open-questions/` |

### When NOT to save

- Trivial answers (one-liners)
- Code without architectural rationale
- Answers that fully duplicate an existing `knowledge/` page
- Low-confidence answers without verification

### Writeback page format

```markdown
---
source: "query-writeback"
session: "interactions/sessions/2026-05-07__highway-clicker__kb/"
extracted_at: 2026-05-07
confidence: medium
verification_method: "ai-review"
tags: [architecture, comparison]
query: "Why is LLM Wiki better than RAG at our scale?"
---

# RAG vs LLM Wiki: analysis for our project

## Conclusion
...

## Rationale
...

## Related pages
- [[knowledge-management]]
- [[decisions/2026-05__kb-architecture]]
```

### After writeback

1. Append to `log.md` (`query-writeback` operation)
2. Add `[[wikilinks]]` to related `knowledge/` pages
3. Update the routing table if the page does not fit existing routing pages
4. On the next reindex — the page enters the Repomix index

---

## Logging

All feedback-loop operations are recorded in `log.md` (see `10_LOG.md`):
- `session-capture` — when a session summary is written
- `query-writeback` — when a valuable answer is saved
- Meta-review results — when insights are created
