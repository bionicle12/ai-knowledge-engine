# Non-Code Knowledge Base — Modular Instructions

> **For:** an AI agent (Codex, Claude, GPT, Cursor) tasked with deploying and maintaining a local knowledge base for a specialist.

## What this is

A set of instructions for building a **Raw-First Knowledge Pipeline** — a system where:

1. The user drops raw materials into `raw/`
2. A Python script converts them, runs NLP enrichment, and writes metadata
3. Every converted file waits for extraction; complex and sensitive ones land in the review queues
4. Clean knowledge with provenance is indexed via Repomix
5. The AI agent learns from each work session via the feedback loop
6. Lint keeps the base healthy; autorun refreshes everything on change

## Reading order

The agent must read modules **strictly in this order**. During deployment they
sit in `setup/`; a deployed base keeps them in `kb-docs/` (copied there in
`02_INIT.md` and by `finalize.sh`), which is where `AGENTS.md` and the scripts
point.

| # | File | What it covers |
|---|------|----------------|
| 0 | `00_OVERVIEW.md` | Deployment map: what to read, what to copy, in what order (read first) |
| 1 | `01_PREREQUISITES.md` | Environment check: Node.js, Python, Git, Repomix; venv at the project root |
| 2 | `02_INIT.md` | Role clarification, entity selection, structure creation, finishing the deployment |
| 3 | `03_PIPELINE.md` | Python pipeline contract: ingest + NLP enrichment + source hash |
| 4 | `04_REVIEW.md` | AI review workflow for complex materials |
| 5 | `05_INDEX.md` | Repomix, `[[wikilinks]]`, routing tables |
| 6 | `06_AGENTS_TEMPLATE.md` | `AGENTS.md` template for the deployed base |
| 7 | `07_INTERACTION_LOOP.md` | Self-learning + Query → Wiki Writeback |
| 8 | `08_PORTABLE.md` | Portability + Dynamic Context Enrichment |
| 9 | `09_LINT.md` | Health check: stale pages, orphans, broken links, contradictions |
| 10 | `10_LOG.md` | Append-only chronology of operations (`log.md`) |
| 11 | `11_PROVENANCE.md` | Source hash, span-level citations, regression tests |
| 12 | `12_NLP_PREPROCESS.md` | NER + keyword extraction + entity resolution before LLM |
| 13 | `13_AUTORUN.md` | File watcher, git hooks, cron — automatic processing |
| 14 | `14_INITIAL_POPULATION.md` | Generate role-specific `DATA_PLACEMENT_EXAMPLES.md` |
| 15 | `15_MEDIA_PROCESSING.md` | Transcription (STT), OCR, archives — out-of-the-box, all platforms |
| 16 | `16_MERGE.md` | Cross-base import/export: merge two deployments without losing knowledge |
| 17 | `17_REFACTOR.md` | Instruction trim: `!refactor`, two-step audit, `--global` report only |
| 18 | `18_HEAL.md` | Catch-up after upgrade: `kb_heal.py`, `!heal`, five stages |

Role configurations: `examples/`.
Templates ready for copy + parameterization: `templates/`.
Reference Python and shell scripts: `scripts/` and `shell/`.

> 🌍 **Russian translation:** `i18n/ru/knowledge-base/README.md` in the engine repository (the full set of Russian translations is under `i18n/ru/` there; drift is tracked in `i18n/TRANSLATION_STATUS.md`).

## Core principles

- **Raw-first:** ingest raw materials first, extract knowledge later
- **Markdown-first:** the LLM reads `.md`, not binary originals
- **Local-first:** processing runs locally via Python + NLP
- **Clean index only:** Repomix indexes only `knowledge/` and `assets-index/`
- **Provenance:** every fact traces back to its source (source hash, span citations)
- **Self-learning:** the base improves through the feedback loop + query writeback
- **Cross-linked:** `[[wikilinks]]` connect knowledge; routing tables scale navigation
- **Auto-maintained:** watchdog + lint + autorun keep the base fresh
- **Privacy-by-default:** raw data and review queues are never indexed

## Quick start for the user

```text
1. Open (or create) the project folder the base should live in
2. Copy this folder (knowledge-base/) into the project root, renamed to setup/
3. Open the project in an IDE with an AI agent (Codex, Cursor, Claude Code, etc.)
4. Tell the agent: "Read setup/README.md and setup/00_OVERVIEW.md, then deploy a
   knowledge base for [my role] inside ./knowledge-base/. When kb_doctor exits 0
   (warnings are fine), run setup/shell/finalize.sh to flatten the base into the
   project root."
5. The agent verifies the environment, asks questions, creates the structure,
   and finalizes it (the base ends up flat in the project root)
6. Start working: drop files into raw/
7. Run watch mode: ./shell/watcher.sh
   (or manually: ./shell/reindex.sh, or the double-click launchers)
```

## User commands

Things you can say to the AI agent in the IDE:

| Command | What it does | Cost | When to use |
|---------|--------------|------|-------------|
| `!status` | Read `STATUS.md` (pending review, extraction backlog, reflection due, heal items, index problems) and say what needs attention | ~0.5K tokens | At the start of a session, or when unsure what to do next |
| `!view` | Start or reopen the local read-only knowledge graph viewer (`!view status` shows the URL, `!view stop` stops it) | 0 tokens | Browse pages, links, metadata, full-text search, and the health panel (orphans, broken links, stale, ambiguous) without AI |
| `!save` | Save a session summary with conclusions and processed materials | ~2K tokens | At the end of a productive session, or when useful conclusions accumulate |
| `!reflect` | Reflect: synthesize higher-level insights from accumulated facts | ~15K tokens | When a lot of new material has been added, or `STATUS.md` says reflection is due |
| `!meta-review` | Analyze saved session summaries that were not reviewed yet: recurring patterns → `interactions/meta-reviews/`, sessions marked `meta_reviewed: true` | ~5–15K tokens | When several sessions have piled up |
| `!audit` | Per-pack L2 review in a fresh session (`.repomix/audit/`) | ~5–20K / pack | Every 2–4 weeks |
| `!profile-review` | Interview `knowledge/profile/` (3 questions at a time) | ~5–15K tokens | When lint warns, or monthly |
| `!quiz` | Five questions about what is already in the base; costliest mistakes first | ~5–15K tokens | When you want the base to exam *you* |
| `!review` | Process the `review/` queues **and** the converted files in `processed/` still waiting for extraction: extract durable knowledge, redact sensitive materials, ask focused questions when input is needed | ~5–30K tokens | When `STATUS.md` shows review or extraction backlog |
| `!populate` | Re-generate `DATA_PLACEMENT_EXAMPLES.md` from the role YAML | ~50 tokens | After editing `examples/<role>.yml` |
| `!export` | Pack this base into a bundle for another machine (`kb_export.py`) | ~100 tokens | Before carrying knowledge to your other machine |
| `!import` | Merge the bundles waiting in `sync/inbox/` (`kb_import.py`) and summarize the report | ~200 tokens | After copying a bundle from the other machine |
| `!merge` | Finish an import: resolve `review/needs-merge/`, check merged pages for contradictions, cross-link, reindex (`16_MERGE.md`) | ~5–30K tokens | After `!import` reports conflicts or new pages |
| `!heal` | Catch up an upgraded base (`kb_heal.py`, `18_HEAL.md`) | ~0–40K tokens | After `kb_upgrade.py`, or when doctor warns about heal |
| `!refactor` | Two-step instruction trim (`17_REFACTOR.md`) | ~5–40K tokens | When lint warns `agents-bytes` / stale `instructions_review`, or after a model change |
| `!super on/off` | Explicitly enable/disable super mode | 0 tokens | See below |
| `!super status` | Show the current mode | 0 tokens | Quick check |

### When it makes sense

- **`!status`** — first thing in a session; it runs `python3 scripts/kb_status.py`, which rewrites `STATUS.md` from the current state and prints it
- **`!view`** — whenever you want to browse what is already in `knowledge/` or triage base health: the health chips + fix queue list every orphan, broken link, stale (same rule as `kb_lint`), or ambiguous page with its source line and an "open file" button; full-text search, 1–3-hop focus, shortest path between two pages, and shareable URL state are built in
- **`!save`** — after any productive 45+ minute session where you discussed documents, made decisions, or analyzed data
- **`!reflect`** — after a series of additions to the base (5+ new pages), before a major strategic decision, or when the system itself says "time"
- **`!audit`** — when you haven't checked the base in a while (2+ weeks), or before large work, to ensure the context is clean
- **`!quiz`** — when you want the base to exam you on what it already holds (costliest mistakes first)

### When it doesn't make sense

- **`!save`** — if the session was trivial (simple questions, no new data)
- **`!reflect`** — if nothing has changed since the last reflection. The system checks this automatically and skips
- **`!audit`** — if the base is small (< 20 pages) or freshly created — no contradictions yet

## Operating modes

The system supports two modes, toggled with `!super` (stored in `knowledge_base.mode`):

| Mode | Paradigm | Tokens/day | Best for |
|------|----------|-----------:|----------|
| `default` | Python-first, throttled | ~3-4K | Limited budget, daily work |
| `super` | AI-first, on-demand | ~50-200K+ | Unlimited plan, intensive learning |

**default** leaves the routine work to Python (NLP enrichment, entity matching, lint) and asks the agent for reflection and audit on a schedule.

**super** tells the agent to spend tokens freely: substantive annotations and semantic entity checks when it writes pages, importance with reasoning, reflection as soon as a little has changed, and `!review` offered at session start when `review/needs-ai-decision/` has items (it starts after the owner's yes). The scripts change only the reflection trigger; the rest is agent behavior read from `mode_profiles.super` in `kb.config.yml`.

> ⚠️ **Super mode** can drain a daily token budget in a single active session. Use only with unlimited AI plans.

### What runs automatically, and who does it

| What | Who | default | super |
|------|-----|---------|-------|
| NLP enrichment (entities, keywords) | `kb_ingest.py`, every ingest | spaCy + RAKE (KeyBERT when installed), 0 tokens | same |
| Entity matching with existing pages | `kb_ingest.py` | Python fuzzy match, 0 tokens | same; the agent double-checks while reviewing |
| Importance score (1–10) | the agent, when it writes a page | score only | score + reasoning |
| Annotations | the agent, when it writes a page | brief | substantive |
| Reflection trigger | `kb_reflect.py`, checked by every reindex; `STATUS.md` then says "reflection due" | importance sum ≥ 25, or any change once 7 days passed since the last reflection (or deployment) | importance sum ≥ 5, no minimum interval; still skipped when nothing changed |
| Lint L1 (Python) | `kb_lint.py`, run by reindex and the watcher | 0 tokens | 0 tokens |
| Lint L2 (contradictions) | the agent | on `!audit` | daily, while the agent is in session |
| Review queue | the agent | on `!review` | on `!review`, offered at session start for `needs-ai-decision` |
| Surprise filter | — | not implemented yet (every ingest counts) | not implemented yet |
