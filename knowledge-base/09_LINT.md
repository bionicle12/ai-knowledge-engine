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

Run by `scripts/kb_lint.py` — deterministic, no LLM.

| Check | What it does | Severity |
|-------|--------------|----------|
| **Frontmatter integrity** | All `knowledge/` files have required fields: `source`, `extracted_at`, `tags`, `lifecycle` | 🔴 error |
| **Stale pages** | `last_verified` older than 30 days. **Skips** `lifecycle: permanent` | 🟡 warning |
| **Broken wikilinks** | `[[slug]]` points to a non-existent file | 🔴 error |
| **Orphan pages** | Pages with no inbound `[[wikilink]]` from any other page | 🟡 warning |
| **Source hash mismatch** | `source_hash` differs from the asset's actual hash. **Skips** `lifecycle: permanent` | 🔴 error |
| **Empty categories** | `knowledge/` subfolders without any `.md` | 🟡 warning |
| **Superseded chains** | File A `supersedes: B`, but B is not in `_archive/`. **Does not touch** `lifecycle: permanent` | 🟡 warning |
| **Duplicate slugs** | Two files with the same slug in different subfolders | 🔴 error |
| **Citation validity** | Span-level citations point to existing files/lines | 🟡 warning |
| **Domain overflow** | A `knowledge/` subfolder contains > 15 `.md` → suggest consolidation | 🟡 warning |
| **Low importance + stale** | `importance < 3` + `lifecycle: temporal` + `last_accessed > 90 days` → suggest archive | ℹ️ info |
| **Annotation overflow** | A file has > 5 `context_annotations` → suggest creating an insight | ℹ️ info |
| **Expired temporal** | `valid_until != null` + `valid_until < now` + file not in `_archive/` | 🟡 warning |
| **Invariants** | `AGENTS.md` is missing a required `AI-KE:INVARIANT` block (`forbidden`, `language`) or markers are malformed. Skips if `AGENTS.md` is absent | 🔴 error |
| **AGENTS.md bytes** | The **deployed** `AGENTS.md` larger than `instructions_lint.agents_max_bytes` (default 10240 / 10 KiB) → propose `!refactor`. The stock template is smaller than that on purpose: `kb_upgrade` appends the managed `!view` block to the deployed file | 🟡 warning |
| **Instruction absolutes** | `always` / `never` / `must` / `forbidden` outside INVARIANT blocks exceed `absolute_max_outside_invariants` (default 8) | 🟡 warning |
| **Work-ordering phrases** | Any configured phrase, matched case-insensitively (`thoroughly`, `consider all`, `максимально тщательно`, …) — these inflate reasoning, not accuracy | 🟡 warning |
| **Instruction duplicates** | `AGENTS.md` restates `privacy.*` or `language_policy` already in `kb.config.yml`. Text **inside** `AI-KE:INVARIANT` blocks is exempt — a copy there is deliberate, it has to survive every trim | ℹ️ info |
| **Instructions review** | `instructions_review.reviewed_at` older than `review_stale_days` (default 90). **Skips** if the field is missing. Procedure: `17_REFACTOR.md` | 🟡 warning |
| **Assumption hotspot** | More than 3 `## Assumptions` bullets naming one `knowledge/<area>/` in 30 days → tighten `DATA_PLACEMENT_EXAMPLES.md` | ℹ️ info |
| **Profile review** | `profile_review.reviewed_at` older than 30 days. **Skips** if the field is missing. Procedure: `!profile-review` | 🟡 warning |

Thresholds for the instruction-budget checks live in top-level
`instructions_lint:` in `kb.config.yml`, not in the script and not under
`mode_profiles.*.lint` (that block is Level 2).

### Level 2: AI review (LLM) — mode-aware

> ⚠️ **Cost:** 50–100K tokens for a full pass (all `knowledge/` files in context).

#### `mode: default`
- Runs **only** on `!audit` or weekly
- No more than once per week

#### `mode: super`
- Runs **automatically** on every consolidation (every 24h)
- The AI also auto-processes `review/needs-ai-decision/`

```yaml
# In kb.config.yml — driven via mode_profiles:
lint:
  # default profile:
  level2_trigger: "manual"       # manual | weekly | daily
  level2_weekly_day: "sunday"
  # super profile:
  # level2_trigger: "daily"      # on every consolidation
  review_auto_process: false     # default: false, super: true
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

```markdown
# Lint Report — 2026-05-06

## Summary
- Total pages: 42
- Errors: 3
- Warnings: 7
- Info: 2

## 🔴 Errors

### [FRONTMATTER] knowledge/domain/caching.md
Missing required field: `extracted_at`

### [BROKEN_LINK] knowledge/principles/architecture.md:15
Link [[infrastructure-scaling]] → file not found

### [SOURCE_HASH] knowledge/domain/redis-patterns.md
source_hash mismatch: expected sha256:a1b2c3, actual sha256:d4e5f6
→ Source file was updated, knowledge page may be stale

## 🟡 Warnings

### [STALE] knowledge/projects/highway-clicker.md
last_verified: 2026-03-15 (52 days ago, threshold: 30)

### [ORPHAN] knowledge/domain/nats-evaluation.md
No inbound [[wikilinks]] from any page

### [EMPTY_CATEGORY] knowledge/timelines/
No .md files in this category

## ℹ️ Info

### [SUPERSEDED] knowledge/decisions/2026-01__initial-db-choice.md
Superseded by knowledge/decisions/2026-03__postgres-migration.md
Consider moving to knowledge/_archive/
```

---

## `scripts/kb_lint.py` contract

```python
"""
kb_lint.py — Automated health-check for the knowledge base.

Usage:
    python3 scripts/kb_lint.py                          # Full lint
    python3 scripts/kb_lint.py --quick                  # Errors only
    python3 scripts/kb_lint.py --fix                    # Auto-fix where possible
    python3 scripts/kb_lint.py --output report          # Write to lint-report.md
    python3 scripts/kb_lint.py --only frontmatter       # Run a subset of checks
    python3 scripts/kb_lint.py --json                   # Machine-readable output

Exit codes:
    0 — no errors
    1 — warnings only
    2 — errors found
"""
```

### Auto-fix capabilities

With `--fix`, the script can:
- Add missing frontmatter fields with defaults (lifecycle default: `evolving`)
- Refresh `last_verified` for verified pages
- Move superseded files to `knowledge/_archive/` (**only** `evolving`/`temporal`, **not** `permanent`)
- Remove broken wikilinks (replace with plain text)

Auto-fix **cannot** (requires AI or human):
- Resolve contradictions
- Create cross-references
- Decide deletion/merge
- Change `lifecycle` without explicit user request
- Archive `lifecycle: permanent` files

---

## Running lint

```bash
# lint.sh — wrapper
#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Running knowledge base lint..."
if [ -f ".venv/bin/python" ]; then
  .venv/bin/python scripts/kb_lint.py "$@"
else
  python3 scripts/kb_lint.py "$@"
fi

# Append to log
echo "" >> log.md
echo "## [$(date -Iseconds)] lint | Automated health-check" >> log.md
echo "- Mode: $*" >> log.md
echo "- Report: see lint-report.md" >> log.md
```

```bash
chmod +x lint.sh
```

---

## Mutation check (`kb_mutate.py`)

Copies the base (plus a tiny seed cluster) into a temp tree, plants **seven**
L1 defects, and scores lint:

broken wikilink, duplicate slug, `source_hash` mismatch, stale
`last_verified`, orphan, expired `valid_until`, missing frontmatter field.

```bash
python3 scripts/kb_mutate.py
python3 scripts/kb_doctor.py --with-mutation   # not in the default doctor run
```

Report line: `7 mutations / 7 killed / 0 survivors`. Survivors mean that L1
check does not see a real defect — fix the check or record the limit.
L2 contradictions are not planted here; that is `!audit`.

---

## Recommended frequency

| Mode | Frequency | Who runs it |
|------|-----------|-------------|
| `--quick` | Every reindex | Automatically (in `reindex.sh`) |
| Full lint | Weekly | Manual or cron |
| AI review (level 2) | Monthly | AI agent in IDE on demand |

---

## Integration with other modules

- **03_PIPELINE:** ingest writes frontmatter with `source_hash` → lint verifies
- **05_INDEX:** lint validates wikilinks → index updates
- **10_LOG:** every lint run is recorded in `log.md`
- **11_PROVENANCE:** lint checks citation validity, source hashes, and lifecycle rules
- **13_AUTORUN:** cron/watch runs `--quick` on changes
