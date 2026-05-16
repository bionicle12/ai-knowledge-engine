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
├── README.md, README.ru.md      ← Project landing pages
├── VERSION                       ← semver of instructions (e.g., 0.1.0)
├── CHANGELOG.md                  ← Keep-a-Changelog format
├── LICENSE
│
├── docs/                         ← Meta-docs (contributors)
│   ├── ARCHITECTURE.md           ← this file
│   ├── MAINTENANCE.md
│   └── …                          (UPGRADING, TRANSLATING, etc.)
│
├── knowledge-base/               ← Full Mode (canonical EN)
│   ├── README.md                 ← Reading order & principles
│   ├── 00_OVERVIEW.md            ← Agent's deployment checklist
│   ├── 01_…13_*.md               ← Instruction modules
│   ├── 14_INITIAL_POPULATION.md  ← (Phase 3) per-role onboarding
│   ├── templates/                ← Files to copy & parameterize
│   │   ├── kb.config.yml.template
│   │   ├── repomix.config.json.template
│   │   ├── AGENTS.md.template
│   │   ├── KNOWLEDGE_STRUCTURE.md.template
│   │   ├── DATA_PLACEMENT_EXAMPLES.md.template
│   │   ├── requirements.txt
│   │   └── .gitignore.template
│   ├── scripts/                  ← Reference Python implementations
│   │   ├── kb_common.py          ← shared utilities
│   │   ├── kb_ingest.py
│   │   ├── kb_lint.py
│   │   ├── kb_watch.py
│   │   ├── kb_reflect.py
│   │   ├── kb_nlp_batch.py
│   │   ├── kb_doctor.py          ← post-deploy smoke-test
│   │   └── tests/
│   ├── shell/                    ← POSIX-safe wrappers
│   │   ├── reindex.sh
│   │   ├── watcher.sh
│   │   ├── lint.sh
│   │   └── doctor.sh
│   └── examples/                 ← Role templates
│       ├── programmer-senior.yml
│       ├── marketing-director.yml
│       └── creative-hybrid.yml
│
├── quick-start/                  ← Lite Mode
│   └── INIT_GUIDE.md
│
└── i18n/                         ← (Phase 2) Translations
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
3. **`02_INIT.md`** — ask user about role, copy & parameterize `kb.config.yml.template`, create folder structure
4. **`03_PIPELINE.md`** — copy `scripts/kb_ingest.py` and `scripts/kb_common.py`, configure pipeline
5. **`04_REVIEW.md`** — set up review queues
6. **`05_INDEX.md`** — copy `repomix.config.json.template`, parameterize, copy `shell/reindex.sh`
7. **`06_AGENTS_TEMPLATE.md`** — copy & parameterize `templates/AGENTS.md.template`
8. **`07_INTERACTION_LOOP.md`** — explain commands, no scripts to copy here
9. **`08_PORTABLE.md`** — instructions for cross-project use
10. **`09_LINT.md`** — copy `scripts/kb_lint.py`, `shell/lint.sh`
11. **`10_LOG.md`** — initialize `log.md`
12. **`11_PROVENANCE.md`** — config tweaks, no scripts
13. **`12_NLP_PREPROCESS.md`** — install spaCy model, NLP runs from kb_ingest.py
14. **`13_AUTORUN.md`** — copy `scripts/kb_watch.py`, `scripts/kb_reflect.py`, `shell/watcher.sh`; install git hook
15. **`14_INITIAL_POPULATION.md`** (Phase 3) — generate role-specific `DATA_PLACEMENT_EXAMPLES.md`
16. **Run `kb_doctor.py`** — smoke-test the deployment

## Key invariants

- **Instructions never embed full reference scripts** — they reference files in `knowledge-base/scripts/`. Inline code blocks in `.md` are explanatory excerpts.
- **All file paths in instructions are relative** to the deployed knowledge base root (not the source repo)
- **Mode-aware behavior** is configured via `kb.config.yml.mode_profiles`. Reference scripts read this and branch accordingly.
- **Lifecycle** (`permanent` / `evolving` / `temporal`) is the cross-cutting concept that both `kb_lint.py` and `kb_reflect.py` must respect identically.
- **Reference scripts must be idempotent** — re-running on already-processed inputs is safe.

## Versioning model

```
ai-knowledge-engine repo:        VERSION = 0.3.0
└── User's deployed knowledge base
    └── kb.config.yml: instructions_version = 0.2.5
                                      ↑
                                user is one minor behind
                                kb_upgrade.py (Phase 4) helps migrate
```

## Languages

EN is canonical. Translations follow EN with explicit drift tracking via frontmatter `source_commit:`.

See `docs/MAINTENANCE.md` for translation discipline.
