# 10 — Operations log (chronology)

> The append-only `log.md` records every operation against the knowledge base: ingest, lint, review, query-writeback, session-capture. It is the single timeline of base evolution.

---

## Why

- The AI agent can see **what happened** to the base in chronological order
- Quickly answer: when was the last review, what was added, what changed
- Parsable by Unix utilities for fast search
- Keeps operational history separate from knowledge content

---

## Location

```
knowledge-base/
└── log.md     # ← append-only, NOT indexed by Repomix
```

Add to `repomix.config.json` → `ignore.customPatterns`:
```json
"log.md",
"lint-report.md"
```

---

## Entry format

Each entry starts with a level-2 heading in this exact format:

```
## [ISO-timestamp] operation-type | Human-readable title
```

### Operation types

| Type | When |
|------|------|
| `ingest` | A new raw file was processed by the pipeline |
| `lint` | A health-check ran |
| `review` | AI processed a `review/` item |
| `query-writeback` | A valuable answer was saved into `knowledge/` |
| `session-capture` | A session summary was written to `interactions/` |
| `update` | Manual edit of a `knowledge/` page |
| `archive` | A page was moved to `_archive/` |
| `reindex` | Repomix index regenerated |
| `nlp-enrich` | NLP enrichment for new material |
| `consolidation` | Daily consolidation block ran (see 13_AUTORUN.md) |
| `reflect` | Reflection trigger fired |
| `populate` | `DATA_PLACEMENT_EXAMPLES.md` regenerated |
| `heal` | Catch-up after upgrade (`kb_heal.py` / `!heal`) |
| `refactor` | Instruction trim (`!refactor` / `17_REFACTOR.md`) |
| `mutate` | L1 mutation self-check (`kb_mutate.py`) |
| `quiz` | Owner exam (`!quiz`) — answers in `interactions/quiz/` |

---

## Example entries

```markdown
# Operations Log

## [2026-05-06T20:30:00+03:00] ingest | Karpathy LLM-Wiki Article
- Source: raw/reference/unsorted/karpathy-llm-wiki.md
- NLP: 12 entities, 18 keywords, complexity: 0.65
- Created: knowledge/domain/llm-wiki-pattern.md
- Updated: knowledge/principles/knowledge-compilation.md
- Updated: knowledge/decisions/2026-05-06__kb-architecture-shift.md
- Tags: #architecture #knowledge-management #llm

## [2026-05-06T21:00:00+03:00] lint | Weekly health-check
- Mode: full
- Checked: 42 pages
- Errors: 1 (broken wikilink in principles/architecture.md)
- Warnings: 3 (stale: redis-patterns.md, caching.md; orphan: nats-evaluation.md)
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

## [2026-05-07T14:05:00+03:00] reindex | Post session-capture
- Pages indexed: 44 (+2 since last)
- Output: .repomix/output.xml
```

---

## Quick search

```bash
# Last 10 operations
grep "^## \[" log.md | tail -10

# All ingest entries in May
grep "^## \[2026-05" log.md | grep "ingest"

# All lint runs that found errors
grep -A5 "^## \[" log.md | grep -B1 "Errors: [1-9]"

# How many of each operation type
grep "^## \[" log.md | sed 's/.*\] //' | sed 's/ |.*//' | sort | uniq -c | sort -rn
```

---

## Who writes to the log

| Source | How |
|--------|-----|
| `kb_ingest.py` | Automatically after each file is processed |
| `kb_lint.py` | Automatically after each run |
| `reindex.sh` | Automatically after regenerating the index |
| AI agent | On query-writeback and session-capture |
| `kb_watch.py` (via `./shell/watcher.sh`) | On automatic processing of a new file |
| `kb_reflect.py --generate` | On reflection trigger |

---

## Rules

1. **Append-only:** entries are NOT edited and NOT deleted
2. **ISO timestamps:** always with timezone offset
3. **Bullet-list body:** operation details — bulleted list under the heading
4. **Not indexed:** `log.md` is excluded from Repomix (operational data, not knowledge)
5. **Rotation:** when > 1000 entries — archive to `log-archive/YYYY.md` and start a new file
6. **Git-friendly:** each entry is an atomic append → minimal merge conflicts
