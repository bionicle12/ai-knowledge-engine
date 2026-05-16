<div align="center">

# 🧠 AI Knowledge Engine

**Turn any AI coding agent into a self-learning knowledge engine.**

A modular, instruction-driven framework that teaches AI agents (Claude, GPT, Cursor, Codex, Gemini)
to build, maintain, and evolve a structured personal knowledge base — powered by
local-first NLP and automatic context indexing.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](#requirements)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-339933.svg?logo=node.js&logoColor=white)](#requirements)
[![Tests](https://img.shields.io/badge/tests-134_passing-brightgreen.svg)](#)
[![Coverage](https://img.shields.io/badge/coverage-69%25-yellow.svg)](#)
[![Version](https://img.shields.io/badge/version-0.8.1-blue.svg)](VERSION)
[![No Cloud Required](https://img.shields.io/badge/Cloud-Not_Required-green.svg)](#)

[Quick Start](#quick-start) · [Features](#features) · [Architecture](#architecture) · [Examples](#examples) · [Русский](i18n/ru/README.md)

</div>

---

## What is this?

**AI Knowledge Engine** is a set of modular Markdown instructions that any AI coding agent can read and execute to:

1. 🗂️ **Index your codebase** — Pack your project into a single AI-readable context file (5 min setup)
2. 🧠 **Build a knowledge base** — Create a full Raw-First Knowledge Pipeline with NLP enrichment, provenance tracking, self-learning, and automated maintenance

No SaaS. No API keys. No cloud. Everything runs locally on your machine.

> **Indexer-agnostic:** Ships with [Repomix](https://github.com/yamadashy/repomix) support out of the box, but the architecture is designed to work with any codebase-to-context tool.

---

## Two Modes

| Mode | What you get | Setup time |
|------|-------------|------------|
| **Lite** → `quick-start/` | AI-optimized codebase index with auto-update on git commit | ~5 minutes |
| **Full** → `knowledge-base/` | Personal knowledge engine with NLP, self-learning loop, AI review queue, health checks, and smart scheduling | ~30 minutes |

---

## Quick Start

### Lite Mode: Codebase Indexing

```bash
# 1. Install the indexer
npm install -g repomix

# 2. Copy quick-start/ into your project
cp -r quick-start/ /path/to/your-project/docs/ai-init/

# 3. Tell your AI agent:
"Read docs/ai-init/INIT_GUIDE.md and set up context indexing for this project"
```

Your AI agent will analyze the project structure, configure the indexer, set up git hooks, and generate the first context snapshot.

### Full Mode: Knowledge Base

```bash
# 1. Install dependencies
npm install -g repomix
pip install pyyaml python-slugify python-docx python-pptx pypdf pandas openpyxl
pip install spacy rake-nltk keybert
python3 -m spacy download ru_core_news_md  # Russian NLP (swap for your language)

# 2. Copy knowledge-base/ into your project
cp -r knowledge-base/ /path/to/your-project/setup/

# 3. Tell your AI agent:
"Read setup/README.md and deploy a knowledge base for [your role]"
```

The agent will ask clarifying questions about your role, create the folder structure, configure NLP pipelines, and run the first indexing pass.

---

## Features

### Lite Mode
- 📦 **One-command setup** — AI agent handles the entire configuration
- 🔄 **Auto-update** — Git hooks regenerate context on every commit
- 🎯 **Stack-aware** — Pre-configured patterns for React, Rust, Python, Go, Node.js, and more
- 🔒 **Security scanning** — Detects leaked secrets before indexing
- 📊 **Token budget control** — Tree-sitter compression reduces token count by 50-70%
- 📂 **Profile support** — Separate context files per subsystem (backend, frontend, infra)

### Full Mode
- 🔬 **Raw-First Pipeline** — Drop PDFs, DOCX, PPTX into `raw/` → auto-convert to Markdown → NLP enrichment → clean knowledge
- 🧠 **Self-Learning Loop** — `!save` sessions, `!reflect` for higher-level insights, `!audit` for comprehensive review
- 🔗 **Cross-Linked Knowledge** — `[[wikilinks]]` + routing tables for scalable navigation across hundreds of pages
- 📊 **NLP Enrichment** — Named Entity Recognition, keyword extraction, entity resolution (spaCy + KeyBERT) — zero tokens, pure CPU
- 📜 **Provenance Tracking** — Every fact traced to its original source with hash verification and span-level citations
- 🔍 **Surprise Filter** — Anti-duplication: only genuinely new information enters the knowledge base
- ⚕️ **Health Checks** — Python-based lint for stale pages, orphans, broken links, and contradictions
- ⏰ **Smart Scheduling** — Auto-reflection when importance threshold is reached; skips when idle to save tokens
- 🔐 **Privacy-by-Default** — Raw data, reviews, and interaction logs are never indexed
- 🌍 **Fully Portable** — Pure Markdown files, no databases, no servers, works on any machine with `rsync`

---

## Architecture

```
                    ┌─────────────┐
User ─────────────→ │   raw/      │  ← PDFs, DOCX, notes, chats, screenshots
                    └──────┬──────┘
                           │ kb_ingest.py (Python + NLP)
                           ▼
                    ┌─────────────┐
                    │ processed/  │  ← Markdown + NLP metadata (0 tokens)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │knowledge/│ │ review/  │ │ assets/  │
        │ (clean)  │ │(complex) │ │(binary)  │
        └────┬─────┘ └──────────┘ └──────────┘
             │
             ▼ context indexer
        ┌──────────────┐
        │  output.xml  │  ← AI-ready context snapshot
        └──────────────┘
```

### Cost Model

Token consumption depends on the **operating mode** (`mode` in `kb.config.yml`):

| Tier | Operations | default | super |
|------|-----------|---------:|------:|
| **Python (free)** | NLP, lint L1, conversion | 0 tok | 0 tok |
| **Light AI** | Importance scoring | ~500 | ~1-2K |
| **Mode-switched** | Surprise filter, annotations, entity resolution | 0 tok (Python) | ~3-9K tok (AI) |
| **Heavy AI** | Reflection, deep review, writeback | ~15-100K | ~15-100K |

| Mode | Daily (active) | Weekly |
|------|---------------:|-------:|
| `default` | **~3-4K tokens** | ~20-30K |
| `super` | **~50-200K+ tokens** | ~500K-1.5M |

---

## Knowledge Structure

The full mode creates a rich, opinionated folder hierarchy:

```
your-project/
├── AGENTS.md                   # AI agent instructions (auto-generated)
├── kb.config.yml               # KB configuration (role, entities, rules)
├── watcher.sh                  # Watch mode (auto-process new files)
├── reindex.sh                  # Manual reindex trigger
├── scripts/                    # Python automation
│   ├── kb_ingest.py            # Raw → processed → knowledge pipeline
│   ├── kb_lint.py              # Health check (Level 1: Python)
│   ├── kb_reflect.py           # Reflection (synthesize insights)
│   ├── kb_watch.py             # File watcher daemon
│   └── kb_nlp_batch.py         # Batch NLP re-enrichment
│
├── raw/                        # Raw materials (NOT indexed)
│   ├── documents/unsorted/
│   ├── reference/unsorted/
│   └── media/unsorted/
│
├── knowledge/                  # ✅ Clean knowledge (INDEXED)
│   ├── domain/                 # Facts, market, technology
│   ├── playbooks/              # Repeatable workflows
│   ├── decisions/              # Immutable decision records
│   ├── principles/             # Rules, beliefs, standards
│   ├── insights/               # Higher-level synthesis
│   ├── opinions/               # Subjective assessments with confidence
│   ├── routing/                # Navigation tables for large bases
│   └── open-questions/         # Unresolved questions
│
├── interactions/               # Session logs (NOT indexed directly)
│   └── sessions/
│
└── review/                     # AI review queue (NOT indexed)
    ├── needs-classification/
    ├── needs-ai-decision/
    └── needs-redaction/
```

---

## User Commands

Commands you tell your AI agent in the IDE chat:

| Command | What it does | Cost | When to use |
|---------|-------------|------|-------------|
| `!save` | Save session summary with key decisions and insights | ~2K tokens | After productive sessions (45+ min) |
| `!reflect` | Synthesize higher-level insights from accumulated facts | ~15K tokens | Auto-triggered or on demand |
| `!audit` | Full AI review: contradictions, gaps, merge candidates | ~50–100K tokens | Every 2–4 weeks |
| `!super` | Toggle operating mode: default ↔ super | 0 tokens | When you need maximum learning speed |
| `!super on/off` | Explicitly enable/disable super mode | 0 tokens | See Operating Modes |
| `!super status` | Show current operating mode | 0 tokens | Quick check |

### Operating Modes

The system supports two operating modes, controlled by `!super` command:

| Mode | Paradigm | Token Cost | Best For |
|------|----------|-----------|----------|
| **default** | Python-first, throttled | ~3-4K/day | Limited token budgets, daily use |
| **super** | AI-first, on-demand | ~50-200K+/day | Unlimited plans, intensive knowledge building |

**Default mode** uses Python-first processing (NLP, heuristic filters) and throttled AI schedules.
AI is called only for importance scoring and large document surprise checks.

**Super mode** replaces Python heuristics with full AI reasoning for every operation:
- 🔍 **Semantic surprise detection** — AI evaluates every ingest for genuinely new information (+40% accuracy vs Python NLP overlap)
- 📝 **Intelligent annotations** — AI generates meaningful cross-references with suggested edits (+60% usefulness vs template annotations)
- 🌐 **Cross-language entity resolution** — AI understands synonyms and multilingual variants (+30% coverage)
- ⚡ **On-demand reflection** — Triggers after every significant ingest (importance ≥5) instead of weekly schedule
- 🧪 **Daily AI audit** — Lint Level 2 runs automatically during consolidation
- 📥 **Auto review processing** — `review/needs-ai-decision/` is processed without waiting for `!audit`

> ⚠️ **Warning:** Super mode can consume your entire daily token budget in a single active session.
> Use only with unlimited or high-limit AI plans.

### Smart Triggers

The system tracks an **importance score** for each ingested item. When the cumulative score exceeds a threshold (default: 25, super: 5), reflection runs automatically. If nothing changed — no tokens are spent.

```
Days without reflection:  1  2  3  4  5  6  7  8  9
Changes?                  -  -  -  -  -  -  -  -  ✓
                                                   ↑
                                          Trigger! (>7 days + changes exist)
```

---

## Instruction Modules

The knowledge base system is built from modular instruction files that the AI agent reads sequentially:

| # | Module | Purpose |
|---|--------|---------|
| 00 | Overview | Deployment map: what to read, what to copy, in what order (read first) |
| 01 | Prerequisites | Environment check: Node.js, Python, Git, indexer |
| 02 | Init | Role clarification, entity selection, folder creation |
| 03 | Pipeline | Python ingest script: conversion + NLP + source hashing |
| 04 | Review | AI review workflow for complex/ambiguous materials |
| 05 | Index | Context indexing, `[[wikilinks]]`, routing tables |
| 06 | Agents Template | `AGENTS.md` template with token budget |
| 07 | Interaction Loop | Self-learning + session capture + query writeback |
| 08 | Portable | Portability + Dynamic Context Enrichment |
| 09 | Lint | Health checks: Level 1 (Python) + Level 2 (AI) + `--metrics` |
| 10 | Log | Append-only operation chronology |
| 11 | Provenance | Source hash, span citations, regression tests |
| 12 | NLP Preprocess | NER + keyword extraction + entity resolution |
| 13 | Autorun | File watcher, git hooks, smart scheduling |
| 14 | Initial Population | Generate role-specific `DATA_PLACEMENT_EXAMPLES.md` |

---

## Role Templates

Pre-configured examples in `knowledge-base/examples/`:

| Template | Role | Highlights |
|----------|------|-----------|
| `programmer-senior.yml` | Senior Software Engineer | Architecture, debugging, tech stack, code principles |
| `marketing-director.yml` | Marketing Director | Strategy, brand, campaigns, audience analysis |
| `creative-hybrid.yml` | Creative Hybrid | Code + music production + indie gamedev |
| `product-manager.yml` | Product Manager | Prioritization, metrics, user research, PRDs |
| `researcher.yml` | Researcher / Analyst | Literature graph, hypotheses, methodology |
| `founder.yml` | Startup founder | Investors, hiring, product, decision logs |
| `content-creator.yml` | Content creator | Voice fingerprinting, audience, monetization |
| `fiction-writer.yml` | Fiction writer | Craft theory, voice training from influences, draft critique |

Don't see your role? Tell the AI agent your profession — it will generate a custom configuration with relevant entities, knowledge paths, and example workflows.

---

## Supported AI Agents

Tested and designed for:

| Agent | Status | Notes |
|-------|--------|-------|
| **Claude** (Anthropic) | ✅ Fully supported | Cursor, API, Claude Desktop |
| **GPT-4 / GPT-4o** | ✅ Fully supported | Cursor, Copilot, ChatGPT |
| **Codex CLI** | ✅ Fully supported | OpenAI Codex |
| **Gemini** | ✅ Fully supported | JetBrains AI, Google AI Studio |
| **Any Markdown-capable agent** | ✅ Compatible | Must read `.md` and run shell commands |

---

## Requirements

| Component | Minimum | Required for |
|-----------|---------|-------------|
| **Node.js** | 20.0+ | Context indexer (Repomix) |
| **Python** | 3.11+ | Ingest pipeline, NLP, lint |
| **Git** | any | Hooks, history tracking |
| **IDE with AI** | required | Agent interaction |

### Optional system tools

```bash
# Ubuntu / Debian
sudo apt install -y pandoc poppler-utils tesseract-ocr

# macOS
brew install pandoc poppler tesseract
```

---

## Contributing

Contributions are welcome! Here's how you can help:

- 🌍 **Translations** — Translate instruction modules to other languages
- 📝 **Role Templates** — Add `examples/*.yml` for new professions
- 🔧 **Pipeline Scripts** — Improve Python ingest, NLP, and lint scripts
- 📖 **Documentation** — Clarify instructions, add diagrams, fix typos
- 🧪 **Testing** — Try with different AI agents and report compatibility

Please open an issue before starting major work to discuss the approach.

---

## License

[MIT](LICENSE) — Free for personal and commercial use.

---

<div align="center">

**Built for humans who talk to AI.**

If this project helps you build a better knowledge workflow — [⭐ give it a star](../../).

</div>
