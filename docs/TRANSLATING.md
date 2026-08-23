# Translating AI Knowledge Engine

> Guide for adding or maintaining a translation of instruction modules.

## Canonical source

**English is canonical.** Files in `knowledge-base/*.md` and `quick-start/*.md` are the source of truth. Translations live in `i18n/<lang>/` and mirror the source structure.

```
ai-knowledge-engine/
├── knowledge-base/                ← canonical EN
│   ├── 00_OVERVIEW.md
│   ├── 01_PREREQUISITES.md
│   └── ...
├── quick-start/
│   └── INIT_GUIDE.md
└── i18n/
    ├── TRANSLATION_STATUS.md      ← auto-generated drift report
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
| `source_commit` | Git SHA of the source file at translation time |
| `source_version` | Repo `VERSION` at translation time |
| `translated_at` | ISO-8601 date |
| `translator` | `human` \| `ai-assisted` \| `machine` |

The drift checker reads these headers and emits status:
- ✅ in sync — `source_commit` matches the source file's last-touched commit
- ⚠️ stale — source has been edited since `source_commit`
- ❌ missing — translation does not exist yet

## How to add a new language

1. Choose a 2-letter ISO 639-1 code (e.g., `de`, `es`, `ja`, `pt-br`).
2. `mkdir -p i18n/<code>/knowledge-base i18n/<code>/quick-start`
3. Copy the canonical structure: `cp -r knowledge-base/*.md i18n/<code>/knowledge-base/` and likewise for `quick-start/`.
4. For each file, replace English text with translated text, **add the frontmatter** described above.
5. Translate `README.md` separately to `i18n/<code>/README.md`.
6. Run `python3 scripts/check_translations.py --update-status` (Phase 2.4).
7. Update top-level `README.md` to link to the new language landing page.

## How to keep translations fresh

When you change a file in `knowledge-base/`:

1. Note the file in the CHANGELOG under "Translation impact".
2. `python3 scripts/check_translations.py` — see which `i18n/*/...` files became stale.
3. (Recommended) Update the impacted translations in the same PR. If not, mark them as known-stale.
4. After updating translations to match, bump their `source_commit`:

   ```bash
   git commit -m "..."          # commit canonical EN changes
   python3 scripts/sync_translations.py --to-source --lang ru
   git commit -am "i18n: sync RU to the EN sources"
   python3 scripts/check_translations.py --update-status
   ```

   Steps 2–4 can also be done as a single atomic PR if you update the
   translations and run `sync_translations.py` before the first commit.

### Use `--to-source`, not `--to-head`

`check_translations.py` calls a file in sync when its `source_commit` equals
the commit that **last touched that EN source file**. `--to-head` stamps the
tip instead, which is the same thing only while the commit that changed the
sources is still the tip. Land anything on top of it — a follow-up docs
commit, a merge — and every file gets stamped with a commit that never touched
it, and the report reads `⚠️ stale … (0 commits)`: marked, but not actually in
sync.

`--to-source` resolves that commit per file from `translation_of:`, which is
the same question the checker asks, so it is right regardless of what landed
afterwards. It is also idempotent — re-running it changes no `source_commit`
that is already correct. When you need one explicit revision for the whole
batch, use `--to-commit <rev>` (accepts a sha, tag, or `HEAD~2`).

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
