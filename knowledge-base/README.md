# Non-Code Knowledge Base — Modular Instructions

> **For:** an AI agent (Codex, Claude, GPT, Cursor) tasked with deploying and maintaining a local knowledge base for a specialist.

## What this is

A set of instructions for building a **Raw-First Knowledge Pipeline** — a system where:

1. The user drops raw materials into `raw/`
2. A Python script converts them, runs NLP enrichment, and writes metadata
3. Complex materials land in the AI review queue
4. Clean knowledge with provenance is indexed via Repomix
5. The AI agent learns from each work session via the feedback loop
6. Lint keeps the base healthy; autorun refreshes everything on change

## Reading order

The agent must read modules **strictly in this order**:

| # | File | What it covers |
|---|------|----------------|
| 0 | `00_OVERVIEW.md` | Deployment map: what to read, what to copy, in what order (read first) |
| 1 | `01_PREREQUISITES.md` | Environment check: Node.js, Python, Git, Repomix |
| 2 | `02_INIT.md` | Role clarification, entity selection, structure creation |
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

Role configurations: `examples/`.
Templates ready for copy + parameterization: `templates/`.
Reference Python and shell scripts: `scripts/` and `shell/`.

> 🌍 **Russian translation:** [`i18n/ru/knowledge-base/README.md`](../i18n/ru/knowledge-base/README.md). The full set of Russian translations is under `i18n/ru/`.
> Drift between languages is tracked in `i18n/TRANSLATION_STATUS.md`.

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
1. Create an empty project folder
2. Copy this folder (knowledge-base/) into the project root
3. Open the project in an IDE with an AI agent (Codex, Cursor, etc.)
4. Tell the agent: "Read knowledge-base/README.md and deploy a knowledge base for [my role]"
5. The agent verifies the environment, asks questions, creates the structure
6. Start working: drop files into raw/
7. Run watch mode: ./shell/watcher.sh
   (or manually: ./shell/reindex.sh)
```

## User commands

Things you can say to the AI agent in the IDE:

| Command | What it does | Cost | When to use |
|---------|--------------|------|-------------|
| `!view` | Start or reopen the local read-only knowledge graph viewer | 0 tokens | Browse pages, links, metadata, and diagnostics without AI |
| `!save` | Save a session summary with conclusions and processed materials | ~2K tokens | At the end of a productive session, or when useful conclusions accumulate |
| `!reflect` | Reflect: synthesize higher-level insights from accumulated facts | ~15K tokens | When a lot of new material has been added |
| `!audit` | AI review of the base: contradictions, gaps, merge candidates | ~50–100K tokens | Every 2–4 weeks |
| `!review` | Process `review/` queues, extract durable knowledge, redact sensitive materials, and ask focused questions when input is needed | ~5–30K tokens | When `review/needs-ai-decision/` starts to accumulate |
| `!populate` | Re-generate `DATA_PLACEMENT_EXAMPLES.md` from the role YAML | ~50 tokens | After editing `examples/<role>.yml` |
| `!super` | Toggle mode: default ↔ super | 0 tokens | When you need maximum learning speed |
| `!super on/off` | Explicitly enable/disable super mode | 0 tokens | See below |
| `!super status` | Show the current mode | 0 tokens | Quick check |

### When it makes sense

- **`!view`** — whenever you want to browse what is already in `knowledge/`; use `!view status` to show the URL and `!view stop` to stop the local server
- **`!save`** — after any productive 45+ minute session where you discussed documents, made decisions, or analyzed data
- **`!reflect`** — after a series of additions to the base (5+ new pages), before a major strategic decision, or when the system itself says "time"
- **`!audit`** — when you haven't checked the base in a while (2+ weeks), or before large work, to ensure the context is clean

### When it doesn't make sense

- **`!save`** — if the session was trivial (simple questions, no new data)
- **`!reflect`** — if nothing has changed since the last reflection. The system checks this automatically and skips
- **`!audit`** — if the base is small (< 20 pages) or freshly created — no contradictions yet

## Operating modes

The system supports two modes, toggled with `!super`:

| Mode | Paradigm | Tokens/day | Best for |
|------|----------|-----------:|----------|
| `default` | Python-first, throttled | ~3-4K | Limited budget, daily work |
| `super` | AI-first, on-demand | ~50-200K+ | Unlimited plan, intensive learning |

**default** uses Python (NLP, heuristics) for the surprise filter, annotations, and entity resolution. Reflection and audit are scheduled.

**super** replaces the Python heuristics with AI analysis: semantic surprise, substantive annotations, on-demand reflection, auto-processed review queue. Maximum speed and quality of learning.

> ⚠️ **Super mode** can drain a daily token budget in a single active session. Use only with unlimited AI plans.

### Automatic triggers (no manual run needed)

| What | default | super |
|------|---------|-------|
| Surprise filter | Python NLP (0 tok) | AI semantic (~2-5K tok) |
| Annotations | Python templates (0 tok) | AI substantive (~1-3K tok) |
| Entity resolution | Python fuzzy (0 tok) | AI semantic (~500-1K tok) |
| Importance scoring | LLM score (~500 tok) | LLM score + reasoning (~1-2K tok) |
| Reflection | ≥7 days + changes (~15K) | After every importance≥5 (~15K) |
| Lint L2 | Only on `!audit` | Auto on consolidation (24h) |
| Review queue | Manual | Auto-processed |
| Lint L1 (Python) | On reindex >24h (0 tok) | On reindex >24h (0 tok) |
| NLP enrichment | On every ingest (0 tok) | On every ingest (0 tok) |
