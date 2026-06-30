<div align="center">

# 🧠 AI Knowledge Engine

**Turn any AI coding agent into a self-learning knowledge engine.**

A modular, instruction-driven framework that teaches AI agents (Claude, GPT, Cursor, Codex, Gemini)
to build, maintain, and evolve a structured personal knowledge base — powered by
local-first NLP and automatic context indexing.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](#requirements)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-339933.svg?logo=node.js&logoColor=white)](#requirements)
[![Tests](https://img.shields.io/badge/tests-166_passing-brightgreen.svg)](#)
[![Coverage](https://img.shields.io/badge/coverage-69%25-yellow.svg)](#)
[![Version](https://img.shields.io/badge/version-0.9.3-blue.svg)](VERSION)
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
# 1. Copy this repo's knowledge-base/ into your project as `setup/`
cp -r knowledge-base/ /path/to/your-project/setup/

# 2. Open the project in an IDE with an AI agent
cd /path/to/your-project

# 3. In the chat, send EXACTLY this:
#
#    "Read setup/README.md and setup/00_OVERVIEW.md, then deploy a
#     knowledge base for [your role] inside ./knowledge-base/.
#     When kb_doctor passes, run setup/shell/finalize.sh to flatten
#     the base into the project root."
```

The agent will:
1. Ask clarifying questions about your role (or invent a custom one if no built-in fits)
2. Build the base **inside `./knowledge-base/`** while the original `setup/` stays put
3. Parameterize `kb.config.yml`, `AGENTS.md`, `KNOWLEDGE_STRUCTURE.md`
4. Generate `DATA_PLACEMENT_EXAMPLES.md` (deterministic, no tokens) via `kb_populate.py`
5. Generate `START_HERE.md` — your first read after deployment
6. Run `kb_doctor.py` to confirm everything is wired
7. **Run `bash setup/shell/finalize.sh`** — promotes `knowledge-base/` contents to the project root, removes both `setup/` and `knowledge-base/`

After deployment your project root looks like this:

```
your-project/
├── START_HERE.md              ← read this first
├── AGENTS.md                  ← agent instructions
├── kb.config.yml              ← config
├── DATA_PLACEMENT_EXAMPLES.md ← what to drop where (role-specific)
├── reindex.command            ← macOS double-click
├── watcher-start.command      ← macOS double-click
├── watcher-stop.command       ← macOS double-click
├── reindex.bat, watcher-start.bat ← Windows double-click
├── shell/                     ← Linux/CLI: watcher.sh, reindex.sh, lint.sh, doctor.sh
├── scripts/                   ← Python pipeline
├── templates/, examples/
├── raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/
└── .repomix/                  ← AI-ready output
```

> ⚠️ **Critical:** every new chat session, start with the line: *"Read AGENTS.md and use it as the primary instruction for everything that follows."* Without this the agent has no idea your knowledge base exists. `START_HERE.md` reminds you of this.

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
- 🎙️ **Media Processing** — Audio/video transcription, image OCR, and archive unpacking work out of the box with optional local-only backends
- 🧠 **Self-Learning Loop** — `!save` sessions, `!reflect` for higher-level insights, `!audit` for comprehensive review
- 🔗 **Cross-Linked Knowledge** — `[[wikilinks]]` + routing tables for scalable navigation across hundreds of pages
- 📊 **NLP Enrichment** — Named Entity Recognition, keyword extraction, entity resolution (spaCy + KeyBERT) — zero tokens, pure CPU
- 📜 **Provenance Tracking** — Every fact traced to its original source with hash verification and span-level citations
- 🔍 **Surprise Filter** — Anti-duplication: only genuinely new information enters the knowledge base
- ⚕️ **Health Checks** — Python-based lint for stale pages, orphans, broken links, and contradictions
- ⏰ **Smart Scheduling** — Auto-reflection when importance threshold is reached; skips when idle to save tokens
- 🔐 **Privacy-by-Default** — Raw data, reviews, and interaction logs are never indexed
- 🌍 **Fully Portable** — Pure Markdown files, no databases, no servers, works on any machine with `rsync`
- 🔧 **Reference Implementations** — Python and shell scripts are copied and used as-is, not re-invented by the agent
- ⬆️ **Upgrade Path** — `kb_upgrade.py` refreshes deployed bases while preserving user customizations where possible

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

The full mode creates a rich, opinionated folder hierarchy at the **project root** (no nested `knowledge-base/`):

```
your-project/
├── START_HERE.md               # Read this first
├── AGENTS.md                   # AI agent instructions (auto-generated)
├── KNOWLEDGE_STRUCTURE.md      # This map
├── DATA_PLACEMENT_EXAMPLES.md  # "Got X → put it here" (role-specific)
├── kb.config.yml               # Config: role, entities, mode
├── repomix.config.json         # Indexer config
├── requirements.txt
│
│   # Double-click launchers (macOS / Windows) live at the root:
├── reindex.command, reindex.bat                      # Manual reindex
├── watcher-start.command, watcher-start.bat          # Auto pipeline
├── watcher-stop.command                              # macOS daemon stop
│
├── shell/                      # Linux / CLI: *.sh wrappers
│   ├── watcher.sh, reindex.sh
│   ├── lint.sh, doctor.sh
│   └── (launchers were promoted to root by finalize.sh)
│
├── scripts/                    # Python pipeline (do not modify lightly)
│   ├── kb_ingest.py            # Raw → processed → knowledge
│   ├── kb_lint.py              # Health check (Level 1)
│   ├── kb_reflect.py           # Reflection trigger logic
│   ├── kb_watch.py             # File watcher daemon
│   ├── kb_nlp_batch.py         # Batch NLP re-enrichment
│   ├── kb_populate.py          # Generate DATA_PLACEMENT_EXAMPLES.md
│   ├── kb_doctor.py            # Smoke test
│   └── kb_common.py            # Shared utilities
├── templates/                  # Kept for re-runs (kb_populate, kb_upgrade)
├── examples/                   # Role YAMLs
│
├── raw/                        # 🚫 Raw materials (NOT indexed)
│   ├── documents/unsorted/
│   ├── reference/unsorted/
│   ├── work/unsorted/
│   ├── chats/unsorted/
│   ├── media/unsorted/
│   ├── personal-context/unsorted/
│   └── unsorted/
│
├── processed/                  # 🚫 Converted artifacts (NOT indexed)
├── assets/                     # 🚫 Binary originals (NOT indexed)
│
├── knowledge/                  # ✅ Clean knowledge — INDEXED
│   ├── profile/, principles/, voice/
│   ├── domain/, projects/, decisions/
│   ├── playbooks/, insights/, opinions/
│   ├── timelines/, routing/
│   ├── open-questions/
│   └── _archive/
│
├── assets-index/               # ✅ Markdown descriptions of assets — INDEXED
├── review/                     # 🚫 Review queues (NOT indexed)
│   ├── needs-classification/
│   ├── needs-ai-decision/
│   ├── needs-redaction/
│   └── excluded-sensitive/
│
├── interactions/               # 🚫 Session logs (NOT indexed directly)
└── .repomix/output.xml         # 🚫 Generated index (regenerated locally)
```

---

## Running the watcher (auto-process raw files)

The watcher monitors `raw/<sub>/unsorted/` and runs the ingest pipeline whenever you drop a file there.

### macOS (double-click, no terminal needed)

| Action | File |
|--------|------|
| Start watcher | Double-click `watcher-start.command` |
| Stop watcher | Press Ctrl+C in the opened Terminal window — or, if you started in daemon mode, double-click `watcher-stop.command` |
| Manual reindex | Double-click `reindex.command` |

### Linux

```bash
./shell/watcher.sh              # foreground, Ctrl+C to stop
./shell/watcher.sh --daemon     # background
./shell/watcher.sh --status
./shell/watcher.sh --stop
./shell/reindex.sh              # one-shot reindex
```

### Windows

| Action | File |
|--------|------|
| Start watcher | Double-click `watcher-start.bat` |
| Stop watcher | Close the cmd window or Ctrl+C |
| Manual reindex | Double-click `reindex.bat` |

---

## User Commands

Commands you tell your AI agent in the IDE chat.

> 🚨 **Before any command works in a new chat, send first:**
> *"Read AGENTS.md and use it as the primary instruction for everything that follows."*

| Command | What it does | Cost | When to use |
|---------|-------------|------|-------------|
| `!save` | Save session summary with key decisions and insights | ~2K tokens | After productive sessions (45+ min) |
| `!reflect` | Synthesize higher-level insights from accumulated facts | ~15K tokens | Auto-triggered or on demand |
| `!audit` | Full AI review: contradictions, gaps, merge candidates | ~50–100K tokens | Every 2–4 weeks |
| `!review` | Process the `review/` queues — turn flagged materials into `knowledge/` pages, redact sensitive content, ask questions when input is needed | ~5–30K tokens | When `review/needs-ai-decision/` accumulates after ingest |
| `!populate` | Re-generate `DATA_PLACEMENT_EXAMPLES.md` (run after editing your role YAML) | ~50 tokens | After tweaking `examples/<role>.yml` |
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
| 15 | Media Processing | STT, OCR, archives, and graceful degradation |

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
| `startup-opportunity-explorer.yml` | Startup Opportunity Explorer | Ideation, market gaps, validation, web-app MVPs |
| `content-creator.yml` | Content creator | Voice fingerprinting, audience, monetization |
| `fiction-writer.yml` | Fiction writer | Craft theory, voice training from influences, draft critique |
| `psychologist-gestalt.yml` | Gestalt-oriented psychologist | Ethics, anonymized case reflection, supervision, Gestalt interventions |
| `music-video-director.yml` | Music video writer-director | Hip-hop and short-form concepts, treatments, production, edit rhythm |
| `battle-rap-producer.yml` | Battle rap producer & lyricist | Lyrics craft, punchlines, vocal stacks, mix notes, battle prep |
| `viral-short-form-veo.yml` | Viral short-form video director (TikTok / Veo3) | Viral hooks, storyboards, Veo 3 prompt chains, ad performance learning |
| `russian-software-engineering-student.yml` | Software engineering student in Russia | Curriculum, labs, exams, university docs, internships |

Don't see your role? Tell the AI agent your profession — it will generate a custom configuration with relevant entities, knowledge paths, and example workflows.

---

## Supported AI Agents

Tested and designed for:

| Agent | Status | Notes |
|-------|--------|-------|
| **Claude** (Anthropic) | ✅ Fully supported | Cursor, API, Claude Desktop |
| **GPT** (OpenAI) | ✅ Fully supported | Cursor, Copilot, ChatGPT |
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
