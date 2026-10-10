# 10 — Operations log (chronology)

> The append-only `log.md` records operations against the knowledge base: ingest, review, query-writeback, session-capture, reflection, heal, merges. It is the single timeline of base evolution.

---

## Why

- The AI agent can see **what happened** to the base in chronological order
- Quickly answer: when was the last review, what was added, what changed
- Parsable by Unix utilities for fast search
- Keeps operational history separate from knowledge content

---

## Location

```
<base root>/
├── log.md         # ← append-only, NOT indexed by Repomix
└── log-archive/   # ← rotated older entries (see Rules)
```

The stock `repomix.config.json` already excludes `log.md`, `log-archive/**`
and `lint-report.md` from the index (`ignore.customPatterns`).

---

## Entry format

Each entry starts with a level-2 heading in this exact format:

```
## [ISO-timestamp] operation-type | Human-readable title
```

Scripts write entries through `kb_common.append_log`, which fills the
timestamp (local time with offset) and turns `details` into bullets.

### Operation types

| Type | When | Written by |
|------|------|------------|
| `ingest` | A new raw file was processed by the pipeline | `kb_ingest.py` (once per file) |
| `ingest-duplicate` | A raw file repeated an existing asset and was moved to `ingest.duplicates_dir` | `kb_ingest.py` |
| `reprocess` | An existing asset was processed again | `kb_ingest.py` |
| `nlp-batch` | Batch NLP enrichment of `processed/` refreshed at least one file | `kb_nlp_batch.py` |
| `lint` | A health-check ran | `kb_lint.py --log` only |
| `reflect-request` | The reflection threshold was met and reflection requested | `kb_reflect.py --generate` |
| `reflect` | A reflection finished (`insights: N`, 0 is valid) | `kb_reflect.py --record-result N` |
| `heal` | Catch-up after upgrade applied auto fixes | `kb_heal.py` |
| `export` | A sync bundle was written | `kb_export.py` |
| `import` | A sync bundle was merged | `kb_import.py` |
| `import-undo` | A merged bundle was rolled back | `kb_import.py --undo` |
| `populate` | `DATA_PLACEMENT_EXAMPLES.md` was generated from a role file | `kb_populate.py` (in a base with `kb.config.yml`) |
| `review` | AI processed a `review/` or `processed/` item | `kb_ingest.py --mark-extracted` / `--mark-skipped`, or the AI agent |
| `query-writeback` | A valuable answer was saved into `knowledge/` | AI agent |
| `session-capture` | A session summary was written to `interactions/` | `kb_save_session.py`, or the AI agent |
| `meta-review` | A meta-review of session summaries finished (`!meta-review`): sessions analyzed, insights written | AI agent |
| `update` | Manual edit of a `knowledge/` page | AI agent |
| `archive` | A page was moved to `_archive/` | AI agent |
| `refactor` | Instruction trim (`!refactor` / `17_REFACTOR.md`) | AI agent |
| `quiz` | Owner exam (`!quiz`) — answers in `interactions/quiz/` | AI agent |

`kb_ingest.py --mark-extracted` / `--mark-skipped` title their `review` entry
`extracted: <asset file>` / `skipped: <asset file>`. An entry about a file from
a private category (`privacy.redact_categories`, or one under privacy review)
never names the file: its title is `<category> item <sha8>` (the same heading
as its `assets-index/` block) and its bullets leave out the asset paths.

`kb_doctor.py`, `kb_reindex.py`, `kb_route.py` and `kb_mutate.py` do not
write to the log.

---

## Example entries

```markdown
# Operations Log

## [2026-05-06T20:30:00+03:00] ingest | 2026-05-06__karpathy-llm-wiki.md
- Source hash: sha256:3f2a9c0e71b4d5a8
- Asset: assets/documents/2026-05-06__karpathy-llm-wiki.md
- Processed: processed/markdown/2026-05-06__karpathy-llm-wiki.md
- NLP meta: processed/nlp-meta/2026-05-06__karpathy-llm-wiki.yml
- Complexity: 0.65

## [2026-05-06T21:00:00+03:00] lint | Health-check
- Mode: full
- Checked: 42 pages
- Errors: 1
- Warnings: 3
- Info: 0
- Auto-fixed: 0
- Report: lint-report.md

## [2026-05-07T10:15:00+03:00] query-writeback | Docker Swarm vs K8s comparison
- Question: "Why Docker Swarm instead of K8s at our scale?"
- Created: knowledge/decisions/2026-05-07__swarm-vs-k8s.md
- Cross-refs added: [[docker-swarm]], [[infrastructure-decisions]]
- Confidence: medium

## [2026-05-07T14:00:00+03:00] session-capture | highway-clicker auth refactor
- Project: highway-clicker
- Session: interactions/sessions/2026-05-07__highway-clicker__auth/
- Duration: ~45 min
- Insights extracted: 2
- Knowledge updated: knowledge/playbooks/auth-implementation.md
```

The exact bullets of a script entry are whatever that script writes; the
heading format is the contract.

---

## Quick search

```bash
# Last 10 operations
grep "^## \[" log.md | tail -10

# All ingest entries in May
grep "^## \[2026-05" log.md | grep "ingest"

# All logged lint runs that found errors
grep -A5 "^## \[.*\] lint |" log.md | grep -B3 "Errors: [1-9]"

# How many of each operation type
grep "^## \[" log.md | sed 's/.*\] //' | sed 's/ |.*//' | sort | uniq -c | sort -rn
```

---

## Rules

1. **Append-only:** entries are NOT edited and NOT deleted (rotation moves them, never drops them)
2. **ISO timestamps:** always with timezone offset (an entry without one is read as local time)
3. **Bullet-list body:** operation details — bulleted list under the heading
4. **Not indexed:** `log.md` is excluded from Repomix (operational data, not knowledge)
5. **Rotation:** when log.md holds more than `logging.rotation_threshold` entries (default 1000; 0 = off), `append_log` moves the oldest entries to `<logging.archive_dir>/log-YYYY-MM.md` (by entry month) and keeps the newest half
6. **Git-friendly:** each entry is an atomic append → minimal merge conflicts
