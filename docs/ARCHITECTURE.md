# Architecture overview

> How the pieces fit together. For contributors and the project owner.
> User-facing docs live in `README.md` and `knowledge-base/README.md`.

## Two layers of artifacts

The project ships two kinds of artifacts:

1. **Instructions** (`knowledge-base/*.md`, `quick-start/INIT_GUIDE.md`) — read by AI agents. Describe contracts, conventions, decision logic.
2. **Reference implementations** (`knowledge-base/scripts/`, `knowledge-base/shell/`, `knowledge-base/templates/`) — copied into a user's project during deployment. Adapted, not invented from scratch.

Why both: instructions alone leave too many decisions to the agent. Implementations alone are inflexible. Together: agent decides *what to deploy* (mode, role, language), but *how* is deterministic.

## Repo structure

```
ai-knowledge-engine/
├── README.md                     ← Project landing (EN); RU → i18n/ru/README.md
├── VERSION                       ← semver of instructions (e.g., 0.12.0)
├── CHANGELOG.md                  ← Keep-a-Changelog format
├── LICENSE
│
├── docs/                         ← Meta-docs (contributors)
│   ├── ARCHITECTURE.md           ← this file
│   ├── MAINTENANCE.md
│   ├── ROADMAP.md
│   └── …                          (UPGRADING, TRANSLATING, etc.)
│
├── knowledge-base/               ← Full Mode (canonical EN)
│   ├── README.md                 ← Reading order & principles
│   ├── 00_OVERVIEW.md … 16_MERGE.md
│   ├── templates/                ← Files to copy & parameterize
│   │   ├── kb.config.yml.template
│   │   ├── repomix.config.json.template
│   │   ├── AGENTS.md.template, START_HERE.md.template, …
│   │   ├── requirements.txt, requirements-media.txt, requirements-dev.txt
│   │   └── .gitignore.template
│   ├── scripts/                  ← Reference Python implementations
│   │   ├── kb_common.py          ← shared utilities
│   │   ├── kb_ingest.py, kb_stt.py, kb_ocr.py
│   │   ├── kb_reindex.py, kb_route.py
│   │   │                           ← orchestration + deterministic navigation
│   │   ├── kb_export.py, kb_import.py
│   │   │                           ← cross-base merge (16_MERGE.md)
│   │   ├── kb_lint.py, kb_watch.py, kb_reflect.py, kb_nlp_batch.py
│   │   ├── kb_populate.py, kb_save_session.py, kb_doctor.py, kb_view.py
│   │   ├── kb_update.py           ← thin launcher for the central updater
│   │   ├── kb_viewer/             ← offline graph viewer UI + vendored library
│   │   └── tests/
│   ├── shell/                    ← POSIX wrappers + macOS/Windows launchers
│   │   ├── reindex.sh, watcher.sh, lint.sh, doctor.sh, finalize.sh
│   │   ├── export.sh, import.sh
│   │   ├── reindex.command, watcher-start.command, watcher-stop.command
│   │   ├── export.command, import.command
│   │   └── reindex.bat, watcher-start.bat, export.bat, import.bat
│   └── examples/                 ← Role templates (*.yml)
│
├── quick-start/                  ← Lite Mode
│   └── INIT_GUIDE.md
│
├── scripts/                      ← Repo-level tooling (upgrade, i18n sync)
│   ├── kb_upgrade.py
│   ├── check_translations.py, sync_translations.py
│   └── sync_deployed_bases.py
│
└── i18n/                         ← Translations
    ├── TRANSLATION_STATUS.md     ← auto-generated drift report
    └── ru/
        ├── README.md
        ├── knowledge-base/…
        └── quick-start/…
```

## How a deployment works

User says to AI agent: *"Read knowledge-base/README.md and deploy a knowledge base for [role]"*.

Agent flow:

1. **Read `00_OVERVIEW.md`** — sequential reading list + which template to copy at each step
2. **`01_PREREQUISITES.md`** — verify env, copy `templates/requirements.txt`, install deps
3. **`02_INIT.md`** — ask user about role, copy & parameterize `kb.config.yml.template`, create folder structure (copy `scripts/`, `shell/`, `templates/`, `examples/` verbatim)
4. **`03_PIPELINE.md`** — configure ingest (`kb_ingest.py` + `kb_common.py`)
5. **`04_REVIEW.md`** — set up review queues
6. **`05_INDEX.md`** — copy `repomix.config.json.template`, parameterize, wire `kb_reindex.py` / `shell/reindex.sh`
7. **`06_AGENTS_TEMPLATE.md`** — copy & parameterize `templates/AGENTS.md.template`
8. **`07_INTERACTION_LOOP.md`** — explain commands; optional `kb_save_session.py`
9. **`08_PORTABLE.md`** — instructions for cross-project use
10. **`09_LINT.md`** — `kb_lint.py`, `shell/lint.sh`
11. **`10_LOG.md`** — initialize `log.md`
12. **`11_PROVENANCE.md`** — config tweaks, no scripts
13. **`12_NLP_PREPROCESS.md`** — install spaCy model, NLP runs from `kb_ingest.py`
14. **`13_AUTORUN.md`** — `kb_watch.py`, `kb_reflect.py`, `kb_nlp_batch.py`, `shell/watcher.sh`; install git hook
15. **`14_INITIAL_POPULATION.md`** — generate role-specific `DATA_PLACEMENT_EXAMPLES.md`
16. **`15_MEDIA_PROCESSING.md`** — STT/OCR/archives (`kb_stt.py`, `kb_ocr.py`, `requirements-media.txt`)
17. **`16_MERGE.md`** — cross-base merge (`kb_export.py`, `kb_import.py`, `shell/export.sh`, `shell/import.sh`); only needed when the base runs on more than one machine
18. **Run `kb_doctor.py`** — smoke-test the deployment
19. **Run `finalize.sh`** — flatten into the project root

## Key invariants

- **Instructions never embed full reference scripts** — they reference files in `knowledge-base/scripts/`. Inline code blocks in `.md` are explanatory excerpts.
- **All file paths in instructions are relative** to the deployed knowledge base root (not the source repo)
- **Mode-aware behavior** is configured via `kb.config.yml.mode_profiles`. Reference scripts read this and branch accordingly.
- **Lifecycle** (`permanent` / `evolving` / `temporal`) is the cross-cutting concept that both `kb_lint.py` and `kb_reflect.py` must respect identically.
- **Reference scripts must be idempotent** — re-running on already-processed inputs is safe.
- **Privacy:** never index `raw/`, `assets/`, `review/`, `interactions/`, `sync/` — only `knowledge/**` and `assets-index/**`.
- **Merges never overwrite silently.** `kb_import.py` applies only what is provably safe (new pages, identical content, non-destructive metadata merges, fast-forwards of untouched pages) and backs up everything it touches; anything ambiguous goes to `review/needs-merge/` for the agent's `!merge`.

## Versioning model

```
ai-knowledge-engine repo:        VERSION = 0.12.0
└── User's deployed knowledge base
    └── kb.config.yml: instructions_version = 0.9.3
                                      ↑
                                user is one minor behind
                                kb_upgrade.py helps migrate
```

## Languages

EN is canonical. Translations follow EN with explicit drift tracking via frontmatter `source_commit:`.

See `docs/MAINTENANCE.md` for translation discipline.
