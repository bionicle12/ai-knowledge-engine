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
│   └── .repomix/output.xml
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

## Plugging into a working project

### Option 1: section in the project's AGENTS.md (recommended)

Add to the working project's `AGENTS.md`:

```markdown
## Personal Knowledge Base

Next to this project sits the author's personal knowledge base.

- Path: `../knowledge-base/`
- Index: `../knowledge-base/.repomix/output.xml`
- Profile: `../knowledge-base/knowledge/profile/`
- Principles: `../knowledge-base/knowledge/principles/`

### When to use it

- Before architectural decisions — read `knowledge/principles/`
- For code/text voice — read `knowledge/voice/`
- For project context — read `knowledge/projects/`
- When discussing ideas — use the full index `.repomix/output.xml`

### Session capture

While working in this project — write session summaries into the KB:
- Path: `../knowledge-base/interactions/sessions/`
- Folder format: `YYYY-MM-DD__<project-name>__<topic>/`
- Auto-capture follows the same rules (see 07_INTERACTION_LOOP.md)
- Reindex manually: `cd ../knowledge-base && ./reindex.sh`
```

### Option 2: symlink to the index

```bash
# In the working project
ln -s ../knowledge-base/.repomix/output.xml .kb-context.xml
```

Add to `AGENTS.md`:
```markdown
## Personal Context
Read `.kb-context.xml` for author context before strategic decisions.
```

### Option 3: copy the index (for isolated environments)

If the project is not on the same machine:

```bash
cp ../knowledge-base/.repomix/output.xml ./docs/kb-context.xml
```

Update manually as needed. Suits CI/CD or remote environments.

---

## Session capture from a working project

When the AI agent works in `highway-clicker` and wants to record conclusions:

1. Writes a session summary into `../knowledge-base/interactions/sessions/`
2. Uses format: `YYYY-MM-DD__highway-clicker__<topic>/`
3. Adds a project tag in frontmatter:

```markdown
---
session_date: 2026-05-06
project: "highway-clicker"
topic: "WebSocket auth refactor"
quality: high
---

# Session: WebSocket auth refactor

## Key takeaways
- Decided to use SIWE for MetaMask instead of a custom signature
- ...
```

4. Reindex the KB **manually**: `cd ../knowledge-base && ./reindex.sh`
   - Not automatic, to avoid slowing down the working project

---

## Continued learning from working projects

The base keeps learning even when you are not in it:

```text
Working in highway-clicker
        ↓
AI writes session summary → ../knowledge-base/interactions/sessions/
        ↓
When convenient: cd ../knowledge-base && ./reindex.sh
        ↓
Meta-review → knowledge/ updates
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
# Pack (without .venv and binary assets)
tar czf knowledge-base-portable.tar.gz \
  --exclude='.venv' \
  --exclude='assets/' \
  --exclude='.repomix/' \
  knowledge-base/

# On the new machine
tar xzf knowledge-base-portable.tar.gz
cd knowledge-base
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./reindex.sh
```

If you need assets — add `assets/` to the archive (increases size).

---

## Multiple projects — staying organized

| Question | Answer |
|----------|--------|
| Where does the KB live? | Once, next to projects (`../knowledge-base/`) |
| Where does the AI write session summaries? | Always in `../knowledge-base/interactions/sessions/` |
| How do projects stay distinct? | By session-folder name: `2026-05-06__highway-clicker__topic/` |
| When to reindex? | Automatically (see `13_AUTORUN.md`) or `./reindex.sh` |
| Need an `AGENTS.md` in every project? | Yes, with a "Personal Knowledge Base" section |
| Different bases for different roles? | Possible, but usually one base per person |

---

## Dynamic Context Enrichment

The AI agent loads knowledge **lazily** through links — only what it needs.

### Problem

Loading the entire `.repomix/output.xml` (~100KB+) burns context. Most knowledge is irrelevant for any given task.

### Solution: lazy loading via routing

```text
routing-table.md (20 lines)
        ↓ AI picks the topic
routing/rt-infrastructure.md (15 lines)
        ↓ AI finds the right pages
domain/docker-swarm.md + domain/caching.md
        ↓ AI follows [[wikilinks]] when more context is needed
decisions/2026-03__swarm-deployment.md
```

**~4 files instead of the entire index.**

### In the working project's AGENTS.md

```markdown
## Dynamic Context Loading

When working with the KB:
1. First read `../knowledge-base/knowledge/routing-table.md`
2. Pick 1-2 relevant routing pages by topic
3. Read only the needed `knowledge/` pages
4. If more context is needed — follow `[[wikilinks]]`
5. Do NOT read the whole `.repomix/output.xml` if 3-5 pages will do

This conserves context and keeps work fast on large bases.
```

### Live context enrichment

While answering, the AI can **dynamically** pull in knowledge:

1. Spotted a `[[wikilink]]` in a loaded page
2. Decided the linked page would sharpen the answer
3. Pulled it in and folded it into reasoning
4. If a gap appeared — created a `query-writeback` page

This turns the base from a **static reference** into a **living system** that:
- Updates on ingest (automatically — see `13_AUTORUN.md`)
- Enriches itself on query-writeback (see `07_INTERACTION_LOOP.md`)
- Loads on demand via routing + wikilinks
- Is checked by lint (see `09_LINT.md`)
