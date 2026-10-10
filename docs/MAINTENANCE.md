# Maintenance Rules

> For contributors and the project owner. Keeps instructions, reference scripts, and translations in sync.

## Versioning

- `VERSION` file in repo root holds **instructions semver**; `ENGINE_VERSION`
  in `knowledge-base/scripts/kb_common.py` must hold the same value (a test in
  `test_kb_common.py` fails otherwise)
- Every deployed knowledge base records `instructions_version` in its `kb.config.yml`
- Bump rules:
  - **patch** (0.1.0 → 0.1.1): typo fixes, doc clarifications, non-breaking script fixes
  - **minor** (0.1.0 → 0.2.0): new modules, new flags, backward-compatible config additions
  - **major** (0.x → 1.0): breaking changes (config schema changes, removed flags, restructured directories)
- `VERSION` changes only in a release commit (see "Release process"). Day-to-day
  changes go under `## [Unreleased]` in `CHANGELOG.md`.

## When you change a `.md` instruction file

1. If it's a **contract for a script** (e.g., `03_PIPELINE.md` ↔ `kb_ingest.py`): update the reference script in `knowledge-base/scripts/` to match
2. Update tests if behavior changed: `knowledge-base/scripts/tests/`
3. Add entry to `CHANGELOG.md` under `[Unreleased]`
4. If translations exist: run `python3 scripts/check_translations.py` and add a
   **Translation impact** note to the CHANGELOG entry when an `i18n/*/` file is
   now stale (see `docs/TRANSLATING.md`)

## When you change a `.py` reference script

1. Update the contract in the corresponding `.md` (e.g., `kb_ingest.py` → `03_PIPELINE.md`)
2. Update or add tests in `knowledge-base/scripts/tests/`
3. Run the test suite (see the checklist below)
4. Add to CHANGELOG under `[Unreleased]`

## When you change a template (`templates/*.template*`)

1. Verify the change is backward-compatible with existing deployments. If not, this is a breaking change.
2. Update relevant instruction module that references the template
3. If deployed bases must catch up (a new file, a changed managed block, a
   `.gitignore` line), add a step under the release's `## X.Y.Z` heading in
   `MIGRATIONS.md` with a detector in `DETECT_BY_ID` (`knowledge-base/scripts/kb_heal.py`);
   for breaking changes also document the steps in `docs/UPGRADING.md`
4. CHANGELOG entry under `[Unreleased]`

## When you add a new instruction module

1. Add to the reading order list in `knowledge-base/README.md` and `00_OVERVIEW.md`
2. If it produces or references files: update `templates/` accordingly
3. Make sure `kb_upgrade.py` and `finalize.sh` ship it to a base's `kb-docs/`
4. `python3 scripts/check_translations.py` lists it as ❌ missing for every
   language until a translation exists
5. CHANGELOG: minor bump

## Pre-commit checklist

Before pushing changes:

- [ ] The full test suite passes, from the repo root: `python3 -m pytest -q`
      (`pyproject.toml` collects `knowledge-base/scripts/tests`, `scripts/tests`
      and `tools/ai-skills-fixer/tests`)
- [ ] `python3 knowledge-base/scripts/kb_doctor.py --self-test` passes
- [ ] `python3 scripts/check_translations.py` runs without errors
- [ ] CHANGELOG updated under `[Unreleased]`

Optional: install `scripts/hooks/pre-commit-translation-drift.sh` as the
pre-commit hook (see `docs/TRANSLATING.md`); it warns when an EN source is
committed without its translation.

## Translation discipline

- EN is the canonical source. All other languages are translations of EN.
- Each translated file MUST have frontmatter:

  ```yaml
  ---
  translation_of: knowledge-base/03_PIPELINE.md
  source_commit: <git sha whose EN text the translation matches>
  source_version: <VERSION at time of translation>
  translated_at: YYYY-MM-DD
  translator: human  # or ai-assisted
  ---
  ```

- Stamp it with `python3 scripts/sync_translations.py --to-source` after the
  EN change is committed and the translation matches.
- Drift is allowed but tracked. `i18n/TRANSLATION_STATUS.md`
  (`check_translations.py --update-status`) is the source of truth.
- Don't merge translations behind multiple minor versions without re-syncing.

## Release process (when cutting a release)

In one release commit:

1. Verify `[Unreleased]` section has all changes
2. Bump `VERSION` and `ENGINE_VERSION` in `knowledge-base/scripts/kb_common.py`
3. Rename `[Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` and add a fresh empty
   `[Unreleased]` above it. Every released version has its own heading;
   headings stay newest first, so a patch release such as 0.15.1 is its own
   `## [0.15.1]` section, not a line under `[Unreleased]`. When `VERSION` was
   bumped ahead of the release (0.16.0 was), the pending section is
   `## [X.Y.Z] - Unreleased` instead: replace `Unreleased` with the date
4. Update the version badge in `README.md` and in each `i18n/<lang>/README.md`
   (the drift checker ignores badge-only differences, so it will not remind you)
5. If the release has catch-up steps, check the `## X.Y.Z` section in `MIGRATIONS.md`
6. Regenerate `scripts/known_hashes.json` with `python3 scripts/build_known_hashes.py`
   (needs a full clone: it reads the git history of the files `kb_upgrade.py`
   manages) and commit it. `kb_upgrade.py` uses it to recognize a pristine file
   from any released version, so bases deployed from a ZIP or a shallow clone
   are not reported as customized
7. `python3 scripts/check_translations.py --update-status` and commit
   `i18n/TRANSLATION_STATUS.md`

Tags are optional: `git tag vX.Y.Z` + `git push origin vX.Y.Z` mark the release
on the forge, but nothing in the engine requires them.
