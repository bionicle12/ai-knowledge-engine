# 08 — Portability: using the base across other projects

> How to plug a trained knowledge base into your working projects so the AI agent uses the accumulated expertise while writing code.

---

## The problem

The knowledge base lives in its own project. But work happens in **other projects** — code repositories where the AI agent should also know the author: voice, decisions, principles, preferences.

## Recommended layout: sibling project + reference

```text
~/www/main/
├── knowledge-base/          # ← The KB (separate project)
│   ├── AGENTS.md
│   ├── knowledge/
│   ├── interactions/
│   └── .repomix/            # index packs + PACKS_STATUS.md
│
├── highway-clicker/         # ← Working project
│   ├── AGENTS.md            # contains a pointer to the base
│   └── ...
│
└── another-project/         # ← Another project
    ├── AGENTS.md
    └── ...
```

### Why a sibling project, not nested?

- The KB is **about the author**, not about a specific project
- One base serves many projects
- KB updates do not pollute the git history of working projects
- It can be backed up / moved separately

---

## The index is a set of packs

`kb_reindex.py` builds the index as packs (see `kb-docs/05_INDEX.md`):

- `.repomix/core.xml` — profile, principles, voice, routing tables. Small; safe to load first.
- `.repomix/<section>.xml` — a pack per large `knowledge/` section (`domain.xml`, `insights.xml`, …); an oversized section is split by subfolder (`library-craft.xml`).
- `.repomix/aux.xml` — small sections merged together; pages directly under `knowledge/` go there too, or into `knowledge-root.xml` once they are large.
- `.repomix/PACKS_STATUS.md` — every pack with its size, `⚠ OVER` when it is over the token ceiling, and when to load it (for `aux.xml`: which sections it holds). Find a section's pack there, not by guessing a file name.

There is no single whole-base index to load. A base deployed before pack mode (no `index:` section in `kb.config.yml`) still builds the legacy `.repomix/output.xml`; everything below assumes packs.

---

## Plugging into a working project

### Option 1: section in the project's AGENTS.md (recommended)

Add to the working project's `AGENTS.md`:

```markdown
## Personal Knowledge Base

Next to this project sits the author's personal knowledge base.

- Path: `../knowledge-base/`
- Index: `../knowledge-base/.repomix/PACKS_STATUS.md` — lists the packs and when to load each
- Profile: `../knowledge-base/knowledge/profile/`
- Principles: `../knowledge-base/knowledge/principles/`

### When to use it

- Before architectural decisions — read `knowledge/principles/`
- For code/text voice — read `knowledge/voice/`
- For project context — read `knowledge/projects/`
- When discussing ideas — load `.repomix/core.xml` plus at most one pack whose "Load when" matches; never load a pack marked `⚠ OVER` whole

### Session capture

Write session summaries into the KB only on `!save` or when the author asks
(rules: `../knowledge-base/kb-docs/07_INTERACTION_LOOP.md`):
- Path: `../knowledge-base/interactions/sessions/`
- Folder format: `YYYY-MM-DD__<project-name>__<topic>/`, one timestamped file per save
- Reindex manually: `cd ../knowledge-base && ./shell/reindex.sh`
```

### Option 2: symlink to the index folder

```bash
# In the working project
ln -s ../knowledge-base/.repomix .kb-index
```

Add to `AGENTS.md`:
```markdown
## Personal Context
Before strategic decisions read `.kb-index/PACKS_STATUS.md`, then `.kb-index/core.xml`
and at most one matching pack.
```

### Option 3: copy packs (for isolated environments)

If the project is not on the same machine:

```bash
mkdir -p ./docs/kb-context
cp ../knowledge-base/.repomix/PACKS_STATUS.md ../knowledge-base/.repomix/core.xml ./docs/kb-context/
cp ../knowledge-base/.repomix/domain.xml ./docs/kb-context/    # only the packs this project needs
```

Update manually as needed. Suits CI/CD or remote environments. The packs hold the author's private knowledge: keep the copy out of a shared repository (add `docs/kb-context/` to its `.gitignore`).

---

## Session capture from a working project

When the owner says `!save` (or asks to record conclusions) while the agent works in `highway-clicker`:

1. Writes a session summary into `../knowledge-base/interactions/sessions/`
2. Uses the folder format `YYYY-MM-DD__highway-clicker__<topic>/` with timestamped files inside (layout: `kb-docs/07_INTERACTION_LOOP.md`)
3. Adds a project tag in frontmatter:

```markdown
---
session_date: 2026-05-06
project: "highway-clicker"
topic: "WebSocket auth refactor"
quality: high
redaction_required: true   # as in kb-docs/07_INTERACTION_LOOP.md
meta_reviewed: false
---

# Session: WebSocket auth refactor

## Key takeaways
- Decided to use SIWE for MetaMask instead of a custom signature
- ...
```

4. Reindex the KB **manually**: `cd ../knowledge-base && ./shell/reindex.sh`
   - Not automatic, to avoid slowing down the working project

---

## Continued learning from working projects

The base keeps learning even when you are not in it:

```text
Working in highway-clicker
        ↓
!save → AI writes session summary → ../knowledge-base/interactions/sessions/
        ↓
When convenient: cd ../knowledge-base && ./shell/reindex.sh
        ↓
STATUS.md: "sessions awaiting meta-review" → !meta-review → knowledge/ updates
        ↓
Next session in highway-clicker — the AI is smarter
```

### What flows into the KB from working projects

- Architectural decisions and their rationale
- Discovered code-style preferences
- Debugging patterns that worked
- Tools and approaches you liked / disliked
- Cross-project insights

### What does NOT flow in

- Project code (already in git)
- Project secrets and configs
- Details specific to a single project with no reusable value

---

## Moving the base to another machine

```bash
# Pack (without the venv, binary assets and machine-local state)
tar czf knowledge-base-portable.tar.gz \
  --exclude='.venv' \
  --exclude='assets/' \
  --exclude='.repomix/' \
  --exclude='.kb-state/' \
  --exclude='.kb-backups/' \
  --exclude='STATUS.md' \
  knowledge-base/

# On the new machine
tar xzf knowledge-base-portable.tar.gz
cd knowledge-base
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# optional, if the old machine had them: requirements-nlp.txt, requirements-media.txt
./shell/reindex.sh
```

`.repomix/`, the `.kb-state/` caches and `STATUS.md` are rebuilt by the first reindex. Backups — `.kb-backups/` (heal), `.kb-state/upgrade-backups/` and `.kb-state/refactor-backups/` — are machine-local and stay behind. If you need assets — add `assets/` to the archive (increases size).

To keep two live copies of one base in step (laptop + desktop), do not copy archives back and forth: use `!export` / `!import` (see `kb-docs/16_MERGE.md`).

---

## Multiple projects — staying organized

| Question | Answer |
|----------|--------|
| Where does the KB live? | Once, next to projects (`../knowledge-base/`) |
| Where does the AI write session summaries? | Always in `../knowledge-base/interactions/sessions/`, on `!save` |
| How do projects stay distinct? | By session-folder name: `2026-05-06__highway-clicker__topic/` |
| When to reindex? | Automatically (see `kb-docs/13_AUTORUN.md`) or `./shell/reindex.sh` |
| Need an `AGENTS.md` in every project? | Yes, with a "Personal Knowledge Base" section |
| Different bases for different roles? | Possible, but usually one base per person |

---

## Dynamic Context Enrichment

The AI agent loads knowledge **lazily** through links — only what it needs.

### Problem

Loading every pack burns context. Most knowledge is irrelevant for any given task.

### Solution: lazy loading via routing

```text
routing-table.md (20 lines)
        ↓ AI picks the topic
routing/domain.md (15 lines, generated per section)
        ↓ AI finds the right pages
domain/docker-swarm.md + domain/caching.md
        ↓ AI follows [[wikilinks]] when more context is needed
decisions/2026-03__swarm-deployment.md
```

**~4 files instead of whole packs.**

### In the working project's AGENTS.md

```markdown
## Dynamic Context Loading

When working with the KB:
1. First read `../knowledge-base/knowledge/routing-table.md`
2. Pick 1-2 relevant routing pages by topic
3. Read only the needed `knowledge/` pages
4. If more context is needed — follow `[[wikilinks]]`
5. Load a pack from `../knowledge-base/.repomix/` only when 3-5 pages will not do (`PACKS_STATUS.md` says which)

This conserves context and keeps work fast on large bases.
```

### Live context enrichment

While answering, the AI can **dynamically** pull in knowledge:

1. Spotted a `[[wikilink]]` in a loaded page
2. Decided the linked page would sharpen the answer
3. Pulled it in and folded it into reasoning
4. If a gap appeared — offered a `query-writeback` page (written once the owner agrees)

This turns the base from a **static reference** into a **living system** that:
- Updates on ingest (automatically — see `kb-docs/13_AUTORUN.md`)
- Enriches itself on query-writeback (see `kb-docs/07_INTERACTION_LOOP.md`)
- Loads on demand via routing + wikilinks
- Is checked by lint (see `kb-docs/09_LINT.md`)
