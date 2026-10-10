# 09 — Lint: periodic health-check of the knowledge base

> The lint operation checks the health of an **existing** base. Unlike review (04), which handles incoming materials, lint analyzes what is already in `knowledge/`.
>
> **Reference implementation:** `knowledge-base/scripts/kb_lint.py`. The agent copies this script during deployment.

---

## Why

A knowledge base degrades without maintenance: facts age, pages lose links, contradictions creep in. Lint catches these issues before the AI agent starts answering from stale data.

---

## Two levels of checks

### Level 1: automatic (Python)

Run by `scripts/kb_lint.py` — deterministic, no LLM. The name in the first
column is what `--only` accepts and what the report prints in brackets.

| Check | What it does | Severity |
|-------|--------------|----------|
| `frontmatter` | All `knowledge/` files have the required fields `source`, `extracted_at`, `tags`, `lifecycle`, and `lifecycle` is `permanent` / `evolving` / `temporal`. Also reports **`frontmatter-yaml`** — the frontmatter does not parse (invalid YAML, not a mapping, no closing `---`); `--fix` never touches such a page — and **`frontmatter-type`** — `source` / `source_hash` not a string, `supersedes` not a slug/path or list of them, `citations` not a list of mappings | 🔴 error |
| `stale` | The newer of `last_verified` / `extracted_at` is older than `lifecycle.stale_warning_days` (default 30). **Never** for `_archive/`, generated pages (`generated_by:`), effective lifecycle `permanent`, or `valid_until` ≥ today; a page with neither date is not stale. The same rule (`kb_common.stale_status`) drives the graph viewer | 🟡 warning |
| `broken-link` | A `[[wikilink]]` resolves to no knowledge page. Matching is case-insensitive; `[[page#section]]`, `[[page.md]]`, `[[page\|alias]]`, `[[knowledge/domain/page]]` and a partial path such as `[[sub/page]]` (matched by its end, as Obsidian does) resolve; embeds (`![[diagram.png]]`) and links inside code are ignored | 🔴 error |
| `orphan` | A page has no inbound `[[wikilink]]` from any other page. Skips `routing/`, `routing-table.md`, `_archive/` and generated pages | 🟡 warning |
| `source-hash` | `source_hash` differs from the source file's actual hash (a missing source file is a warning; a `source:` that leads outside the base — `..`, an absolute path or a symlink — is a warning and is never read). **Skips** effective lifecycle `permanent`. Hashes are cached in `.kb-state/lint-hash-cache.json` and recomputed only when the source's size or mtime changes | 🔴 error |
| `empty-category` | A **custom** `knowledge/` subfolder without any `.md`. The stock folders `kb_ingest.py --init-dirs` creates are compatibility shelves and are never reported | 🟡 warning |
| `superseded` | Page A `supersedes: B` (a slug, a path, or a list of them), but B is not in `_archive/`. **Skips** B when its effective lifecycle is `permanent` | 🟡 warning |
| `duplicate-slug` | Two files outside `_archive/` share a slug (case-insensitive) in different subfolders | 🔴 error |
| `citation` | A `citations[].source_span` names no file inside the base, or its `#Lx-Ly` span ends past the file's last line; a citation without `source_span` is reported too. Other span formats (`#page=`, `#section=`, timecodes) are checked for the file only | 🟡 warning |
| `domain-overflow` | A `knowledge/` subfolder contains > 15 `.md`, not counting pages in any `_archive/` folder → suggest consolidation | 🟡 warning |
| `low-importance` | `importance` < 3 + effective lifecycle `temporal` + `last_accessed` more than 90 days ago (without `last_accessed`: the newer of `last_verified` / `extracted_at`) → suggest moving it to `_archive/`. Skips `_archive/` and generated pages | ℹ️ info |
| `annotation-overflow` | A file has > 5 `context_annotations` → suggest creating an insight | ℹ️ info |
| `expired-temporal` | Effective lifecycle `temporal` + `valid_until` < today + file not in `_archive/` | 🟡 warning |
| `invariants` | `AGENTS.md` is missing a required `AI-KE:INVARIANT` block (`forbidden`, `language`) or markers are malformed. Skips if `AGENTS.md` is absent | 🔴 error |
| `agents-bytes` | The **deployed** `AGENTS.md` larger than `instructions_lint.agents_max_bytes` (default 10240 / 10 KiB) → propose `!refactor`. The stock template already contains every managed block (INDEX, STATUS, VIEW) and stays within 9 KiB, leaving room for the base's own additions | 🟡 warning |
| `instruction-absolutes` | `always` / `never` / `must` / `forbidden` — and the Russian `всегда` / `никогда` / `обязательно` / `запрещено` / `запрещается` / `нельзя` — outside INVARIANT blocks exceed `absolute_max_outside_invariants` (default 8) | 🟡 warning |
| `work-ordering` | Any configured phrase, matched case-insensitively (`thoroughly`, `consider all`, `максимально тщательно`, …) — these inflate reasoning, not accuracy | 🟡 warning |
| `instruction-duplicates` | `AGENTS.md` restates `privacy.*` or `language_policy` already in `kb.config.yml`. Text **inside** `AI-KE:INVARIANT` blocks is exempt — a copy there is deliberate, it has to survive every trim | ℹ️ info |
| `instructions-review` | `instructions_review.reviewed_at` older than `review_stale_days` (default 90). **Skips** if the field is missing. Procedure: `17_REFACTOR.md` | 🟡 warning |
| `assumption-hotspot` | More than 3 `## Assumptions` bullets naming one `knowledge/<area>/` in 30 days → tighten `DATA_PLACEMENT_EXAMPLES.md` | ℹ️ info |
| `profile-review` | `profile_review.reviewed_at` older than 30 days. **Skips** if the field is missing. Procedure: `!profile-review` | 🟡 warning |
| `secret` | A `knowledge/` page (frontmatter included) holds credential-looking text — the `privacy.secret_scan` patterns ingest uses: GitHub / Slack / Stripe / OpenAI-style tokens, AWS access keys, private-key headers (error), and `password:` / `secret=` style assignments (warning: prose about passwords can match). Reports the kind and line numbers, never the value. repomix's security check silently leaves such a page out of its pack, and `knowledge/` is committed: remove the value (keep a placeholder such as `<redacted>`) or move the page to `review/needs-redaction/`. Off when `privacy.secret_scan: false` | 🔴 error / 🟡 warning |

Two more names can appear in a report without being `--only` checks:
`unreadable` (the page is not UTF-8 text) and `config` (`kb.config.yml` does
not parse — lint then runs with the code defaults).

**Effective lifecycle** is the page's own `lifecycle` when it is set to
something other than `lifecycle.default`; otherwise the deepest matching
`lifecycle.by_folder` entry (default: `decisions`, `profile`, `principles` →
`permanent`), otherwise `lifecycle.default` (`evolving`). So a decision page
that `--fix` or a template filled with `lifecycle: evolving` is still treated
as permanent, and an explicit `lifecycle: temporal` wins over the folder.

A page that makes a check fail is reported **on that page** (an error under
that check's name) and the run goes on; one odd page never stops lint.

Thresholds for the instruction-budget checks live in top-level
`instructions_lint:` in `kb.config.yml`, not in the script and not under
`mode_profiles.*.lint` (that block is Level 2).

### Level 2: AI review (LLM) — mode-aware

> ⚠️ **Cost:** 50–100K tokens for a full pass (all `knowledge/` files in context).

Level 2 is agent work; no script schedules it. The agent reads
`mode_profiles.<mode>.lint` from `kb.config.yml`:

#### `mode: default`
- Runs **only** on `!audit`
- `level2_weekly_day` is reserved for a weekly schedule that is not
  implemented yet (see `docs/ROADMAP.md`)

#### `mode: super`
- `level2_trigger: "daily"` — agent policy, not a schedule: the agent may
  offer `!audit` at session start and starts after the owner says yes. The
  daily consolidation in `kb_reindex.py` is a script and never starts the
  agent (`kb-docs/13_AUTORUN.md`)
- `review_auto_process: true` — when `STATUS.md` shows `needs-ai-decision`
  items, the agent offers `!review` at session start and starts after the
  owner says yes (`kb-docs/04_REVIEW.md`)

```yaml
# In kb.config.yml — read by the AI agent:
mode_profiles:
  default:
    lint:
      level2_trigger: "manual"       # manual | weekly | daily
      level2_weekly_day: "sunday"    # not implemented yet
      review_auto_process: false
  super:
    lint:
      level2_trigger: "daily"
      review_auto_process: true
```

| Check | What it does |
|-------|--------------|
| **Contradictions** | Find pages with conflicting claims |
| **Missing cross-refs** | Pages on similar topics with no links between them |
| **Data gaps** | Areas where knowledge is too thin for confident answers |
| **Consolidation candidates** | Pages worth merging |
| **Freshness recommendations** | Which pages should be re-verified/updated |

---

## lint-report format

`--output report` writes `lint-report.md`; without it the same text goes to
stdout. `--json` prints `root`, `scope`, `pages_scanned`, `issues` (`check`,
`severity`, `path`, `message`, `fixable`), `fixed`, `metrics`, `exit_code`.

```markdown
# Lint Report — 2026-05-06

## Summary
- Pages scanned: 42
- Errors: 2
- Warnings: 3
- Info: 1
- Auto-fixed: 0

## 🔴 Errors
- **[frontmatter]** `knowledge/domain/caching.md` — missing required fields: extracted_at *(fixable)*
- **[broken-link]** `knowledge/principles/architecture.md` — [[infrastructure-scaling]] does not resolve

## 🟡 Warnings
- **[stale]** `knowledge/projects/highway-clicker.md` — last_verified 2026-03-15 is 52 days old (threshold: 30)
- **[orphan]** `knowledge/domain/nats-evaluation.md` — no inbound wikilinks from any other knowledge page
- **[superseded]** `knowledge/domain/redis-caching.md` — superseded by knowledge/domain/dragonfly-caching.md but not in _archive/

## ℹ️ Info
- **[low-importance]** `knowledge/projects/q1-offsite.md` — importance 2, temporal, last_accessed 2026-01-10 (116 days ago) — consider moving it to knowledge/_archive/
```

A `--quick` run adds `- Mode: quick (error-level checks only)` to the
summary, an `--only` run `- Mode: partial (--only)`.

---

## `scripts/kb_lint.py` contract

```text
Usage:
    python3 scripts/kb_lint.py                          # Full lint
    python3 scripts/kb_lint.py --quick                  # Only the checks that can report an error
    python3 scripts/kb_lint.py --fix                    # Add missing frontmatter fields
    python3 scripts/kb_lint.py --output report          # Write to lint-report.md
    python3 scripts/kb_lint.py --only frontmatter       # Run a subset of checks
    python3 scripts/kb_lint.py --json                   # Machine-readable output
    python3 scripts/kb_lint.py --metrics                # Add health metrics
    python3 scripts/kb_lint.py --stale-days 60          # Override lifecycle.stale_warning_days
    python3 scripts/kb_lint.py --log                    # Also record the run in log.md

Exit codes:
    0 — no issues
    1 — warnings or info only
    2 — at least one error (a crash of the script itself also exits 2)
```

A broken install is a crash too: when `scripts/kb_common.py` is older than
`kb_lint.py` (a partial upgrade that kept a customized `kb_common.py` and
left `kb_common.py.new` beside it), lint prints the missing names and exits 2.
A folder without `kb.config.yml` is not a base: lint says so, writes nothing
and exits 2.

`--quick` runs `frontmatter`, `broken-link`, `source-hash`, `duplicate-slug`,
`invariants` and `secret` — the only checks with error severity — and prints
errors only. `kb_reindex.py` runs it as a step of its pipeline.

### Auto-fix capabilities

`--fix` does exactly one thing: it adds missing frontmatter fields with
defaults — `lifecycle: <lifecycle.default>` (`evolving`), `tags: []`,
`extracted_at: <today>`. `source` is never invented. A page whose frontmatter
does not parse (`frontmatter-yaml`) is left byte-for-byte alone.

Everything else is for the AI agent or the owner:
- Refresh `last_verified` after re-verifying a page
- Move superseded or expired pages to `knowledge/_archive/` (never `permanent` ones)
- Repair or remove broken wikilinks
- Resolve contradictions, create cross-references, decide deletion/merge
- Change `lifecycle` (only on an explicit user request)

---

## Running lint

`shell/lint.sh` runs `scripts/kb_lint.py` from the base root and passes every
argument and the exit code through. The interpreter comes from
`shell/_kbpy.sh`: `$KB_PYTHON`, else the base's `.venv`, else `python3`
(`shell/doctor.sh` works the same way for `kb_doctor.py`):

```bash
./shell/lint.sh                  # full lint
./shell/lint.sh --output report  # lint-report.md
./shell/lint.sh --log            # and a `lint` entry in log.md
```

### What a run leaves behind

- **`.kb-state/lint-summary.json`** — every CLI run without `--only` writes
  `{"errors", "warnings", "infos", "at", "scope", "full_at"}` (read by
  `kb_status.py` for `STATUS.md`). A `--quick` run measures errors only, so it
  keeps the warning and info counts of the last full run; `full_at` says when
  that run was. `--only` runs write nothing.
- **`.kb-state/lint-hash-cache.json`** — the source-hash cache (above).
- **`log.md`** — only with `--log`. Lint runs on every reindex; logging each
  of them would bury the log.

---

## Mutation check (`kb_mutate.py`)

Copies the base (plus a tiny seed cluster) into a temp tree, plants **seven**
L1 defects, and scores lint:

broken wikilink, duplicate slug, `source_hash` mismatch, stale
`last_verified` + `extracted_at`, orphan, expired `valid_until`, missing
frontmatter field.

A mutation counts as killed only when its check fires **on the page the
mutation touched** — an unrelated issue elsewhere in the copied base does not
count.

```bash
python3 scripts/kb_mutate.py
python3 scripts/kb_doctor.py --with-mutation   # not in the default doctor run
```

Report line: `7 mutations / 7 killed / 0 survivors`. Survivors mean that L1
check does not see a real defect — fix the check or record the limit.
L2 contradictions are not planted here; that is `!audit`.

---

## Environment check (`kb_doctor.py`)

Lint checks the knowledge; `kb_doctor.py` (`./shell/doctor.sh`) checks the
installation. It never writes to the base (no `log.md` entry).

**Doctor passes = exit code 0.** Warnings (`⚠️`) are advice and do not fail
it; exit code 2 means at least one error (`❌`). The summary line ends with
`PASS` or `FAIL` accordingly. A check that crashes becomes one error and the
others still run; a crash of doctor itself, or a `kb_common.py` that does
not import at all, also exits 2.

Besides Python packages, folders, `kb.config.yml`, the Codex / Claude Code
instruction files, spaCy, media backends, sync folders, heal state and
`repomix.config.json`, it checks:

| Check | Error when | Warning when |
|-------|------------|--------------|
| `index:repomix` | no `repomix`, and no `npx` + `node` for the pinned fallback (`index.repomix_version`, `index.npx_fallback`) | — |
| `index:packs` | a pack is `FAILED` in `.repomix/PACKS_STATUS.md`, or the file says `Index not built` | no index built yet; a pack not rebuilt (`STALE` — repomix was unavailable); `knowledge/` changed after the last reindex; a pack over the ceiling (`⚠ OVER`); files repomix left out of a pack ("Left out by repomix": its security check, or an ignore file); no pack row could be read |
| `scripts:consistency` | a `scripts/kb_*.py` does not import, or uses a `kb_common` name that `scripts/kb_common.py` lacks (a partial upgrade; doctor itself still runs against the older `kb_common.py`) | — |
| `upgrade:sidecars` | — | unmerged `.new` files from `kb_upgrade` → `!heal` |
| `kb-docs` | `AGENTS.md`, `CLAUDE.md`, `START_HERE.md` or `KNOWLEDGE_STRUCTURE.md` points to a `kb-docs/NN_*.md` that is missing | no `kb-docs/` at all (a base from before 0.16) |
| `agent-env:claude-md-import` | — | `CLAUDE.md` lacks `@AGENTS.md`; or `index.primary_agent: claude-code` and there is no `CLAUDE.md` (Claude Code would not load `AGENTS.md`) |
| `venv:*` | — | no `.venv` for the base (`venv:missing` — the wrappers, launchers and git hook run `python3`, so optional packages go unused); a venv they never use: `knowledge-base/.venv` left after `finalize.sh`, or the venv doctor runs in (`venv:stranded`); `.venv/.venv` (nested venv); `.venv` moved (`activate` or `bin/pip` point to the old place); doctor itself runs outside the base venv |
| `nlp:nltk-data` | — | `rake-nltk` is installed but the NLTK `stopwords` / `punkt` data is not |
| `log:writable` | `log.md` (or the base root) is not writable — checked without writing | — |

`--self-test` (run against the engine's own `knowledge-base/` folder) skips
the deployment checks: Codex environment, index, `kb-docs/`, venv and heal.
`--skip-nlp` skips spaCy and the NLTK data probe.

---

## Recommended frequency

| Mode | Frequency | Who runs it |
|------|-----------|-------------|
| `--quick` | Every reindex | Automatically (`kb_reindex.py`, `shell/reindex.sh`) |
| Full lint | Weekly | Manual or cron |
| AI review (level 2) | Monthly | AI agent in IDE on demand |

---

## Integration with other modules

- **03_PIPELINE:** ingest writes frontmatter with `source_hash` → lint verifies
- **05_INDEX:** lint validates wikilinks → index updates
- **10_LOG:** `kb_lint.py --log` records a run in `log.md`
- **11_PROVENANCE:** lint checks source hashes, citation files/line spans and lifecycle rules
- **13_AUTORUN:** cron/watch runs `--quick` on changes
