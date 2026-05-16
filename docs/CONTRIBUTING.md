# Contributing

> Quick guide for contributing changes to AI Knowledge Engine.

## Prerequisites

- Python 3.11+
- Node.js 20+ (for repomix tests, optional)
- Git

## Setup

```bash
git clone <repo>
cd ai-knowledge-engine
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r knowledge-base/templates/requirements-dev.txt
.venv/bin/pytest knowledge-base/scripts/tests/
```

All tests should pass.

## Where to make changes

| What you want to change | Where |
|--------------------------|-------|
| Reference Python script | `knowledge-base/scripts/*.py` |
| Reference shell script | `knowledge-base/shell/*.sh` |
| Template/configuration | `knowledge-base/templates/` |
| Instruction module | `knowledge-base/*.md` |
| Role example | `knowledge-base/examples/*.yml` |
| Top-level docs | `docs/*.md` |
| Translation | `i18n/<lang>/...` |

See `docs/ARCHITECTURE.md` for the layered structure.

## Workflow

1. Branch off `main`
2. Make your change
3. Update tests if you changed a script
4. Update the corresponding contract `.md` if you changed a script
5. Add a CHANGELOG entry under `[Unreleased]`
6. Run `pytest knowledge-base/scripts/tests/`
7. Run `python3 knowledge-base/scripts/kb_doctor.py --self-test --skip-nlp`
8. Run `python3 scripts/check_translations.py` if your change touched any `knowledge-base/*.md`
9. Open a PR

See `docs/MAINTENANCE.md` for full versioning and synchronization rules.

## Style

- Python: PEP 8, type hints where useful, no over-engineering
- Markdown: short paragraphs; bullet lists where ordering doesn't matter; tables for matrices
- Shell: POSIX-compatible where possible; macOS + Linux must both work
- Translations: see `docs/TRANSLATING.md`

## What we welcome

- Bug fixes (with a regression test)
- New role templates (`examples/<role>.yml` with `placement_examples:`)
- New languages in `i18n/`
- Additional `knowledge-base/scripts/tests/` coverage
- Clarifications and typo fixes in instructions
- New troubleshooting entries in `docs/TROUBLESHOOTING.md`

## What needs design discussion first

- New instruction modules (`15_*.md`, …)
- Breaking changes to `kb.config.yml` schema
- New CLI flags on reference scripts
- Removing existing features

Open an issue describing the motivation before coding.

## License

By contributing, you agree your changes are released under the project's [MIT license](../LICENSE).
