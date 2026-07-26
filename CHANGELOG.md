# Changelog

All notable changes to AI Knowledge Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`instructions_version` field in deployed `kb.config.yml` should match this VERSION.
On mismatch, `kb_upgrade.py` (Phase 4) helps migrate.

> 🤖 **Note for AI agents reading this file:** the entries below are
> historical and may reference scripts/files that no longer exist by those
> names (e.g., `install.sh` was renamed to `finalize.sh` in 0.9.1). For the
> current canonical state, **always rely on what is actually present in
> `knowledge-base/shell/` and the live instruction modules**, not on
> CHANGELOG history. The `## [Unreleased]` section reflects pending work
> only; the latest released version is the source of truth.

## [Unreleased]

## [0.11.0] - 2026-07-26

### Added
- A lightweight, local-only knowledge graph viewer launched through `!view`.
  It derives nodes and links directly from Markdown and wikilinks, requires no
  vector store or database, and includes search, filters, page details,
  one-hop focus, and diagnostics for orphaned, broken, ambiguous, and stale
  knowledge.
- `scripts/kb_view.py` with idempotent background start, status, stop, refresh,
  safe page reads, and explicit open-in-default-app actions.
- A self-contained offline web UI with a vendored `vis-network` bundle and its
  license notices. The deployment upgrader now copies the full viewer bundle.
- Tests for graph extraction, path safety, HTTP behavior, background lifecycle,
  the offline bundle, and upgrade planning.
- A deployed `scripts/kb_update.py` launcher that locates the authoritative
  source checkout, plus central `--all-root`, repeatable `--accept`, and
  current-directory upgrade modes.

### Fixed
- Upgrades now preserve the finalized layout by syncing POSIX wrappers under
  `shell/` instead of creating false missing files at the KB root.
- Dry-runs no longer claim `.new` files were written, use console-safe status
  text on Windows, and return success when a conflict-free plan completes.
- Existing upstream versions can be recognized from Git history even when a
  deployed base has an inaccurate `instructions_version`; `!view` is added
  through an idempotent managed block without replacing local `AGENTS.md`
  instructions.
- Audit follow-ups: ingest refuses paths outside `raw/**/unsorted/`;
  `assets-index` paths are always POSIX; bare `.gz` no longer mapped as an
  archive strategy; cloud STT is not advertised as usable until implemented;
  `kb_save_session.py` included in `kb_upgrade.SCRIPT_FILES`; docs/overview/
  architecture/README badges aligned with `VERSION` 0.10.0.

## [0.10.0] - 2026-07-09

### Added
- **Out-of-the-box media processing (transcription, OCR, archives).**
  - `knowledge-base/scripts/kb_stt.py` — speech-to-text for audio/video.
    Default backend is `faster-whisper`, which decodes audio via bundled PyAV,
    so **no system `ffmpeg` is required** on macOS/Windows/Linux. Fixes the
    common macOS Homebrew PATH failure ("ffmpeg not found"). Falls back to
    `openai-whisper` when configured. Graceful degradation: missing backend →
    review queue with an OS-specific install hint.
  - `knowledge-base/scripts/kb_ocr.py` — OCR for images/scans. Default backend
    `rapidocr-onnxruntime` (no system deps); Tesseract optional.
  - Archive unpacking (`.zip`, `.tar`, `.tar.gz`) into `raw/unsorted/` for
    re-ingestion, with a zip-bomb safety cap.
  - `knowledge-base/templates/requirements-media.txt` — optional media deps.
  - `media:` section in `kb.config.yml` (stt / ocr / archives).
  - `knowledge-base/15_MEDIA_PROCESSING.md` — contract module.
  - `kb_doctor.py` now reports STT/OCR/ffmpeg readiness.
- `knowledge-base/scripts/kb_reindex.py` — cross-platform (pure-Python) reindex
  orchestrator so the pipeline runs on Windows without Git Bash/WSL. The watcher
  now uses it; `reindex.bat` delegates to it.
- `knowledge-base/scripts/kb_save_session.py` — optional CLI helper to write a
  session summary under `interactions/sessions/` (agent `!save` remains primary).
- `kb_common.find_ffmpeg()` (cross-platform, probes `/opt/homebrew/bin` etc.)
  and `os_install_hint()`.
- `.cursor/rules/` — repo rules for AI agents (architecture/privacy/
  cross-platform + media handling).
- `docs/ROADMAP.md` — phased roadmap with task checklists
- Role templates:
  - `knowledge-base/examples/psychologist-gestalt.yml`
  - `knowledge-base/examples/music-video-director.yml`
  - `knowledge-base/examples/battle-rap-producer.yml`
  - `knowledge-base/examples/viral-short-form-veo.yml`
  - `knowledge-base/examples/russian-software-engineering-student.yml`
  - `knowledge-base/examples/startup-opportunity-explorer.yml`

### Changed
- Agent instructions now route chat-uploaded files into `raw/*/unsorted/`
  only after user confirmation and require a user question before low-signal
  files are extracted into `knowledge/`.
- `kb_ingest.py` now mechanically handles the `stt`, `ocr`, and `archive`
  strategies (previously declared but unimplemented), and recognizes many more
  audio/video/image/archive extensions. Silent `except: pass` blocks in NLP
  enrichment replaced with debug logging (`--verbose`).
- `03_PIPELINE.md` and `01_PREREQUISITES.md` updated: `ffmpeg`/`tesseract` are
  now genuinely optional (only for alternative backends); the defaults need no
  system tools.
- CI remains intentionally disabled: this repo is a download-only template that
  is never deployed, so `.github/workflows/ci.yml.disabled` stays off and is
  documented as such (run `pytest` locally instead).
- `scripts/kb_upgrade.py` syncs the new scripts (`kb_stt`, `kb_ocr`,
  `kb_reindex`, `kb_save_session`) and the previously-missing `kb_populate`.

### Translation impact
- `README.md` role-template table updated; `i18n/ru/README.md` updated
  alongside with the same new templates.
- `i18n/ru/knowledge-base/06_AGENTS_TEMPLATE.md` updated for the new
  chat-attached file rule.
- `i18n/ru/knowledge-base/03_PIPELINE.md` updated for the chat attachment
  staging rule.
- `i18n/ru/knowledge-base/00_OVERVIEW.md` refreshed for finalize layout and
  module 15.

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

## [0.8.2] - 2026-05-16

### Changed
- **CI workflows disabled.** The repo is currently local-only with no public
  GitHub Actions instance, so the workflow file was renamed to prevent
  unintended runs:
  - `.github/workflows/ci.yml` → `.github/workflows/ci.yml.disabled`
  - GitHub Actions only picks up `*.yml`/`*.yaml` files in this directory,
    so the `.disabled` suffix turns the workflow into a no-op.
  - Re-enabling is a single `git mv` away (see `.github/workflows/README.md`).
- Added `.github/workflows/README.md` with explicit "do not enable without
  the project owner's request" note + re-enable instructions.

### Added
- `.github/workflows/README.md` — disabled-state documentation
- `examples/fiction-writer.yml` (released earlier this day, expanded with the
  long-form-book artifact entry)
- `kb_ingest.py` heuristic `_looks_like_long_book` — detects PDF/EPUB/DOCX
  with ≥25 000 words and adds a "long-form reference book" warning block to
  the generated review package, advising the agent to keep prose in
  `assets/` and write a takeaways note instead. Metadata now records
  `long_book_hint: true/false`.
- `03_PIPELINE.md` — new section "Handling long reference materials" with
  the asset-as-reference + notes-as-knowledge pattern and an explicit
  decision tree.
- 8 new tests in `test_kb_ingest.py` for the long-book detection and review-
  package wording.

### Removed
- `i18n/ru/knowledge-base/templates/` — empty leftover folder. Templates,
  scripts, and shell wrappers are language-agnostic and live only in the
  canonical `knowledge-base/`.

### Test stats
- 142 tests passing (was 134)

### Translation impact
- After committing, all 18 RU files become stale (HEAD moved). Run:
  ```
  python3 scripts/sync_translations.py --to-head --lang ru
  python3 scripts/check_translations.py --update-status
  ```

## [0.9.0] - 2026-05-16

> Real-world feedback round: deployed on macOS, found six UX issues, fixed all of them.

### Added
- `knowledge-base/shell/install.sh` — flattens the `setup/` payload into the project root and removes the empty `setup/` folder afterward. Eliminates the nested-`knowledge-base/` problem reported from a real macOS deployment.
- macOS double-click launchers (Finder-friendly, no terminal navigation needed):
  - `shell/watcher-start.command` — opens a Terminal window with the watcher running
  - `shell/watcher-stop.command` — stops a daemonized watcher
  - `shell/reindex.command` — one-shot manual reindex
- Windows equivalents: `shell/watcher-start.bat`, `shell/reindex.bat`
- `templates/START_HERE.md.template` — auto-generated post-deployment cheat sheet that reminds the user to start every new chat with the "Read AGENTS.md…" line
- `!review` command — drains the review queue, processes each item with explicit reporting, honors the long-form-book hint, asks the user one question per item when input is required
- `!populate` command — regenerates `DATA_PLACEMENT_EXAMPLES.md` after a role YAML edit

### Changed
- **Deployment flow** rewritten in `02_INIT.md` and `00_OVERVIEW.md`:
  - User copies `knowledge-base/` to their project as `setup/`
  - Agent runs `bash setup/shell/install.sh` to flatten the payload into the project root
  - No more nested `knowledge-base/` inside the project — files live at the project root
- `kb_populate.py` moved from `scripts/` → `knowledge-base/scripts/` (it's a deployment-time tool, not a maintainer tool); path resolution updated to find `examples/` in either layout
- `templates/AGENTS.md.template` — explicit "Read AGENTS.md first" workflow callout at the top, plus `!review` and `!populate` rows in the commands table
- `04_REVIEW.md` — added a full `!review` command spec with long-form-book guard, defer-to-user pattern, batched questions
- Main `README.md` and `i18n/ru/README.md` — new "Running the watcher" section with platform-specific instructions, updated commands table with `!review`/`!populate`, project-root layout reflecting the new deployment flow, explicit "Read AGENTS.md first" warning

### Test stats
- 142 tests still passing (the kb_populate move didn't change behavior)

### Translation impact
- After committing, the 18 RU files become stale (HEAD moved). Run:
  ```
  python3 scripts/sync_translations.py --to-head --lang ru
  python3 scripts/check_translations.py --update-status
  ```

## [0.9.1] - 2026-05-17

> Hotfix: deployment flow direction reversed. The 0.9.0 `install.sh` was
> pre-deploy (flatten before agent works), which mixed source instructions
> with build artifacts and left the project messy. Replaced with `finalize.sh`
> which runs at the very end.

### Changed
- `knowledge-base/shell/install.sh` → `knowledge-base/shell/finalize.sh`
  - **Old behavior** (pre-deploy): flatten `setup/` into project root, agent
    builds the base on top → mixed instructions and artifacts at the root,
    `setup/` deleted before deployment finished.
  - **New behavior** (post-deploy): agent builds the base inside
    `<project>/knowledge-base/` while `setup/` stays put as the source. After
    `kb_doctor.py` passes and `START_HERE.md` is generated, the agent runs
    `bash setup/shell/finalize.sh` which:
    - Validates required files (`AGENTS.md`, `kb.config.yml`,
      `scripts/kb_ingest.py`)
    - Refuses if anything in `knowledge-base/` would overwrite a file at the
      project root (without `--force`)
    - Promotes every entry to the project root
    - Removes the empty `knowledge-base/`
    - Removes `setup/` (use `--keep-setup` to retain)
  - Flags: `--dry-run`, `--keep-setup`, `--force`, `--kb-dir <path>`
- `02_INIT.md`, `00_OVERVIEW.md`, `14_INITIAL_POPULATION.md` updated to reflect
  the corrected flow:
  - Agent works inside `knowledge-base/` during deployment
  - `--kb-root knowledge-base` for `kb_populate.py` invocations during build
  - `finalize.sh` is the final step in Phase 3

### Added
- `knowledge-base/scripts/tests/test_finalize_sh.py` — 8 tests covering happy
  path, refusal scenarios (missing kb, missing required files, conflicts),
  `--keep-setup`, `--dry-run`, `--force`, idempotency

### Test stats
- 150 tests passing (was 142)

### Translation impact
- After committing, the 18 RU files become stale (HEAD moved). Run:
  ```
  python3 scripts/sync_translations.py --to-head --lang ru
  python3 scripts/check_translations.py --update-status
  ```

## [0.9.2] - 2026-05-17

> Hotfix: shell wrappers and macOS launchers were resolving paths relative
> to their own folder instead of the project root, so they couldn't find
> `scripts/kb_watch.py`. Reported from a real macOS deployment.

### Fixed
- `shell/watcher.sh`, `shell/reindex.sh`, `shell/lint.sh`, `shell/doctor.sh`
  now resolve **the project root** (parent of `shell/`) and `cd` there
  before locating `scripts/`. Previously they did
  `cd "$(dirname "$0")"` and ended up inside `shell/`, where
  `scripts/kb_*.py` does not exist.
- `shell/watcher-start.command`, `shell/watcher-stop.command`,
  `shell/reindex.command` (macOS launchers) now detect the project root
  whether the launcher lives in `shell/` or at the project root, with a
  clear error message if `scripts/` cannot be found.
- `shell/watcher-start.bat`, `shell/reindex.bat` (Windows launchers) — same
  resolution logic.
- All wrappers now report **where they looked** when a script is missing,
  pointing at the resolved project root path.

### Added
- `knowledge-base/scripts/tests/test_shell_wrappers.py` — 8 regression
  tests covering:
  - Wrappers called from project root
  - Wrappers called via absolute path from arbitrary CWD
  - Helpful error message when `scripts/` is missing
  - `.command` launcher located in `shell/` (default)
  - `.command` launcher copied to project root (alternative layout)

### Test stats
- 158 tests passing (was 150)

### Translation impact
- After committing, the 18 RU files become stale (HEAD moved). Run:
  ```
  python3 scripts/sync_translations.py --to-head --lang ru
  python3 scripts/check_translations.py --update-status
  ```

## [0.9.3] - 2026-05-17

> Polish: cleaner final layout. `*.sh` wrappers live only in `shell/`, while
> `*.command` / `*.bat` launchers are promoted to the project root by
> `finalize.sh` so they're discoverable for double-clicking.

### Changed
- `shell/finalize.sh` now performs two extra cleanup steps after promoting
  `knowledge-base/` to the project root:
  1. **Promotes launchers** — moves every `*.command` and `*.bat` from
     `shell/` up to the project root so Finder / Explorer can launch them.
     Skips files that already exist at the root (preserves user customizations).
  2. **Deduplicates `*.sh`** — if a `*.sh` exists both at the root and in
     `shell/` and they are byte-identical, removes the root copy. Different
     content (user customization) is preserved untouched.
- Documentation updated to reflect the cleaner layout:
  - `README.md`, `i18n/ru/README.md` — Linux invocation now shown as
    `./shell/watcher.sh` etc.; project-root tree no longer lists `*.sh` at
    the top level.
  - `00_OVERVIEW.md`, `02_INIT.md` — same.
  - `templates/START_HERE.md.template` — Linux instructions point at
    `./shell/...`, troubleshooting tips updated.

### Added
- 4 new regression tests in `test_finalize_sh.py`:
  - `test_finalize_promotes_command_launchers_to_root`
  - `test_finalize_keeps_sh_in_shell_only`
  - `test_finalize_preserves_root_sh_when_different`
  - `test_finalize_promotion_does_not_overwrite_existing_root_launcher`

### Test stats
- 162 tests passing (was 158)
