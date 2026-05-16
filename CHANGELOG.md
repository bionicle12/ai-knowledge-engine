# Changelog

All notable changes to AI Knowledge Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`instructions_version` field in deployed `kb.config.yml` should match this VERSION.
On mismatch, `kb_upgrade.py` (Phase 4) helps migrate.

## [Unreleased]

### Added
- `docs/ROADMAP.md` — phased roadmap with task checklists
- `VERSION` file (semver of instructions)
- `CHANGELOG.md`
- `docs/MAINTENANCE.md` — contributor rules for keeping instructions/scripts/translations in sync

### Changed
- (none yet)

### Translation impact
- New files in EN need to be translated into `i18n/ru/` once Phase 2 starts.

## [0.1.0] - 2026-05-16

### Added
- Initial public structure: `knowledge-base/` (13 instruction modules), `quick-start/INIT_GUIDE.md`, `examples/` (3 role templates)
- Bilingual `README.md` / `README.ru.md`
- MIT License

## [0.2.0] - 2026-05-16

> Phase 1 (reference implementations) complete.

### Added
- `knowledge-base/templates/` directory with all configuration templates:
  - `kb.config.yml.template` (with full `mode_profiles` for default/super)
  - `repomix.config.json.template`
  - `AGENTS.md.template`
  - `KNOWLEDGE_STRUCTURE.md.template`
  - `DATA_PLACEMENT_EXAMPLES.md.template`
  - `requirements.txt`, `requirements-dev.txt`
  - `.gitignore.template`
- `knowledge-base/scripts/` directory with reference Python implementations:
  - `kb_common.py` — shared utilities (frontmatter, hashing, logging, wikilinks)
  - `kb_doctor.py` — post-deploy smoke test (env, deps, structure, spaCy)
  - `kb_ingest.py` — full pipeline (raw → processed → metadata, NLP, routing)
  - `kb_lint.py` — Level 1 health check (11 rules, lifecycle-aware, auto-fix)
  - `kb_watch.py` — watchdog-based file watcher with polling fallback
  - `kb_reflect.py` — reflection trigger logic (importance threshold + weekly)
  - `kb_nlp_batch.py` — incremental NLP re-enrichment
- `knowledge-base/scripts/tests/` — pytest suite (59 tests) covering common,
  lint, ingest, and reflect logic
- `knowledge-base/shell/` directory with POSIX-safe wrappers:
  - `reindex.sh` (with daily consolidation block)
  - `watcher.sh` (start/stop/status/daemon)
  - `lint.sh`, `doctor.sh`
- `knowledge-base/00_OVERVIEW.md` — agent's deployment map: what to read,
  what to copy, in what order
- `docs/ARCHITECTURE.md` — contributor-oriented architecture overview

### Changed
- Instruction modules now point to reference implementations:
  `01_PREREQUISITES.md`, `02_INIT.md`, `03_PIPELINE.md`, `05_INDEX.md`,
  `06_AGENTS_TEMPLATE.md`, `09_LINT.md`, `13_AUTORUN.md`
- `knowledge-base/README.md` — updated reading order, mentions
  `templates/`, `scripts/`, `shell/`
- `09_LINT.md` — `--only` flag added to the kb_lint contract

### Translation impact
- All instruction modules touched in this release will need re-translation
  in Phase 2. Russian counterparts in `i18n/ru/` (to be created) should be
  marked as stale until updated.

## [0.3.0] - 2026-05-16

> Phase 3 (Initial Population Helper) complete.

### Added
- `knowledge-base/14_INITIAL_POPULATION.md` — new module describing role-aware
  generation of `DATA_PLACEMENT_EXAMPLES.md`
- `placement_examples:` section in all three role templates:
  - `examples/programmer-senior.yml` (7 artifacts + quickstart + don't-drop)
  - `examples/marketing-director.yml` (8 artifacts)
  - `examples/creative-hybrid.yml` (8 artifacts)

### Changed
- `02_INIT.md` — Phase 3 hook directing the agent to `14_INITIAL_POPULATION.md`
  after structure creation
- `templates/DATA_PLACEMENT_EXAMPLES.md.template` — clarified its role as a
  starting skeleton replaced during deployment
- `knowledge-base/README.md`, `00_OVERVIEW.md` — reading order includes module 14

### Translation impact
- `02_INIT.md`, `14_INITIAL_POPULATION.md`, README, and 00_OVERVIEW need new
  Russian translations once Phase 2 begins.

## [0.4.0] - 2026-05-16

> Phase 2 (localization infrastructure) partially complete: framework + critical
> entry-point translations. Modules 03–13 and `INIT_GUIDE.md` remain in Russian
> (with a "pending English translation" banner) for incremental translation.

### Added
- `i18n/ru/` directory with all 17 Russian instruction files copied from the
  canonical sources, each carrying frontmatter:
  `translation_of`, `source_commit`, `source_version`, `translated_at`, `translator`
- `scripts/check_translations.py` — drift report generator
- `i18n/TRANSLATION_STATUS.md` — auto-generated drift report (currently all
  in-sync, will mark stale as canonical EN files evolve)
- `docs/TRANSLATING.md` — contributor guide for adding/maintaining translations

### Changed
- **Translated to English (canonical):**
  - `knowledge-base/README.md`
  - `knowledge-base/01_PREREQUISITES.md`
  - `knowledge-base/02_INIT.md`
  - `knowledge-base/14_INITIAL_POPULATION.md`
- Modules 03–13 and `quick-start/INIT_GUIDE.md` now display a "Pending English
  translation" banner at the top, with a pointer to the Russian copy in
  `i18n/ru/`. Technical contracts inside (file names, code, command names) are
  language-agnostic and remain usable.
- `README.md` link now points to `i18n/ru/README.md`
- `README.ru.md` is now a redirect page to `i18n/ru/README.md`

### Translation impact
- Once the canonical EN versions of modules 03–13 are written, the existing
  `i18n/ru/` copies will be automatically marked as stale by
  `check_translations.py` (their `source_commit` will fall behind HEAD).
  This is the intended workflow.

## [0.5.0] - 2026-05-16

> Phase 2 fully complete: every canonical instruction module is now in English.

### Changed
- Translated to English (replacing Russian originals):
  - `knowledge-base/03_PIPELINE.md`
  - `knowledge-base/04_REVIEW.md`
  - `knowledge-base/05_INDEX.md`
  - `knowledge-base/06_AGENTS_TEMPLATE.md`
  - `knowledge-base/07_INTERACTION_LOOP.md`
  - `knowledge-base/08_PORTABLE.md`
  - `knowledge-base/09_LINT.md`
  - `knowledge-base/10_LOG.md`
  - `knowledge-base/11_PROVENANCE.md`
  - `knowledge-base/12_NLP_PREPROCESS.md`
  - `knowledge-base/13_AUTORUN.md`
  - `quick-start/INIT_GUIDE.md`
- All "Pending English translation" banners removed; English is now the
  unambiguous canonical version.

### Translation impact
- Russian copies under `i18n/ru/` still carry their original `source_commit`
  values. After this release, `python3 scripts/check_translations.py` will
  flag every RU file as **stale** (their commit lags the canonical EN sources).
  Re-translation is tracked via Phase 4 / future commits.
- `i18n/ru/` files remain functional (they continue to describe the same system);
  the divergence is structural (English wording vs Russian wording), not
  semantic.

## [0.6.0] - 2026-05-16

> Phase 4 baseline: upgrade tooling, troubleshooting docs, contributor guide,
> drift hook.

### Added
- `scripts/kb_upgrade.py` — upgrade tool for deployed KBs:
  - Diffs deployed scripts against the source repo
  - Detects user customizations via SHA-256 against the previous git tag
  - Writes `.new` sidecars for customized files instead of overwriting
  - Bumps `instructions_version` after a clean upgrade
  - Modes: `--dry-run`, `--diff`, `--force`
- `docs/UPGRADING.md` — step-by-step upgrade guide for KB owners
- `docs/TROUBLESHOOTING.md` — common installation, pipeline, lint, watcher,
  repomix, reflection, and translation problems with solutions
- `docs/CONTRIBUTING.md` — contributor onboarding
- `scripts/hooks/pre-commit-translation-drift.sh` — opt-in git pre-commit hook
  that warns (without blocking) when canonical files are committed without
  matching translation updates

### Translation impact
- New EN documents in `docs/` (TROUBLESHOOTING, UPGRADING, CONTRIBUTING) are
  EN-only by design (contributor-facing). They are not part of the user-facing
  knowledge-base/ instructions and don't need `i18n/ru/` mirrors.

## [0.7.0] - 2026-05-16

> Phase 4 expanded: more role templates, KB health metrics, edge-case tests,
> top-level scripts coverage, GitHub Actions CI, badges.

### Added
- Four new role templates with full `placement_examples` (artifacts +
  quickstart + don't-drop):
  - `examples/founder.yml` (startup founder)
  - `examples/researcher.yml` (researcher / analyst)
  - `examples/product-manager.yml`
  - `examples/content-creator.yml`
- `kb_lint --metrics` flag — KB health metrics:
  - Lifecycle distribution (permanent / evolving / temporal / unset)
  - Pages per subfolder
  - Importance avg, median, distribution
  - Freshness buckets (≤30d / 30–90d / >90d / no date)
  - Wikilink density, orphan rate, entity coverage
  - Routing depth, insight ratio, annotation overflow count
- Test fixtures in `knowledge-base/scripts/tests/fixtures/`:
  - `with-frontmatter.md`, `no-frontmatter.md`, `empty.md`,
    `broken-frontmatter.md`, `sample.txt`
- Edge-case tests `test_edge_cases.py` (16 tests) covering empty files,
  Unicode filenames, broken frontmatter, idempotency under churn, scaling
  to 50 pages
- Tests for `scripts/check_translations.py` (10 tests)
- Tests for `scripts/kb_upgrade.py` (14 tests)
- `pyproject.toml` with pytest config (importlib mode, dual testpaths)
- `.github/workflows/ci.yml` with five jobs:
  - Tests (Python 3.11, 3.12, macOS-latest)
  - Coverage upload to Codecov
  - kb_doctor self-test
  - Shell-script syntax + shellcheck
  - YAML config and role-example validation
  - Translation drift report

### Changed
- `README.md` — updated badges (tests, coverage, version), expanded role
  templates table (7 roles), added module 00 and 14 to instruction list

### Test stats
- 108 tests passing (was 67)
- ~69% overall coverage; kb_common 91%, kb_lint 84%, kb_reflect 70%

### Translation impact
- The new role templates and updated `README.md` need re-translation in
  `i18n/ru/`. `check_translations.py` will mark them stale automatically.

## [0.7.1] - 2026-05-16

> Patch release: Russian translations synchronized with current canonical EN.

### Added
- `i18n/ru/knowledge-base/00_OVERVIEW.md` — Russian translation of the
  deployment-overview module
- `i18n/ru/knowledge-base/14_INITIAL_POPULATION.md` — Russian translation of
  the initial-population module (was an EN copy in the previous release)
- `scripts/sync_translations.py` — utility that bumps `source_commit`,
  `source_version`, and `translated_at` in translated frontmatter after manual
  re-verification (modes: `--to-head`, `--to-version`, `--lang`, `--files`,
  `--dry-run`)

### Changed
- `i18n/ru/README.md` — refreshed to mirror canonical EN: badges, 7-role table,
  15 instruction modules (00–14), `kb_lint --metrics` mention, `kb_upgrade.py`
  callout, links to `docs/TRANSLATING.md` and `docs/CONTRIBUTING.md`
- `i18n/ru/knowledge-base/README.md` — reading order now includes modules 00
  and 14; pointer to canonical EN added
- All 18 RU translation files bumped to `source_version: 0.7.0` and
  `translated_at: 2026-05-16`
- `docs/TRANSLATING.md` — documented the post-commit workflow:
  `git commit → sync_translations.py --to-head → check_translations.py --update-status`

### Translation impact
- After this release lands and is committed, `check_translations.py` will
  flag the 18 RU files as stale (their `source_commit` will lag the new
  HEAD). Run `python3 scripts/sync_translations.py --to-head --lang ru`
  immediately after committing to reset the markers.

## [0.8.0] - 2026-05-16

> Adds deterministic generation of `DATA_PLACEMENT_EXAMPLES.md` and a custom-role
> workflow.

### Added
- `scripts/kb_populate.py` — pure-templating yaml → markdown generator:
  - Reads `placement_examples` from `examples/<role>.yml`
  - Emits a structured `DATA_PLACEMENT_EXAMPLES.md` with all sections
    (intro, generic table, role-specific quick map, detailed examples,
    quickstart, do-not-drop, footer)
  - `--from <path>` for custom role files
  - `--create-samples` writes `raw/_samples/<artifact>.example.md` placeholders
  - `--dry-run`, `--json`, `--output <name>` flags
  - 0 tokens to generate; deterministic across all AI agents
- `knowledge-base/templates/role.yml.template` — scaffold for the custom-role
  flow (Path B). The agent now must save `examples/<slug>.yml` before invoking
  `kb_populate.py`.
- `scripts/tests/test_kb_populate.py` — 25 tests covering YAML parsing,
  markdown rendering, edge cases, all CLI flags, and a parametrized
  integration test that runs against every shipped role template.

### Changed
- `knowledge-base/14_INITIAL_POPULATION.md` rewritten around the two-path
  workflow:
  - **Path A (built-in role)**: `kb_populate.py --role <role>` directly
  - **Path B (custom role)**: build YAML from `role.yml.template` first, then Path A
  - Added an explicit "AI review pass" step where the agent appends a
    `## Project notes` section with project-specific tips (not capturable in YAML)
  - Updated the agent checklist to enforce the new ordering
- `knowledge-base/02_INIT.md` Phase 3 section now points to the
  populate-script-first workflow

### Test stats
- 133 tests passing (was 108)
- New parametrized tests catch placement_examples regressions in any role
  template before they ship

### Translation impact
- `i18n/ru/knowledge-base/14_INITIAL_POPULATION.md` and
  `i18n/ru/knowledge-base/02_INIT.md` need re-translation. After committing,
  run:
  ```
  python3 scripts/sync_translations.py --to-head --lang ru
  python3 scripts/check_translations.py --update-status
  ```

## [0.8.1] - 2026-05-16

### Added
- `examples/fiction-writer.yml` — role template for fiction writers. Pillars:
  - **Craft theory** entities (story structure, dialogue, POV, scene mechanics, show-don't-tell)
  - **Influences** entity (excerpts from books the writer loves, dissected for *why* they work — the AI's voice anchor)
  - **Genre conventions** entity (tropes, comp titles, reader expectations)
  - **Project hierarchy** (current WIP with outline, characters, worldbuilding subfolders)
  - 11-artifact `placement_examples` covering excerpts, drafts, outlines, character bibles, worldbuilding, beta feedback, voice memos, genre research, queries, anti-patterns
  - `ai_assistant_tasks` focused on *analytical critique* — pacing audits, voice checks, POV slip detection, show-vs-tell passes, structural mapping
- `README.md` and `i18n/ru/README.md` — added the new role to the templates table

### Test stats
- 134 tests passing (one new parametrized integration entry for fiction-writer)
