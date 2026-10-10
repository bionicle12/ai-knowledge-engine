# Translating AI Knowledge Engine

> Guide for adding or maintaining a translation of instruction modules.

## Canonical source

**English is canonical.** The root `README.md` and every `.md` under
`knowledge-base/` and `quick-start/` (sub-folders included) are the source of
truth — except files inside `scripts/`, `templates/`, `tests/`, `vendor/` or a
dot-folder, which are code, fixtures or templates rather than prose to
translate. This set is `CANONICAL_GLOBS` / `NON_DOC_DIRS` in
`scripts/check_translations.py`. Translations live in `i18n/<lang>/` and
mirror the source paths.

```
ai-knowledge-engine/
├── README.md                      ← canonical EN
├── knowledge-base/                ← canonical EN
│   ├── 00_OVERVIEW.md
│   ├── 01_PREREQUISITES.md
│   └── ...
├── quick-start/
│   └── INIT_GUIDE.md
└── i18n/
    ├── TRANSLATION_STATUS.md      ← generated drift report
    └── ru/
        ├── README.md
        ├── knowledge-base/
        │   ├── 00_OVERVIEW.md
        │   ├── 01_PREREQUISITES.md
        │   └── ...
        └── quick-start/
            └── INIT_GUIDE.md
```

## Required frontmatter for translated files

Every translated `.md` MUST start with:

```yaml
---
translation_of: knowledge-base/03_PIPELINE.md
source_commit: a1b2c3d
source_version: 0.3.0
translated_at: 2026-05-16
translator: human
---
```

| Field | Meaning |
|-------|---------|
| `translation_of` | Path to source file relative to repo root |
| `source_commit` | Git commit whose EN text the translation matches |
| `source_version` | Repo `VERSION` at translation time (informational) |
| `translated_at` | ISO-8601 date |
| `translator` | `human` \| `ai-assisted` \| `machine` |

## How drift is measured

`python3 scripts/check_translations.py` compares each EN source **as it is in
the working tree** (uncommitted edits included) with the same file at the
translation's `source_commit`, and reports:

- ✅ in sync — the source text is unchanged since `source_commit`
- ⚠️ stale — the source text changed (the Drift column counts the commits and
  says "uncommitted edits" when the working tree differs), `source_commit` is
  missing or not a commit sha (a placeholder such as `pending`, or a name that
  moves such as `HEAD` or a branch), or the source did not exist at
  that commit
- ❔ unknown — drift cannot be measured: no git history for the source (a copy
  without `.git`, or an EN file not committed yet), or `source_commit` is a sha
  this clone does not have (shallow clone)
- ❌ missing — an EN source has no translation in this language yet
- ℹ️ orphan — the translation has no `translation_of`, or its source is gone

Two differences never count: line endings, and the version number on a line
with a `img.shields.io/badge/` badge (a release rewrites the README badge; the
translation keeps its own, which the release process bumps — see
`docs/MAINTENANCE.md`). A commit that touched a source without changing its
text is not drift either.

`--strict` exits 1 unless every file is ✅ in sync, so ❔ unknown fails it too.
`--json` prints the same records for tools.

## How to add a new language

1. Choose a 2-letter ISO 639-1 code (e.g., `de`, `es`, `ja`, `pt-br`).
2. `mkdir -p i18n/<code>/knowledge-base i18n/<code>/quick-start`
3. Copy the canonical files you translate into the same paths under
   `i18n/<code>/` (`README.md`, `knowledge-base/*.md`, `quick-start/*.md`).
4. For each file, replace English text with translated text, **add the frontmatter** described above.
5. Stamp the frontmatter: `python3 scripts/sync_translations.py --to-source --lang <code>`.
6. Run `python3 scripts/check_translations.py --update-status` — every EN
   source you have not translated yet is listed as ❌ missing.
7. Update top-level `README.md` to link to the new language landing page.

## How to keep translations fresh

When you change a canonical EN file:

1. Note the file in the CHANGELOG under "Translation impact".
2. `python3 scripts/check_translations.py` — see which `i18n/*/...` files became stale.
3. (Recommended) Update the impacted translations in the same PR. If not, mark them as known-stale.
4. After updating translations to match, stamp exactly those files. A run
   over the whole language would also re-stamp the stale translations nobody
   updated and hide their drift:

   ```bash
   git commit -m "..."          # commit canonical EN changes first
   python3 scripts/sync_translations.py --to-source --files i18n/ru/README.md i18n/ru/knowledge-base/04_REVIEW.md
   git commit -am "i18n: sync RU to the EN sources"
   python3 scripts/check_translations.py --update-status
   ```

### What `sync_translations.py` stamps

It edits only the leading frontmatter block — never the body, and never a key
that is not in the frontmatter: the file's output line names the missing keys
(add them by hand).

- `source_commit` — with one of three mutually exclusive flags:
  - `--to-source` (the usual choice): per file, the commit that last touched
    its EN source, resolved from `translation_of:`. A file whose source has
    uncommitted edits is skipped (`SKIP … commit it first`), since the stamp
    could not cover them. Idempotent: a correct `source_commit` is left alone,
    and so is a sha whose source changed since then only in ways the checker
    ignores (line endings, a badge version) — `NOOP … (no drift since
    source_commit)`, so a release bump never re-dates a translation.
  - `--to-commit <rev>`: one explicit revision (sha, tag, `HEAD~2`) for the
    whole batch; a revision git cannot resolve is an error.
  - `--to-head`: the current HEAD. The checker compares text, so this is right
    whenever the EN sources are committed; `--to-source` additionally records
    which commit last changed each source.
- `source_version` and `translated_at` — the explicit `--to-version` /
  `--to-date YYYY-MM-DD` on every target; otherwise the repo `VERSION` and
  today's date, and only on files whose `source_commit` this run changes.

Without any of `--to-source`, `--to-commit`, `--to-head`, `--to-version`,
`--to-date` it stamps nothing and exits 1. `--files` accepts only paths under
`i18n/`; `--dry-run` shows what would change. Files keep their line endings.

## `TRANSLATION_STATUS.md`

`i18n/TRANSLATION_STATUS.md` is the output of
`python3 scripts/check_translations.py --update-status`. It carries no HEAD sha
or date, so an unrelated commit does not make it outdated; it changes only when
a translation's state or drift changes, and the command leaves an up-to-date
file untouched. Regenerate and commit it together with translation updates.

## Pre-commit hook (optional)

`scripts/hooks/pre-commit-translation-drift.sh` warns — never blocks — when a
canonical EN file is staged without its `i18n/<lang>/` translation, and when
an EN file is deleted or renamed while its translation stays behind. It covers
the same set as the checker (including the root `README.md`) and prints paths
verbatim, spaces and `%` included. Install it from the repo root:

```bash
chmod +x scripts/hooks/pre-commit-translation-drift.sh
ln -sf "$(pwd)/scripts/hooks/pre-commit-translation-drift.sh" "$(git rev-parse --git-path hooks)/pre-commit"
```

## What to translate vs. keep verbatim

**Translate:**
- Prose, headings, tables, descriptions
- User-facing messages, examples
- Comments in YAML/code blocks (only if they are documentation; not if they are real code)

**Keep verbatim:**
- Code samples, file paths, command names (`kb_ingest.py`, `npm install -g repomix`)
- Frontmatter keys (`source`, `extracted_at`, `lifecycle`)
- Brand names, URLs
- YAML config keys and values that the system parses (`mode_profiles.default.surprise.engine: python`)

## Style guidance

- Match the tone of the source: technical but accessible.
- Localize idioms, but preserve technical precision.
- For Russian: follow standard tech-writing conventions (Тб vs ТБ, Markdown vs `Markdown`, etc.).
- Don't add or remove sections without flagging it in the frontmatter (`translator: human` + brief note in CHANGELOG if substantive).
