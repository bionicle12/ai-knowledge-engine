# 00 — Deployment Overview

> **Read this first.** Map for the AI agent: what to read, what to copy, in what order.
> Once familiar with the flow, follow the numbered modules sequentially.

---

## What you (the agent) are doing

Deploying a **Raw-First Knowledge Pipeline** into a user's project. The user
copied this kit into the project as `setup/`; you build the base in
`<project-root>/knowledge-base/` and flatten it into the project root at the end.
Run every command from the **project root** unless a step says otherwise.

1. Verify the environment and create the venv at the project root (`01`)
2. Ask the user about their role and preferences (`02` Phase 0)
3. Copy the engine files **once** (`02` Phase 1): `scripts/` (without `tests/`), `shell/`, `templates/`, `examples/`, and the instruction modules into `kb-docs/`
4. Parameterize the templates (`kb.config.yml`, `AGENTS.md`, …) and create the folders
5. Walk modules `03`–`18` in order and configure what each one needs (`02` Phase 3 says which ones to read in full now)
6. Verify with `kb_doctor.py` (it passes when it exits 0), then run `setup/shell/finalize.sh` (`02` "Finish the deployment")
7. Produce a short "what to drop where" summary for the user

**Important:** you are NOT writing the Python/shell scripts from scratch. They live in `setup/scripts/` and `setup/shell/`. Copy them. Adapt only the config (`kb.config.yml`) and the parameterized templates.

---

## Module reading order

The files are copied in `02` Phase 1; each module below says what to configure,
not what to copy.

| # | Module | What it sets up |
|---|--------|-----------------|
| 00 | This file | The big picture |
| 01 | `01_PREREQUISITES.md` | Node.js, Python, Git, Repomix; venv at the project root; install `requirements.txt` (+ optional NLP/media files) |
| 02 | `02_INIT.md` | Role interview, blind-spot pass, four structure sketches (`kb_structure.py`); copy engine files and `kb-docs/`; parameterize `kb.config.yml` and the other templates; create folders |
| 03 | `03_PIPELINE.md` | Ingest contract (`kb_ingest.py`): `raw/` → `assets/`, `processed/`, `review/`; the extraction registry |
| 04 | `04_REVIEW.md` | Review workflow behind `!review` (no code) |
| 05 | `05_INDEX.md` | Index packs (`repomix.config.json`, `kb_reindex.py`, `shell/reindex.sh`) and `STATUS.md` |
| 06 | `06_AGENTS_TEMPLATE.md` | `AGENTS.md` from `templates/AGENTS.md.template` |
| 07 | `07_INTERACTION_LOOP.md` | Commands, feedback loop, optional `kb_save_session.py` |
| 08 | `08_PORTABLE.md` | Cross-project usage |
| 09 | `09_LINT.md` | Lint (`kb_lint.py`, `kb_mutate.py`, `shell/lint.sh`) |
| 10 | `10_LOG.md` | `log.md`; the scripts append to it |
| 11 | `11_PROVENANCE.md` | Frontmatter conventions (no scripts) |
| 12 | `12_NLP_PREPROCESS.md` | spaCy model; NLP runs inside `kb_ingest.py` |
| 13 | `13_AUTORUN.md` | Watcher (`kb_watch.py`, `shell/watcher.sh`), git hook (`shell/install-hooks.sh`), reflection trigger (`kb_reflect.py`) |
| 14 | `14_INITIAL_POPULATION.md` | Role-specific `DATA_PLACEMENT_EXAMPLES.md` (`kb_populate.py`) |
| 15 | `15_MEDIA_PROCESSING.md` | STT/OCR (`kb_stt.py`, `kb_ocr.py`, `requirements-media.txt`); `media:` config |
| 16 | `16_MERGE.md` | Export/import between machines (`kb_export.py`, `kb_import.py`, `shell/export.sh`, `shell/import.sh`); `sync:` config — only when the base runs on more than one machine |
| 17 | `17_REFACTOR.md` | Instruction trim (`!refactor`): two-step audit, owner decisions, eval; `--global` reports only |
| 18 | `18_HEAL.md` | Catch-up after upgrade (`!heal`, `kb_heal.py`) |

After module 18: `python3 knowledge-base/scripts/kb_doctor.py --root knowledge-base`
(or `bash knowledge-base/shell/doctor.sh`) must exit 0, then follow
`02_INIT.md` → "Finish the deployment".

---

## What gets created during deployment

The agent builds the base inside `<project-root>/knowledge-base/` while keeping the original `setup/` folder. After everything is verified, the agent runs `bash setup/shell/finalize.sh` to flatten the result into the project root, copy the instruction modules into `kb-docs/`, and remove both `setup/` and `knowledge-base/`.

Layout BEFORE finalize:

```
{user-project-root}/
├── .venv/                            ← created in 01, stays here for good
├── setup/                            ← the kit (source)
│   ├── 00_OVERVIEW.md … 18_HEAL.md, README.md
│   ├── scripts/, shell/, templates/, examples/
│   └── shell/finalize.sh             ← run at the end
└── knowledge-base/                   ← agent builds the base in here
    ├── kb.config.yml                 ← parameterized from templates/kb.config.yml.template
    ├── repomix.config.json           ← from templates/repomix.config.json.template
    ├── AGENTS.md                     ← parameterized from templates/AGENTS.md.template
    ├── KNOWLEDGE_STRUCTURE.md, DATA_PLACEMENT_EXAMPLES.md, START_HERE.md
    ├── requirements*.txt, .gitignore, .gitattributes
    ├── kb-docs/                      ← the instruction modules (00 … 18, README.md), read at run time
    ├── scripts/                      ← Python reference scripts (verbatim copy, no tests/)
    ├── shell/                        ← POSIX wrappers, git hook, macOS/Windows launchers
    ├── templates/, examples/         ← kept for re-runs (kb_populate, kb_upgrade)
    └── (folder structure created by kb_ingest.py --init-dirs)
        raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/, eval/, sync/
```

Layout AFTER finalize — flat at the project root, with launchers at the top level and `*.sh` wrappers in `shell/`:

```
{user-project-root}/
├── kb.config.yml, AGENTS.md, KNOWLEDGE_STRUCTURE.md
├── DATA_PLACEMENT_EXAMPLES.md, START_HERE.md, repomix.config.json
├── CLAUDE.md                         (only for Claude Code: one line, @AGENTS.md)
├── reindex.command, watcher-start.command, watcher-stop.command   (macOS launchers)
├── export.command, import.command                                  (macOS: cross-base sync)
├── reindex.bat, watcher-start.bat, export.bat, import.bat          (Windows launchers)
├── requirements*.txt, .gitignore, .gitattributes
├── kb-docs/                          ← 00_OVERVIEW.md … 18_HEAL.md, README.md
├── shell/                            ← watcher.sh, reindex.sh, lint.sh, doctor.sh, export.sh, import.sh,
│                                        install-hooks.sh, hooks/post-commit, _kbpy.sh
├── scripts/                          ← Python pipeline
├── templates/, examples/
├── raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/, eval/, sync/
└── .venv/                            ← untouched by finalize
```

> Note: `finalize.sh` promotes the `*.command` and `*.bat` launchers from `shell/` up to the project root (so users can double-click them in Finder/Explorer); the `*.sh` files stay in `shell/`. It never moves or deletes `.git` or a virtualenv, adds the base's `.gitignore` / `.gitattributes` rules at the top of the project's own files (the project's rules keep precedence), moves conflicting project-root files to `.kb-finalize-backup/<timestamp>/` only with `--force`, and records an interrupted run in `.kb-finalize.journal` for `--resume`. Details: `02_INIT.md` → "Finish the deployment".

The scripts in the user's KB are **identical** to the ones in this kit. Later, the engine repository's `scripts/kb_upgrade.py` (see `docs/UPGRADING.md` there) compares versions and refreshes scripts, shell wrappers and `kb-docs/`.

---

## What you (the agent) MUST NOT do

- Do not invent your own Python pipeline. Copy `scripts/kb_ingest.py`.
- Do not invent your own lint logic. Copy `scripts/kb_lint.py`.
- Do not write your own watcher with custom debouncing. Copy `scripts/kb_watch.py`.
- Do not write git hooks by hand. Install `shell/hooks/post-commit` with `shell/install-hooks.sh`.
- Do not create or move a venv inside `knowledge-base/` — it lives at the project root.
- Do not skip `kb_doctor.py` at the end of the deployment.

## When in doubt about file names

Instructions sometimes lag reality. If a step says to run a script that you cannot find:

1. **Check what is actually present** in `setup/shell/` and `setup/scripts/` — list the directory contents:
   ```bash
   ls setup/shell/
   ls setup/scripts/
   ```
2. The current canonical names (as of the version you are reading):
   - **Finalize** the deployment (move `knowledge-base/` to project root, fill `kb-docs/`, delete `setup/`): `setup/shell/finalize.sh`
   - Git post-commit hook: `setup/shell/hooks/post-commit`, installed by `shell/install-hooks.sh`
   - Pipeline: `setup/scripts/kb_ingest.py`
   - Lint: `setup/scripts/kb_lint.py`
   - Doctor (smoke-test): `setup/scripts/kb_doctor.py`
   - Watcher: `setup/scripts/kb_watch.py` (Python) or `setup/shell/watcher.sh`/`watcher-start.command`/`watcher-start.bat`
   - Reindex orchestrator: `setup/scripts/kb_reindex.py`
   - Session hand-off (`STATUS.md`): `setup/scripts/kb_status.py`
   - Reflection trigger: `setup/scripts/kb_reflect.py`
   - NLP batch: `setup/scripts/kb_nlp_batch.py`
   - STT / OCR: `setup/scripts/kb_stt.py`, `setup/scripts/kb_ocr.py`
   - Session save (optional CLI): `setup/scripts/kb_save_session.py`
   - Common utils (and the engine version: `kb_common.py --version`): `setup/scripts/kb_common.py`
   - Populate (DATA_PLACEMENT_EXAMPLES.md generator): `setup/scripts/kb_populate.py`
   - Structure sketches (four variants + blind spots): `setup/scripts/kb_structure.py`
   - Mutate (L1 lint self-check): `setup/scripts/kb_mutate.py`
   - Heal: `setup/scripts/kb_heal.py`
3. If a script you expected is missing, **do not invent it** — show the user `ls` output and ask. Older docs or your own memory may reference renamed files (e.g., `install.sh` was renamed to `finalize.sh`); always trust the filesystem over recall.

---

## Quick mental model

```
User drops files          ┌──── kb_ingest.py ─────┐
into raw/*/unsorted/  ────►│  - hash & rename      │──► assets/<type>/<stable>.ext
                          │  - convert / STT/OCR  │──► processed/markdown|transcripts|ocr/
                          │  - NLP enrich         │──► processed/nlp-meta/<stable>.yml
                          │  - estimate complexity│──► processed/extracted-metadata/<stable>.yml
                          │  - route              │──► review/needs-*/  (complex or sensitive)
                          └───────────────────────┘
                                      │
                          Every converted file waits for extraction
                          (`extraction: pending`). On `!review` the agent
                          works the review/ queues and the pending
                          processed/ items, and writes curated knowledge
                          into knowledge/.

knowledge/**.md  ────► kb_reindex.py (Repomix) ────► .repomix/<pack>.xml ────► consumed by AI
                                          └────────► STATUS.md (pending work, read at session start)

kb_lint.py runs over knowledge/ to catch staleness, broken links, etc.
kb_watch.py automates the whole loop on file changes.
kb_reflect.py decides when to ask the agent for higher-level reflection.
```

---

## Versioning

The engine repository's `VERSION` file holds the engine version. The kit has no
`VERSION` file; the same number is printed by
`python3 setup/scripts/kb_common.py --version`. At deployment, fill
`{{KB_INSTRUCTIONS_VERSION}}` in `kb.config.yml.template` with that output
(`instructions_version`). On a future update, `kb_upgrade.py` compares versions
and refreshes scripts.
