# 00 — Deployment Overview

> **Read this first.** Map for the AI agent: what to read, what to copy, in what order.
> Once familiar with the flow, follow the numbered modules sequentially.

---

## What you (the agent) are doing

Deploying a **Raw-First Knowledge Pipeline** into a user's project:

1. Verify the environment (Node.js, Python, Git, indexer)
2. Ask the user about their role and preferences
3. Copy & parameterize templates from `templates/`
4. Copy reference scripts from `scripts/` and `shell/`
5. Run `kb_doctor.py` to verify the deployment
6. Generate a role-specific `DATA_PLACEMENT_EXAMPLES.md` (Phase 3)
7. Produce a short "what to drop where" summary for the user

**Important:** you are NOT writing the Python/shell scripts from scratch. They live in `scripts/` and `shell/` next to this file. Copy them. Adapt only the config (`kb.config.yml`).

---

## Module reading order

| # | Module | What you do |
|---|--------|-------------|
| 00 | This file | Get the big picture |
| 01 | `01_PREREQUISITES.md` | Verify env, copy `templates/requirements.txt`, install deps |
| 02 | `02_INIT.md` | Ask about role, copy `kb.config.yml.template` and parameterize, create folders |
| 03 | `03_PIPELINE.md` | Copy `scripts/kb_ingest.py` + `scripts/kb_common.py` |
| 04 | `04_REVIEW.md` | Set up review workflow (no code needed) |
| 05 | `05_INDEX.md` | Copy `templates/repomix.config.json.template`, copy `shell/reindex.sh` |
| 06 | `06_AGENTS_TEMPLATE.md` | Copy `templates/AGENTS.md.template` and parameterize |
| 07 | `07_INTERACTION_LOOP.md` | Document commands, no scripts to copy |
| 08 | `08_PORTABLE.md` | Cross-project usage |
| 09 | `09_LINT.md` | Copy `scripts/kb_lint.py`, copy `shell/lint.sh` |
| 10 | `10_LOG.md` | Touch `log.md`; the scripts handle the rest |
| 11 | `11_PROVENANCE.md` | Frontmatter conventions (no scripts) |
| 12 | `12_NLP_PREPROCESS.md` | Install spaCy model; NLP runs from `kb_ingest.py` |
| 13 | `13_AUTORUN.md` | Copy `scripts/kb_watch.py`, `scripts/kb_reflect.py`, `scripts/kb_nlp_batch.py`, `shell/watcher.sh`; install git hook |
| 14 | `14_INITIAL_POPULATION.md` | Generate role-specific `DATA_PLACEMENT_EXAMPLES.md` from `examples/<role>.yml` |

After all modules: run `bash shell/doctor.sh` (or `python3 scripts/kb_doctor.py`) to verify.

---

## What gets copied to the user's KB

```
{user-kb-root}/
├── kb.config.yml                      ← parameterized from templates/kb.config.yml.template
├── repomix.config.json                ← from templates/repomix.config.json.template
├── AGENTS.md                          ← parameterized from templates/AGENTS.md.template
├── KNOWLEDGE_STRUCTURE.md             ← from templates/KNOWLEDGE_STRUCTURE.md.template
├── DATA_PLACEMENT_EXAMPLES.md         ← initial skeleton; Phase 3 expands it
├── requirements.txt                   ← from templates/requirements.txt
├── .gitignore                         ← from templates/.gitignore.template
│
├── scripts/                           ← verbatim copy from knowledge-base/scripts/
│   ├── kb_common.py
│   ├── kb_ingest.py
│   ├── kb_lint.py
│   ├── kb_watch.py
│   ├── kb_reflect.py
│   ├── kb_nlp_batch.py
│   └── kb_doctor.py
│
├── reindex.sh                         ← from shell/reindex.sh
├── watcher.sh                         ← from shell/watcher.sh
├── lint.sh                            ← from shell/lint.sh
├── doctor.sh                          ← from shell/doctor.sh
│
└── (folder structure is created by kb_ingest.py --init-dirs)
```

The scripts in the user's KB are **identical** to the ones in this repo. When upgrading, `kb_upgrade.py` (Phase 4) compares versions and refreshes them.

---

## What you (the agent) MUST NOT do

- Do not invent your own Python pipeline. Copy `scripts/kb_ingest.py`.
- Do not invent your own lint logic. Copy `scripts/kb_lint.py`.
- Do not write your own watcher with custom debouncing. Copy `scripts/kb_watch.py`.
- Do not skip `kb_doctor.py` at the end of the deployment.

---

## Quick mental model

```
User drops files          ┌──── kb_ingest.py ────┐
into raw/*/unsorted/  ────►│  - hash & rename     │──► assets/<type>/<stable>.ext
                          │  - convert to MD     │──► processed/markdown/<stable>.md
                          │  - NLP enrich        │──► processed/nlp-meta/<stable>.yml
                          │  - estimate complexity│──► processed/extracted-metadata/<stable>.yml
                          │  - route             │──► review/needs-ai-decision/  (if complex)
                          └──────────────────────┘
                                      │
                          On simple files, no review.
                          On complex files, agent reviews and writes
                          curated knowledge into knowledge/.

knowledge/**.md  ────► repomix indexes ────► .repomix/output.xml ────► consumed by AI

kb_lint.py runs over knowledge/ to catch staleness, broken links, etc.
kb_watch.py automates the whole loop on file changes.
kb_reflect.py decides when to ask the agent for higher-level reflection.
```

---

## Versioning

`VERSION` in the parent repo holds `instructions_version` (e.g., `0.1.0`).
At deployment, parameterize `kb.config.yml.template` with the current version.
On a future update, `kb_upgrade.py` (Phase 4) compares versions and refreshes scripts.
