# Maintenance Rules

> For contributors and the project owner. Keeps instructions, reference scripts, and translations in sync.

## Versioning

- `VERSION` file in repo root holds **instructions semver**
- Every deployed knowledge base records `instructions_version` in its `kb.config.yml`
- Bump rules:
  - **patch** (0.1.0 → 0.1.1): typo fixes, doc clarifications, non-breaking script fixes
  - **minor** (0.1.0 → 0.2.0): new modules, new flags, backward-compatible config additions
  - **major** (0.x → 1.0): breaking changes (config schema changes, removed flags, restructured directories)

## When you change a `.md` instruction file

1. If it's a **contract for a script** (e.g., `03_PIPELINE.md` ↔ `kb_ingest.py`): update the reference script in `knowledge-base/scripts/` to match
2. Update tests if behavior changed: `knowledge-base/scripts/tests/`
3. Bump `VERSION`
4. Add entry to `CHANGELOG.md` under `[Unreleased]`
5. If translations exist: run `python3 scripts/check_translations.py --update-status` (Phase 2)
6. In CHANGELOG, add **Translation impact** note if any `i18n/*/` file is now stale

## When you change a `.py` reference script

1. Update the contract in the corresponding `.md` (e.g., `kb_ingest.py` → `03_PIPELINE.md`)
2. Update or add tests in `knowledge-base/scripts/tests/`
3. Run `pytest knowledge-base/scripts/tests/` locally
4. Bump VERSION (patch for fixes, minor for new flags/features)
5. Add to CHANGELOG

## When you change a template (`templates/*.template*`)

1. Verify the change is backward-compatible with existing deployments. If not, this is a breaking change.
2. Update relevant instruction module that references the template
3. For breaking template changes — document migration steps in `docs/UPGRADING.md` (Phase 4)
4. Bump VERSION
5. CHANGELOG entry

## When you add a new instruction module

1. Add to the reading order list in `knowledge-base/README.md` and `00_OVERVIEW.md`
2. If it produces or references files: update `templates/` accordingly
3. Add the file to `i18n/*/knowledge-base/` placeholders (mark as needing translation)
4. CHANGELOG: minor bump

## Pre-commit checklist

Before pushing changes:

- [ ] `pytest knowledge-base/scripts/tests/` passes
- [ ] `python3 knowledge-base/scripts/kb_doctor.py --self-test` passes
- [ ] `python3 scripts/check_translations.py` runs without errors (Phase 2+)
- [ ] CHANGELOG updated under `[Unreleased]`
- [ ] VERSION bumped if shipping (otherwise leave for the release commit)

## Translation discipline (Phase 2+)

- EN is the canonical source. All other languages are translations of EN.
- Each translated file MUST have frontmatter:

  ```yaml
  ---
  translation_of: knowledge-base/03_PIPELINE.md
  source_commit: <git sha at time of translation>
  source_version: <VERSION at time of translation>
  translated_at: YYYY-MM-DD
  translator: human  # or ai-assisted
  ---
  ```

- Drift is allowed but tracked. The status table is the source of truth.
- Don't merge translations behind multiple minor versions without re-syncing.

## Release process (when cutting a release)

1. Verify `[Unreleased]` section has all changes
2. Rename `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`
3. Add fresh `[Unreleased]` section at the top
4. Tag git: `git tag vX.Y.Z`
5. Push tag: `git push origin vX.Y.Z`
