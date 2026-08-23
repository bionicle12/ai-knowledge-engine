# 06 — AGENTS.md template for the knowledge base

> The AI agent must create `AGENTS.md` at the base root from this template, adapted to the user's role and entities.
>
> **Reference template:** `knowledge-base/templates/AGENTS.md.template` — already contains the full structure with placeholders `{{KB_NAME}}`, `{{PRIMARY_ROLE}}`, `{{PRIMARY_LANGUAGE}}`, `{{KB_INSTRUCTIONS_VERSION}}`. The agent copies and parameterizes it rather than writing from scratch.
>
> **Ownership after deployment:** `AGENTS.md` belongs to the base, not to the
> engine. Agents evolve it while working; upgrades (`kb_upgrade.py`) maintain
> the managed `AI-KE:INDEX` and `AI-KE:VIEW` blocks and **never overwrite a
> block with local edits** — they write a `.new` sidecar and ask an AI agent
> to merge (see `docs/UPGRADING.md`). `AI-KE:INVARIANT` blocks (`forbidden`,
> `language`) are never auto-written or overwritten; missing wrappers are a
> lint error and an assisted heal step. No script may replace this file
> wholesale. To shrink it, use `!refactor` (`17_REFACTOR.md`) — two steps,
> owner decisions, eval before/after. Do not grow it by restating
> `kb.config.yml` or `mode_profiles`.

---

## Template

```markdown
# AGENTS.md — [Knowledge base name]

## Purpose

Local non-code knowledge base for role: **[user role]**.
Helps the AI agent understand context, thinking style, decisions, expertise, and preferences of the author.

## Context

- Repomix packs: `.repomix/*.xml`, fresh sizes in `.repomix/PACKS_STATUS.md`
- Routing map: `knowledge/routing-table.md`
- Config: `kb.config.yml` (`index:` section controls the packs)
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

- **Never read a full-base index dump.** Load the `core` pack plus AT MOST ONE
  domain pack per task (routing: `knowledge/routing-table.md` →
  `.repomix/PACKS_STATUS.md`). Library/reference packs — only when the task
  is about that material.
- Read specific `knowledge/` files before targeted edits
- **Lost the thread mid-session?** Re-read `knowledge/routing-table.md` and
  `.repomix/PACKS_STATUS.md` (both tiny), then reload only the one pack the
  current question needs — never re-read everything you already saw.
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

Write a session summary into `interactions/sessions/` on `!save` or when the
user explicitly asks to save. Do not invent a write because "enough material
has accumulated".

### Commands

| Command | What it does | Cost |
|---------|--------------|------|
| `!view` | Start or reopen the local read-only knowledge graph viewer | 0 tokens |
| `!save` | Save session summary + enrichment now | ~2K tokens |
| `!reflect` | Run reflection: synthesize insights from accumulated facts | ~15K tokens |
| `!audit` | Per-pack L2 review — `.repomix/audit/<pack>__request.md`, new session | ~5–20K / pack |
| `!review` | Walk through `review/needs-classification/`, `review/needs-ai-decision/`, and `review/needs-redaction/`, process each item, and report what was extracted, redacted, archived, or deferred | ~5–30K tokens |
| `!populate` | Regenerate `DATA_PLACEMENT_EXAMPLES.md` (run `python3 scripts/kb_populate.py --role <role> --kb-root .`) | ~50 tokens |
| `!heal` | Catch up after an upgrade — `18_HEAL.md` | ~0–40K tokens |
| `!refactor` | Two-step instruction trim — `17_REFACTOR.md`. `--global` reports only | ~5–40K tokens |
| `!profile-review` | Interview `knowledge/profile/` (3 questions at a time) | ~5–15K tokens |
| `!quiz` | Five questions about what is already in the base; costliest mistakes first | ~5–15K tokens |
| `!super` | Toggle mode: default ↔ super | 0 tokens |
| `!super on/off` | Explicitly enable/disable super mode | 0 tokens |
| `!super status` | Show current mode | 0 tokens |

Graph, sync, and heal are the scripts — do not rebuild the graph or invent
export/import/merge mechanics with AI.

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

> ⚠️ **Super mode** consumes the maximum possible tokens and can blow through limits. In return — peak speed and learning quality.

Token numbers live in `kb.config.yml` `mode_profiles` — do not restate them here.

## Context budget

Rules for managing context when reading `knowledge/`:

1. **Reading priority:** insights/ → opinions/ → domain/ → playbooks/ → raw facts
   (synthesized → raw; like Hindsight — first "what I think", then "what I know")
2. **Routing first:** always start with the routing table; do not load every domain file
3. **Loading limit:** at most 7 `knowledge/` files in context simultaneously
4. Summarize what you have read before loading the next batch
5. **Ranking:** all else equal, prefer files with high `importance` and recent `last_accessed`
6. **Temporal filter:** when the question is about a specific period — filter by `valid_from`/`valid_until`
7. **Access tracking:** update `last_accessed` and `access_count += 1` only when the page actually influenced the answer — not on every glance

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
