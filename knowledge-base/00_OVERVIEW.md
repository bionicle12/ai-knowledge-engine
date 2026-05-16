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

## What gets created during deployment

The agent builds the base inside `<project-root>/knowledge-base/` while keeping the original `setup/` folder. After everything is verified, the agent runs `bash setup/shell/finalize.sh` to flatten the result into the project root and remove both `setup/` and `knowledge-base/`.

Layout BEFORE finalize:

```
{user-project-root}/
├── setup/                            ← upstream instructions (source)
│   ├── 00_OVERVIEW.md … 14_INITIAL_POPULATION.md
│   ├── README.md
│   ├── scripts/, shell/, templates/, examples/
│   └── shell/finalize.sh             ← run at the end
└── knowledge-base/                   ← agent builds the base in here
    ├── kb.config.yml                 ← parameterized from templates/kb.config.yml.template
    ├── repomix.config.json           ← from templates/repomix.config.json.template
    ├── AGENTS.md                     ← parameterized from templates/AGENTS.md.template
    ├── KNOWLEDGE_STRUCTURE.md, DATA_PLACEMENT_EXAMPLES.md, START_HERE.md
    ├── requirements.txt, .gitignore
    ├── scripts/                      ← Python reference scripts (verbatim copy)
    ├── shell/                        ← POSIX wrappers + macOS/Windows launchers
    ├── templates/, examples/         ← kept for re-runs (kb_populate, kb_upgrade)
    └── (folder structure created by kb_ingest.py --init-dirs)
        raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/
```

Layout AFTER finalize — flat at the project root, with launchers at the top level and `*.sh` wrappers in `shell/`:

```
{user-project-root}/
├── kb.config.yml, AGENTS.md, KNOWLEDGE_STRUCTURE.md
├── DATA_PLACEMENT_EXAMPLES.md, START_HERE.md, repomix.config.json
├── reindex.command, watcher-start.command, watcher-stop.command   (macOS launchers)
├── reindex.bat, watcher-start.bat                                  (Windows launchers)
├── requirements.txt
├── shell/                            ← Linux/CLI: watcher.sh, reindex.sh, lint.sh, doctor.sh
├── scripts/                          ← Python pipeline
├── templates/, examples/
└── raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/
```

> Note: `finalize.sh` automatically promotes the `*.command` and `*.bat` launchers from `shell/` up to the project root (so users can double-click them in Finder/Explorer). The `*.sh` files stay only in `shell/` to keep the root tidy.

The scripts in the user's KB are **identical** to the ones in this repo. When upgrading, `kb_upgrade.py` (Phase 4) compares versions and refreshes them.

---

## What you (the agent) MUST NOT do

- Do not invent your own Python pipeline. Copy `scripts/kb_ingest.py`.
- Do not invent your own lint logic. Copy `scripts/kb_lint.py`.
- Do not write your own watcher with custom debouncing. Copy `scripts/kb_watch.py`.
- Do not skip `kb_doctor.py` at the end of the deployment.

## When in doubt about file names

Instructions sometimes lag reality. If a step says to run a script that you cannot find:

1. **Check what is actually present** in `setup/shell/` and `setup/scripts/` — list the directory contents:
   ```bash
   ls setup/shell/
   ls setup/scripts/
   ```
2. The current canonical names (as of the version you are reading):
   - **Finalize** the deployment (move `knowledge-base/` to project root, delete `setup/`): `setup/shell/finalize.sh`
   - Pipeline: `setup/scripts/kb_ingest.py`
   - Lint: `setup/scripts/kb_lint.py`
   - Doctor (smoke-test): `setup/scripts/kb_doctor.py`
   - Watcher: `setup/scripts/kb_watch.py` (Python) or `setup/shell/watcher.sh`/`watcher-start.command`/`watcher-start.bat`
   - Reflection trigger: `setup/scripts/kb_reflect.py`
   - NLP batch: `setup/scripts/kb_nlp_batch.py`
   - Common utils: `setup/scripts/kb_common.py`
   - Populate (DATA_PLACEMENT_EXAMPLES.md generator): `setup/scripts/kb_populate.py`
3. If a script you expected is missing, **do not invent it** — show the user `ls` output and ask. Older docs or your own memory may reference renamed files (e.g., `install.sh` was renamed to `finalize.sh`); always trust the filesystem over recall.

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
