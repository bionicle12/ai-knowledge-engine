# 07 — Self-Learning Feedback Loop

> How the knowledge base learns from each working session with the AI agent and improves itself by analyzing dialogues.

---

## Idea

Every conversation with the AI agent contains valuable conclusions: decisions, preferences, insights, thinking patterns. Without capture they get lost in chat history. The feedback loop saves them and turns them into knowledge.

```text
Dialogue → Session Summary (!save) → interactions/sessions/
                                    ↓
                          Meta-review (!meta-review)
                                    ↓
                          interactions/insights/
                                    ↓
                          Quality filter + owner confirms
                                    ↓
                          knowledge/ (updates)
                                    ↓
                          Reindex → Repomix packs
                                    ↓
                          AI agent gets smarter ←──── next dialogue
```

Nothing in this loop writes on its own. Scripts only count what is waiting and report it in `STATUS.md`; the agent writes when the owner asks.

---

## Session start: `STATUS.md` and `!status`

`scripts/kb_status.py` rewrites `STATUS.md` at the end of every reindex: one line per kind of pending work, each ending with the command that resolves it (see `kb-docs/05_INDEX.md`). Lines this module resolves:

- `sessions awaiting meta-review: 5 → !meta-review`
- `reflection due (changes 31 ≥ 25) → !reflect`

Read `STATUS.md` at session start. Mention its non-zero lines to the owner once; act on them only when asked. `!status` runs `python3 scripts/kb_status.py`, which rewrites the file and prints it.

---

## Capture

Write a session summary on `!save` or when the user explicitly asks to save
(or "lock this into the base"). Do not auto-detect that "enough material has
accumulated" and write on your own.

| Situation | Action |
|-----------|--------|
| User issues `!save` | Writes summary immediately (agent writes under `interactions/sessions/`; optional CLI: `python3 scripts/kb_save_session.py --title … --summary …` with `--session <dialogue folder or topic>`; it writes the layout below, never overwrites — a second save in the same minute gets `.v02` before `.md` — and logs `session-capture`) |
| User explicitly asks to save | Same as `!save` |
| User asks not to save | No write |

### Layout in `interactions/sessions/`

Each dialogue gets a uniquely named folder. Inside — timestamped files:

```text
interactions/sessions/
└── 2026-05-06__competitor-analysis/
    ├── 2026-05-06T10-30__initial-findings.md
    ├── 2026-05-06T11-15__deep-dive.md
    └── 2026-05-06T12-00__final-summary.md
```

A new save adds a file; it never overwrites an earlier one.

---

## Session-summary format

```markdown
---
session_date: 2026-05-06
topic: "Q2 competitor analysis"
duration_estimate: "45 min"
quality: high
redaction_required: true   # a redaction pass is still owed (privacy.require_redaction_for_chats)
meta_reviewed: false       # !meta-review sets true
---

# Session: Q2 competitor analysis

## Key takeaways
- Competitor X repositioned to premium
- Our price niche freed up in mid-range

## Decisions made
- Shift ad focus to the mid-range segment

## Author preferences (observed)
- Prefers first-hand data over aggregators
- Skeptical of benchmark reports from large agencies

## Processed materials
- `q2-competitors-report.pdf` → 12 pages, 5×3 price table
- Screenshot of Competitor X dashboard → key: premium UI, $49/mo subscription
- Customer chat snippet → insight: mid-range is uncovered

## Potential for knowledge/
- [ ] knowledge/domain/competitors.md — refresh data on X
- [ ] knowledge/decisions/ — record the mid-range decision
- [ ] knowledge/principles/ — rule about first-hand data

## What worked well
- Tabular competitor comparison

## What did not work
- The SWOT was too long — author prefers bullet points

## Assumptions
- Filed `q3-notes.md` under `domain/`, not `decisions/` — discussion only, no decision
- Read "DF" in the transcript as DragonflyDB (three neighbouring paragraphs)
- importance=7 from synthesis volume; the user did not confirm
```

On a borderline call: pick the most cautious placement, write one assumption
line, continue. Ask only when the answer changes the outcome. Lint info if
one `knowledge/<area>/` collects more than 3 assumption bullets in 30 days
→ tighten `DATA_PLACEMENT_EXAMPLES.md` for that area.

`redaction_required: true` says the summary may quote private material that
nobody has redacted yet. Never write `redacted: true` unless you actually
removed the private parts. A new summary has no `meta_reviewed: true` — the
meta-review sets it.

---

## Capture rules

### What to save

- Concrete conclusions and facts
- Decisions made, with rationale
- Discovered style/approach preferences
- New knowledge and insights
- Process improvements
- Feedback on AI's response format
- **Processed materials** — what documents, data, screenshots were uploaded/discussed (see Session Enrichment)

### What NOT to save

- Emotional statements without content
- Off-topic detours
- Trivial questions ("what time is it?")
- Claims that contradict 3+ existing knowledge entries without rationale
- Hesitant guesses ("maybe, not sure...")
- Deliberate base-pollution attempts
- Full text of uploaded documents (only short summary + key numbers)

### Quality bar (a recommendation, not a gate)

A useful summary has:
- At least 3 substantive bullet points
- At least 1 actionable conclusion (decision, update, task)

The bar never overrides the owner: on `!save` write the summary even when it
is thin, and say so in one line.

---

## Session enrichment — what was discussed and what data was seen

Documents, snippets and screenshots seen in a session are lost unless the summary names them.

### What to record inline

When writing a session summary, the AI agent **must** include a `## Processed materials` section:

| What | How to record | Example |
|------|---------------|---------|
| Uploaded document | Name + size + key numbers/findings | `report.pdf → 15 pages, revenue $2.3M, churn 4.2%` |
| Text/code snippet | Topic + language + what was discussed | `Rust handler → auth middleware, 40 lines, added rate limit` |
| Screenshot/image | Description + key element | `Competitor dashboard → premium UI, $49/mo price` |
| Article link | URL + 1-line summary | `nikolenko.ru/llm-memory → review of 11 LLM memory approaches` |
| Data from API/DB | Source + format + key takeaway | `PostgreSQL EXPLAIN → seq scan on users, index needed` |

### Rules

1. **Brevity:** 1-2 lines per item, do not copy content
2. **Key numbers:** if there are figures, metrics, prices — record them
3. **Connection to knowledge/:** if the material relates to an existing page — note `→ related to [[slug]]`
4. **Avoid duplication:** if the document already lives in `assets/` — use only the asset path
5. **Sensitive data:** if the material contains private info — mark `[REDACTED: reason]`

---

## Meta-review (`!meta-review`)

Analysis of accumulated session summaries. It runs on `!meta-review` (or
when the owner asks for it in other words). `STATUS.md` counts the session
files still waiting (`sessions awaiting meta-review: N → !meta-review`);
suggest the command when the number grows, do not start it on your own.

### Process

1. Find the unprocessed session files: every `.md` under
   `interactions/sessions/` whose frontmatter does not say
   `meta_reviewed: true`. `!import` keeps an incoming copy that differs
   from a local file next to it (`<name>__from-<label>-<sha8>.md`,
   `kb-docs/16_MERGE.md`): that is the same session — when either copy
   says `meta_reviewed: true`, mark the other without analyzing it again
2. Look for repeating patterns:
   - What questions come up most often?
   - What style preferences repeat?
   - Which knowledge areas need updating?
   - Where did the AI answer poorly — and why?
3. Write each pattern (3+ repeats, see Anti-sabotage) to
   `interactions/insights/YYYY-MM__insight-slug.md`
4. Write the run report `interactions/meta-reviews/YYYY-MM-DD.md`: the
   session files analyzed, the patterns found, the proposed `knowledge/`
   updates
5. The owner confirms or rejects each proposed update; apply only the
   confirmed ones
6. Mark every analyzed session file — add `meta_reviewed: true` to its
   frontmatter, creating one if the file has none (a YAML boolean; the
   string `"true"` does not count). Files that taught nothing are marked too
7. Log operation `meta-review`

No pattern is a valid result: write the report, mark the files, stop.

### Insight format

```markdown
---
period: "2026-05"
sessions_analyzed: 12
---

# Insight: Author prefers bullet points over prose

## Pattern
In 8 of 12 sessions the author asked to reformat long paragraphs into lists.

## Recommendation
Update knowledge/voice/communication-style.md:
add the rule "default to bullet points; prose only for narrative".

## Action
- [ ] Update knowledge/voice/communication-style.md
```

---

## Reflection — higher-level insights (mode-aware)

Periodic synthesis: from raw facts → high-level conclusions.
`scripts/kb_reflect.py` decides **when** a reflection is due; the reflection
itself is agent work (`!reflect`, ~15K tokens). The active profile is
`mode_profiles.<knowledge_base.mode>.reflection` in `kb.config.yml`.

### When it is due

`python3 scripts/kb_reflect.py --check-threshold` compares the **change
score** since the last reflection with the profile:

- every `ingest` entry in `log.md` weighs the `importance` in its ingest
  metadata, or `default_ingest_importance` (1) when it has none;
- every `knowledge/` page whose content changed since the last reflection
  weighs its `importance` (3 when unset); access tracking (`last_accessed`,
  `access_count`) is not a change, and generated pages (`generated_by:`)
  and `_archive/` do not count (details: `kb-docs/13_AUTORUN.md`).

| Decision | Meaning |
|----------|---------|
| `THRESHOLD_MET` | A reflection is due |
| `STAGNANT` | It would be due, but the last two reflections found 0 insights and no ingest arrived since |
| `SKIP` | Nothing to do |

When the check says `THRESHOLD_MET`, `STATUS.md` shows `reflection due … →
!reflect`, and a reindex that runs consolidation (at most every
`autorun.consolidation_interval_hours`, when
`autorun.consolidation_on_reindex` is true) logs a `reflect-request`. Nothing
runs the reflection itself: suggest `!reflect` to the owner.

#### `knowledge_base.mode: default` — throttled

| Trigger | How |
|---------|-----|
| **Importance threshold** | Change score ≥ `importance_threshold` (25) |
| **Weekly** | ≥ `min_interval_days` (7) since the last reflection — or since deployment when there is none yet — **and** at least one change |
| **Command `!reflect`** | User explicitly requests reflection — always runs |

A base that has never reflected starts the weekly clock at its deployment
(`deployed_at` in `kb.config.yml`, or the first `log.md` entry when that is
older): its first ingest is not a reflection on its own. A reflection recorded
with 0 insights restarts the weekly clock.

#### `knowledge_base.mode: super` — on-demand

| Trigger | How |
|---------|-----|
| **Every significant change** | Change score ≥ 5: one changed page of importance 5, two changed pages without importance, or five ingests without importance |
| **Command `!reflect`** | User explicitly requests |
| **No minimum interval** | Not bound by 7-day spacing; no change at all → `SKIP` |

Each reflection costs ~15K tokens.

```yaml
# kb.config.yml — mode_profiles.<mode>.reflection (read by kb_reflect.py):
mode_profiles:
  default:
    reflection:
      trigger: "threshold+weekly"    # threshold, plus weekly once min_interval_days passed
      importance_threshold: 25       # due when the change score reaches it
      min_interval_days: 7           # weekly spacing
      require_changes: true          # weekly: only with at least one change
      max_insights_per_run: 3        # ceiling, not a quota — 0 insights is valid
      # default_ingest_importance: 1 # weight of an ingest without importance
  super:
    reflection:
      trigger: "on-demand"
      importance_threshold: 5
      min_interval_days: 0
      require_changes: false
      max_insights_per_run: 5
```

### Brakes

- **Honest zero.** No new insight is a valid, expected result. Record it
  (`python3 scripts/kb_reflect.py --record-result 0`) and stop. Do not invent
  insights to fill `max_insights_per_run`.
- **Meta-insight (level 2)** only if new level-0 facts (ingests) arrived
  since the last level-1 reflection. `kb_reflect.py --json` reports that as
  `meta_insight_allowed`.
- **Stagnation.** Two consecutive reflections with 0 insights → the check
  says `STAGNANT` instead of `THRESHOLD_MET` until a new ingest arrives.
  `!reflect` from the user still runs.

### Process

1. `python3 scripts/kb_reflect.py --json`: change score, `max_insights_per_run`,
   `meta_insight_allowed`, `exploration` pairs
2. AI generates 3 important questions about recent experience
3. For each, search relevant pages via routing + wikilinks
4. Synthesize a higher-level insight
5. Write at most `max_insights_per_run` pages to `knowledge/insights/`
   with `[[wikilinks]]` to source pages — or write none
6. **Always finish with** `python3 scripts/kb_reflect.py --record-result N`
   (N = insight pages written, 0 is valid). Only this call stamps
   `.last_reflection` and logs `reflect | insights: N`; without it the change
   score keeps growing and the reflection stays due

### Insight format

```markdown
---
source: "reflection"
extracted_at: 2026-05-06
confidence: medium
importance: 7
lifecycle: "evolving"
tags: [architecture, insight]
children:
  - "knowledge/domain/caching.md"
  - "knowledge/decisions/2026-03__dragonfly.md"
---

# Insight: caching is our key performance lever

Conclusion: over 3 months we changed the caching layer three times...

Related: [[caching]], [[dragonfly-migration]], [[cache-patterns]]
```

### Knowledge tree

Level 0: `domain/` + `playbooks/` (facts) → level 1: `insights/` (synthesis) →
level 2: meta-insights in `insights/`. **No more than 3 levels.**

---

## Self-editing — note evolution (mode-aware)

When new knowledge is related to existing knowledge, the older page gets a
`context_annotations` entry. There is no Python annotator: annotations are
agent work in both modes, and `mode_profiles.<mode>.annotations.engine` says
how much effort to spend.

### When it applies

- Ingest's entity resolution matched an entity to an existing page:
  `processed/nlp-meta/<name>.yml` → `entities[].existing_page` (the review
  package lists them under "NLP enrichment")
- A query-writeback page overlaps with an existing one

### `engine: "python"` (default mode) — template note

Append an entry without reading the related page. The `note` is template
text built from the NLP match: `"NLP-match: entity 'knowledge-base'"`.

### `engine: "ai"` (super mode) — substantive annotation (~1-3K tokens)

The AI agent **reads** the related page and the new material, then writes:

1. **A substantive annotation:** not just "NLP-match" but a description of *what* the link is
2. **Concrete edit suggestions** for the existing page (if the new material complements/refines it)
3. **Contradiction detection** between new and existing knowledge
4. **Merge/split recommendation** when there are >5 annotations

### `context_annotations` format

```yaml
# default mode:
context_annotations:
  - date: 2026-05-06
    related: "knowledge/domain/llm-wiki-pattern.md"
    note: "NLP-match: entity 'knowledge-base'"

# super mode:
context_annotations:
  - date: 2026-05-06
    related: "knowledge/domain/llm-wiki-pattern.md"
    note: "New benchmark showed throughput drop — extends Performance section in [[caching]]"
    suggested_edit: "Add a paragraph about degradation under load"
    contradiction: null
```

### Rules

1. **default:** `note` is template text; the related page is not read
2. **super:** `note` is a substantive link description (~1-3K tokens)
3. **Maximum 5 annotations** per page (more → lint `annotation-overflow` suggests creating an insight)
4. Files with `lifecycle: permanent` — annotations are added but the body is not touched

---

## Surprise-based filtering — not implemented yet

`mode_profiles.*.surprise` is reserved (engine `docs/ROADMAP.md`): no script
scores how new a source is, and ingest writes no `is_surprise`. Until it
exists, apply the outcome by hand when you extract or write back — check the
related pages first:

- **Nothing new** → update the existing page or add a `context_annotations` entry instead of creating a new page
- **New** → add it
- **Contradicts** existing knowledge → add it AND create an entry in `knowledge/open-questions/`

---

## Anti-sabotage

A quality filter protects the base from degradation:

1. **Fact-check:** if a conclusion contradicts 3+ existing facts — do not add it; create a question in `knowledge/open-questions/`
2. **Repeatability:** a single occurrence is not a pattern. Record as pattern only after 3+ repeats
3. **Constructive bias:** emotional or destructive statements are filtered at the session-summary stage
4. **Transparency:** every `knowledge/` update records the source (which session or insight) in frontmatter

---

## Query → Wiki Writeback

A valuable AI answer can become a `knowledge/` page without waiting for
meta-review — **once the owner says yes** (or on `!save` / "save this").
Offer it in one line ("Save this comparison as
`knowledge/domain/rag-vs-wiki.md`?"); do not write on your own.

### When to offer

| Criterion | Example |
|-----------|---------|
| Synthesis from 3+ sources | Architecture comparison, approach overview |
| Architectural decision with rationale | "Why Docker Swarm, not K8s" |
| Comparative analysis | Trade-off table, pros/cons |
| Answer contradicts knowledge/ | → offer an entry in `knowledge/open-questions/` |

### When NOT to offer

- Trivial answers (one-liners)
- Code without architectural rationale
- Answers that fully duplicate an existing `knowledge/` page
- Low-confidence answers without verification

### Writeback page format

```markdown
---
source: "query-writeback"
session: "interactions/sessions/2026-05-07__highway-clicker__kb/"
extracted_at: 2026-05-07
confidence: medium
verification_method: "ai-review"
lifecycle: "evolving"
importance: 6
tags: [architecture, comparison]
query: "Why is LLM Wiki better than RAG at our scale?"
---

# RAG vs LLM Wiki: analysis for our project

## Conclusion
...

## Rationale
...

## Related pages
- [[knowledge-management]]
- [[decisions/2026-05__kb-architecture]]
```

### After writeback

1. Append to `log.md` (`query-writeback` operation)
2. Add `[[wikilinks]]` to related `knowledge/` pages
3. Routing is regenerated on reindex: `kb_route.py` rewrites `knowledge/routing/*.md` and the `AUTO-ROUTING` block of `routing-table.md` — never edit those by hand; edit `routing-table.md` outside that block only when the page needs a new topic line
4. On the next reindex — the page enters its Repomix pack

---

## `!audit` — clean context, by pack

The writer of a page must not be the only reviewer. `kb_reindex.py` writes
`.repomix/audit/<pack>__request.md` (pack + checklist + report format) and
`CROSS_PACK__request.md` (titles only).

`!audit` → one **new session** per request file. You cannot open one
yourself: ask the owner to start a new chat (or a sub-agent with a clean
context, if the tool has one) and give it the request file. A finding
without `file:line` and a quote is discarded. There is no `kb_audit.py`.

## `!profile-review`

`knowledge/profile/` is `permanent` by folder policy (`lifecycle.by_folder`
→ `profile: permanent`, the default in `kb.config.yml`), so the stale check
skips it.

1. Read what you know about the author from `knowledge/profile/`. What is
   missing? Ask **three questions at a time**, important first. Update pages
   from the answers.
2. Then: what may be outdated or incomplete? Same cadence.

Stamp `profile_review.reviewed_at` in `kb.config.yml` (edit that one line;
keep the comments). Lint warns after 30 days if that field is set; missing
field is not a warning.

## `!quiz`

The base exams the owner. This is the only command that checks the human,
not the pages.

1. Skim `knowledge/profile/`, `knowledge/principles/`, `knowledge/decisions/`,
   and `knowledge/routing-table.md`. Do not load the whole base.
2. Ask **five questions** about what is already in the base. Start with the
   **costliest mistakes** (a silent contradiction, a decision the owner
   would hate to see inverted, a fact the AI would invent if the page is
   thin). Then coverage gaps. Then a recall check on a dated decision.
3. One question at a time is fine if the owner is answering in chat;
   batch only when they ask.
4. Write the sheet to `interactions/quiz/YYYY-MM-DD.md` (not indexed):
   question, owner answer, page that should have held it, whether the
   page needs an edit. Log operation `quiz`.
5. If an answer contradicts a page — do not silently "fix" the page.
   Show the diff and wait.

There is no `kb_quiz.py`.

## Exploration slot (`!reflect`)

When `kb_reflect.py --json` returns `exploration` pairs, use **at most
two** of them as reflection questions: "What connects [[A]] and [[B]] that
the graph does not show?" Pairs are disconnected components (or nodes with
no directed path) with tag/title overlap `< 0.8`. An empty list is valid —
do not invent a link. New insights from a real connection go to
`knowledge/insights/`.

---

## Logging

All feedback-loop operations are recorded in `log.md` (see `kb-docs/10_LOG.md`):
- `session-capture` — when a session summary is written
- `query-writeback` — when a valuable answer is saved
- `meta-review` — when `!meta-review` finishes (sessions analyzed, insights written)
- `quiz` — when `!quiz` writes `interactions/quiz/`
- `reflect` — written by `kb_reflect.py --record-result N`; `reflect-request` — written by `kb_reflect.py --generate` during consolidation
