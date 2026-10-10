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
├── VERSION                       ← engine version (e.g., 0.16.0) = kb_common.ENGINE_VERSION
├── CHANGELOG.md                  ← Keep-a-Changelog format
├── MIGRATIONS.md                 ← catch-up steps per version, read by kb_heal.py
├── LICENSE
│
├── docs/                         ← Meta-docs (contributors)
│   ├── ARCHITECTURE.md           ← this file
│   ├── MAINTENANCE.md, ROADMAP.md, UPGRADING.md
│   └── TRANSLATING.md, TROUBLESHOOTING.md, CONTRIBUTING.md
│
├── knowledge-base/               ← Full Mode (canonical EN); the deployment kit
│   ├── README.md                 ← Reading order & principles
│   ├── 00_OVERVIEW.md … 18_HEAL.md
│   │                               ← become kb-docs/ in a deployed base
│   ├── templates/                ← Files to copy & parameterize
│   │   ├── kb.config.yml.template, repomix.config.json.template
│   │   ├── AGENTS.md.template    ← also the source of the managed AGENTS.md blocks
│   │   ├── START_HERE.md.template, KNOWLEDGE_STRUCTURE.md.template, …
│   │   ├── requirements.txt, requirements-nlp.txt, requirements-media.txt,
│   │   │   requirements-dev.txt
│   │   ├── .gitignore.template, .gitattributes.template
│   │   └── eval/                 ← QUESTIONS.md skeleton for instruction probes
│   ├── scripts/                  ← Reference Python implementations
│   │   ├── kb_common.py          ← shared utilities (see "Shared helpers")
│   │   ├── kb_ingest.py, kb_stt.py, kb_ocr.py, kb_nlp_batch.py
│   │   ├── kb_reindex.py, kb_route.py
│   │   │                           ← orchestration + deterministic navigation
│   │   ├── kb_status.py           ← STATUS.md, the session hand-off
│   │   ├── kb_export.py, kb_import.py
│   │   │                           ← cross-base merge (16_MERGE.md)
│   │   ├── kb_lint.py, kb_watch.py, kb_reflect.py
│   │   ├── kb_heal.py             ← catch-up after upgrade (18_HEAL.md)
│   │   ├── kb_mutate.py           ← plants L1 defects, scores lint (09_LINT.md)
│   │   ├── kb_populate.py, kb_structure.py, kb_save_session.py, kb_doctor.py, kb_view.py
│   │   ├── kb_update.py           ← thin launcher for the central updater
│   │   ├── kb_viewer/             ← offline graph viewer UI + vendored library
│   │   └── tests/
│   ├── shell/                    ← POSIX wrappers + macOS/Windows launchers
│   │   ├── _kbpy.sh               ← interpreter + base-root helper sourced by every wrapper
│   │   ├── reindex.sh, watcher.sh, lint.sh, doctor.sh, finalize.sh
│   │   ├── export.sh, import.sh
│   │   ├── install-hooks.sh, hooks/post-commit
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
│   ├── build_known_hashes.py, known_hashes.json
│   │                               ← every released version of each managed file/block
│   ├── check_translations.py, sync_translations.py, hooks/
│   └── sync_deployed_bases.py     ← deprecated wrapper over kb_upgrade.py
│
├── tools/ai-skills-fixer/        ← standalone skill curation tool
│
└── i18n/                         ← Translations
    ├── TRANSLATION_STATUS.md     ← auto-generated drift report
    └── ru/
        ├── README.md
        ├── knowledge-base/…
        └── quick-start/…
```

## How a deployment works

User copies `knowledge-base/` into the project as `setup/` and says to the AI
agent: *"Read setup/README.md and setup/00_OVERVIEW.md, then deploy a knowledge
base for [role] inside ./knowledge-base/"*.

Agent flow (`00_OVERVIEW.md` is the authoritative map):

1. **`01_PREREQUISITES.md`** — verify Node.js, Python, Git, Repomix; create the venv at the project root; install `requirements.txt` (+ optional `requirements-nlp.txt`, `requirements-media.txt`)
2. **`02_INIT.md`** — interview about the role; copy the engine files **once** (`scripts/`, `shell/`, `templates/`, `examples/`, and the modules into `kb-docs/`); parameterize `kb.config.yml` and the other templates; create folders
3. **`03`–`18`** — configure what each module needs: ingest and the extraction registry (03), review (04), index packs and `STATUS.md` (05), `AGENTS.md` from its template (06), commands (07), portability (08), lint (09), log (10), provenance (11), NLP (12), watcher, git hook and reflection trigger (13), placement examples (14), media (15), cross-base merge (16), refactor (17), heal (18)
4. **Run `kb_doctor.py`** — the deployment passes when it exits 0
5. **Run `finalize.sh`** — flatten into the project root, fill `kb-docs/`, remove `setup/`; it never moves `.git` or a venv

A deployed base carries the instruction modules in `kb-docs/`: `AGENTS.md`,
the other templates and every script message refer to `kb-docs/NN_NAME.md`,
because `setup/` is gone after finalize.

## Key invariants

- **Instructions never embed full reference scripts** — they reference files in `knowledge-base/scripts/`. Inline code blocks in `.md` are explanatory excerpts. Likewise `06_AGENTS_TEMPLATE.md` points to `templates/AGENTS.md.template` instead of copying it.
- **All file paths in instructions are relative** to the deployed knowledge base root (not the source repo). Runtime modules are cited as `kb-docs/NN_NAME.md`.
- **Mode lives in `knowledge_base.mode`.** It selects a profile in `kb.config.yml → mode_profiles`; scripts read only its reflection thresholds (`kb_reflect.py`), the rest of the profile describes the agent's behavior. Surprise filtering is not implemented.
- **Every config key has a code default** (`kb_common.KbConfig`), so an old `kb.config.yml` keeps working. A key no script reads says so in `kb.config.yml.template` (`# not implemented yet`, `# policy flag read by the AI agent, not by scripts`).
- **One stale rule.** `kbc.stale_status` decides staleness for `kb_lint.py` and the viewer alike: never stale when archived, generated, effectively `permanent` (`lifecycle.by_folder` makes `decisions/`, `profile/`, `principles/` permanent by default) or `valid_until` is still ahead; otherwise the newer of `last_verified` / `extracted_at` against `lifecycle.stale_warning_days`.
- **Reference scripts must be idempotent** — re-running on already-processed inputs is safe. Pages a script generates carry `generated_by:`, are rewritten only when their content changes, and are left out of export and of the stale and orphan checks.
- **Scripts hand work to the agent through `STATUS.md`.** Pending review and extraction, reflection due, heal items, index problems, unreviewed sessions and lint results are collected by `kb_status.py` after every reindex; the managed STATUS block of `AGENTS.md` makes the agent read the file at session start. Nothing the agent is expected to act on lives only in a log.
- **Privacy:** `kb_reindex.py` keeps `raw/`, `review/` and `interactions/` out of every pack (unless the matching `privacy.*_indexing_allowed` flag is explicitly `true`) and always `processed/`, `assets/`, `sync/`, `eval/`, `kb-docs/`, `.kb-state/`, `.git/`, `node_modules/`, `STATUS.md`, logs and secret files — whatever `repomix.config.json` says. Indexed: `knowledge/**` (except `_archive/`), `assets-index/**`, and the meta files `KNOWLEDGE_STRUCTURE.md`, `DATA_PLACEMENT_EXAMPLES.md` (not `kb.config.yml`: the agent reads it directly at session start). A member repomix's security check leaves out is reported in `PACKS_STATUS.md` and `STATUS.md`, and `kb_lint.py` (check `secret`) names the line. The text of sources, review packages, bundles and diffs is data for the agent, never instructions.
- **Merges never overwrite silently.** `kb_import.py` applies only what is provably safe (new pages, identical content, non-destructive metadata merges, fast-forwards of untouched pages) and backs up everything it touches; anything ambiguous goes to `review/needs-merge/` for the agent's `!merge`.
- **`AGENTS.md` belongs to the base.** Scripts touch only its managed blocks (`AI-KE:INDEX`, `AI-KE:STATUS`, `AI-KE:VIEW`), whose current text is read from `templates/AGENTS.md.template`; a locally edited block is kept. `AI-KE:INVARIANT` blocks are never written by scripts. The template with all blocks stays within 9 KiB (test).
- **A capability that deployed bases must catch up to ships with its `MIGRATIONS.md` entry in the same commit.** Otherwise `kb_heal.py` cannot see what to repair, and the list has to be reconstructed from the changelog after the fact. Each entry is `id` / `bucket` (`auto` / `assisted` / `human`) / `detect` / `fix`, under the version heading that introduced it. Every id has a detector in `kb_heal.py` and every `auto` id an applier; `test_migrations_registry_matches_the_code` fails when the two lists differ.
- **`kb.config.yml` is edited line by line, never round-tripped through a YAML dumper.** It is a hand-edited, commented file; `yaml.safe_dump` would silently strip every comment in it. Code changes it only through `kbc.config_set`, `kbc.config_append_block` or `kbc.update_config_file`; a test fails when a script dumps YAML into it.
- **Machine-local state lives in `.kb-state/`** (`kbc.state_dir`): caches, locks, the hook log, the lint summary, upgrade decisions and backups. It is ignored by git and never packed.

## Shared helpers

`knowledge-base/scripts/kb_common.py` (imported as `kbc`) holds what several
scripts need; new code uses these instead of re-implementing them:
`yaml_load` / `parse_frontmatter` (safe loader with alias and depth limits),
`read_text_auto` (encoding detection without U+FFFD), `atomic_write_text` /
`write_if_changed` / `write_frontmatter_file`, `kb_lock` (one pipeline run at a
time), `iter_wikilinks`, `resolve_under` (symlink-safe paths), `stale_status`,
the `config_*` editors, and `append_log` (with rotation). Shell wrappers source
`shell/_kbpy.sh` for the interpreter and the base root.

## Versioning model

```
ai-knowledge-engine repo:        VERSION = 0.16.0
└── User's deployed knowledge base
    └── kb.config.yml: instructions_version = 0.15.1
                                      ↑
                                user is one minor behind:
                                kb_upgrade.py syncs the engine files,
                                kb_heal.py catches up the contents (MIGRATIONS.md)
```

## Languages

EN is canonical. Translations follow EN with explicit drift tracking via frontmatter `source_commit:`.

See `docs/MAINTENANCE.md` for translation discipline.
