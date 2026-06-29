# 06 — AGENTS.md template for the knowledge base

> The AI agent must create `AGENTS.md` at the base root from this template, adapted to the user's role and entities.
>
> **Reference template:** `knowledge-base/templates/AGENTS.md.template` — already contains the full structure with placeholders `{{KB_NAME}}`, `{{PRIMARY_ROLE}}`, `{{PRIMARY_LANGUAGE}}`, `{{KB_INSTRUCTIONS_VERSION}}`. The agent copies and parameterizes it rather than writing from scratch.

---

## Template

```markdown
# AGENTS.md — [Knowledge base name]

## Purpose

Local non-code knowledge base for role: **[user role]**.
Helps the AI agent understand context, thinking style, decisions, expertise, and preferences of the author.

## Context

- Repomix index: `.repomix/output.xml`
- Config: `kb.config.yml`
- Structure: `KNOWLEDGE_STRUCTURE.md`
- Placement examples: `DATA_PLACEMENT_EXAMPLES.md`

## Reading priority

1. `AGENTS.md` (this file)
2. `kb.config.yml` — role, entities, rules
3. `knowledge/profile/` — who the author is, what they do
4. `knowledge/principles/` — how they think and decide
5. `knowledge/voice/` — how they write and speak
6. Other `knowledge/*` — by relevance to the request

## How to use

- Read `.repomix/output.xml` for broad context before strategy, analysis, or planning
- Read specific `knowledge/` files before targeted edits
- Process `review/needs-ai-decision/` — the queue of materials needing semantic analysis
- Useful conclusions from review → clean Markdown in `knowledge/`
- Update `assets-index/` when describing a binary asset

## Chat-attached files

When the user attaches/uploads a file in chat or gives a local path:

1. Treat it as candidate source material, not an automatic ingest
2. Read `DATA_PLACEMENT_EXAMPLES.md` and `KNOWLEDGE_STRUCTURE.md`
3. Summarize what was attached and propose the best destination in `raw/<category>/unsorted/`
4. Ask the user whether to add the file to the main knowledge base; do not stage or ingest it before confirmation
5. After confirmation, copy/move it into the chosen `raw/<category>/unsorted/`; use `raw/unsorted/` only when routing is unclear
6. Run `./shell/reindex.sh` or confirm the watcher processed it; then check `log.md`, `assets-index/`, `processed/`, and `review/`
7. Update existing `knowledge/` pages before creating duplicates; refresh `last_verified`/`valid_until` when the file changes old facts
8. If the file is low-signal, noisy, or irrelevant, ask whether to keep it as an asset, archive it, or ignore it

## Forbidden

- Do not index `raw/`, `assets/`, `review/` directly
- Do not create new folders in `knowledge/` without confirming with the user
- Do not store secrets, tokens, passwords, private keys, banking data
- Do not copy third-party private data into `knowledge/`
- For sensitive material → only `review/needs-redaction/`

## Feedback loop

While working with the user the agent captures conclusions:
- Auto-detects when meaningful material has accumulated
- Writes a session summary into `interactions/sessions/` (with a "Processed materials" section)
- On `!save` — saves immediately

### Commands

| Command | What it does | Cost |
|---------|--------------|------|
| `!save` | Save session summary + enrichment now | ~2K tokens |
| `!reflect` | Run reflection: synthesize insights from accumulated facts | ~15K tokens |
| `!audit` | Run AI base review (lint level 2) | ~50–100K tokens |
| `!review` | Walk through `review/needs-classification/`, `review/needs-ai-decision/`, and `review/needs-redaction/`, process each item, and report what was extracted, redacted, archived, or deferred | ~5–30K tokens |
| `!populate` | Regenerate `DATA_PLACEMENT_EXAMPLES.md` (run `python3 scripts/kb_populate.py --role <role> --kb-root .`) | ~50 tokens |
| `!super` | Toggle mode: default ↔ super | 0 tokens |
| `!super on/off` | Explicitly enable/disable super mode | 0 tokens |
| `!super status` | Show current mode | 0 tokens |

## Knowledge lifecycle

- `knowledge/decisions/` — immutable (log style, do not edit historical entries)
- `knowledge/domain/` — update when underlying data changes
- `knowledge/playbooks/` — update when processes change
- `knowledge/insights/` — synthesis from facts; update on new data
- `knowledge/profile/` — update on professional/career changes
- Outdated knowledge → `knowledge/_archive/` with a note
- Frontmatter `last_verified` — refresh on confirmed accuracy

## Operating mode

At the start of a session **read `mode` in `kb.config.yml`** and apply the corresponding profile from `mode_profiles`.

| Mode | Paradigm | Tokens/day | Use when |
|------|----------|-----------:|----------|
| `default` | Python-first, throttled | ~3-4K | Daily work, limited budget |
| `super` | AI-first, on-demand | ~50-200K+ | Unlimited plan, intensive base build-up |

### default mode
- Surprise filter: Python NLP overlap (0 tok)
- Annotations: Python templates (0 tok)
- Entity resolution: Python fuzzy match (0 tok)
- Reflection: by threshold (≥25) OR weekly + changes
- Lint L2: only on `!audit`
- Review queue: waits for manual processing

### super mode
- Surprise filter: AI semantic per-ingest (~2-5K tok)
- Annotations: AI substantive + suggested edits (~1-3K tok)
- Entity resolution: AI semantic + cross-language (~500-1K tok)
- Reflection: after every significant ingest (importance ≥5)
- Lint L2: auto on every consolidation (24h)
- Review queue: AI auto-processes `review/needs-ai-decision/`

> ⚠️ **Super mode** consumes the maximum possible tokens and can blow through limits. In return — peak speed and learning quality.

## Context budget

Rules for managing context when reading `knowledge/`:

1. **Reading priority:** insights/ → opinions/ → domain/ → playbooks/ → raw facts
   (synthesized → raw; like Hindsight — first "what I think", then "what I know")
2. **Routing first:** always start with the routing table; do not load every domain file
3. **Loading limit:** at most 7 `knowledge/` files in context simultaneously
4. If you have loaded > 5 — stop and reassess: are they all needed?
5. Summarize what you have read before loading the next batch
6. **Ranking:** all else equal, prefer files with high `importance` and recent `last_accessed`
7. **Temporal filter:** when the question is about a specific period — filter by `valid_from`/`valid_until`
8. **Access tracking:** when reading a `knowledge/` file, update `last_accessed` and `access_count += 1`

## Token budget

Depends on `mode` in `kb.config.yml`:

### default mode — at most ~10% of session tokens

- **On ingest:** importance scoring (~500 tok) + review if complex (~5–15K)
- **On query writeback:** 1 call (~3K tok)
- **Surprise filter:** Python-only (0 tok); AI only for >3000 words (max 2/day)
- **Self-editing annotations:** Python-only (0 tok)
- **Reflection / lint L2:** ONLY on `!reflect` / `!audit` or weekly schedule

### super mode — unlimited

- **On ingest:** AI surprise (~2-5K) + AI annotations (~1-3K) + AI entity resolution (~1K) + importance with reasoning (~1-2K)
- **On query writeback:** 1 call + auto-update of related pages (~5-8K)
- **Surprise filter:** AI for every material, no size/frequency limits
- **Self-editing annotations:** AI substantive + suggested edits
- **Reflection:** after every significant ingest (importance ≥5)
- **Lint L2:** auto on every consolidation
- **Review queue:** auto-processed without waiting for `!audit`

## Language

Primary language: [primary language]. Technical terms, brand names, and product names — keep in original.
```

---

## Adapting to the role

The AI agent must:

1. Replace `[user role]` and `[Knowledge base name]`
2. Add role-specific sections if needed
3. Avoid restating the obvious ("write clean code", "be helpful")
4. Avoid duplicating rules already present in `kb.config.yml`
