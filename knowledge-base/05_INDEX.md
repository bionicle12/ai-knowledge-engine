# 05 — Indexing and Repomix

> Configure the Repomix index: what is indexed, what is excluded, how it auto-updates.
>
> **Reference template:** `knowledge-base/templates/repomix.config.json.template`. The agent copies it to the deployed base root as `repomix.config.json` and parameterizes if needed.
> **Reference shell script:** `knowledge-base/shell/reindex.sh` is copied into `shell/reindex.sh` in the deployed base.

---

## Principle: clean data only

The Repomix index contains **only**:
- `knowledge/**/*.md` — extracted knowledge
- `assets-index/**/*.md` — descriptions of binary files
- Meta files: `README.md`, `KNOWLEDGE_STRUCTURE.md`, `kb.config.yml`

**Not indexed:** `raw/`, `processed/`, `assets/`, `review/`, `interactions/`, `setup/`, `scripts/`, **and `AGENTS.md`** — it is already loaded into every session's system prompt; indexing it charges its tokens twice.

---

## Principle: packs, not a monolith

A single `.repomix/output.xml` stops working the moment the base grows: a
base with a library of reference books easily passes 150–250K tokens, which
no longer fits a 256K context window *before the session even starts*, and
"read the index for broad context" turns into context poisoning. Long chats
then degrade — the model visibly "loses the thread".

So the index is built as **semantic packs**, each under a token ceiling:

| Window profile | Pack ceiling |
|---------------|-------------|
| `256k` (default) | 80K |
| `200k` | 60K |
| `1m` | 150K |

- `core.xml` — author profile, principles, voice, routing tables, meta files.
  Small by design; always safe to load.
- One pack per `knowledge/` section (`domain.xml`, `insights.xml`, …).
- A section **over the ceiling is split by subfolder automatically**:
  `knowledge/library/craft/` → `library-craft.xml`, and so on. A reference
  library never shares a pack with working knowledge — book packs load only
  when the task is about them.
- Sections under ~15K merge into a shared `aux.xml` (routing between twenty
  micro-files is as bad as one giant file).
- `.repomix/PACKS_STATUS.md` — auto-generated table of packs with fresh token
  estimates; agents read it instead of hardcoded numbers.

The agent's loading rule (already in the AGENTS.md template): route via
`knowledge/routing-table.md`, then load `core` plus **at most one** domain
pack per task.

Configuration lives in the `index:` section of `kb.config.yml`
(see `templates/kb.config.yml.template`): `window_profile`, optional
`pack_token_ceiling` / `merge_below_tokens` overrides, and `packs: auto`
(recommended) or an explicit pack list. `kb_reindex.py` plans the packs,
generates `.repomix/configs/<pack>.json` from the base `repomix.config.json`,
builds only stale packs (mtime-based skip), and **warns when a pack exceeds
the ceiling** — that is the signal to sub-split further (deeper subfolders,
or an explicit `packs:` list).

Bases deployed before pack mode keep working: without an `index:` section
`kb_reindex.py` builds the old monolithic `output.xml` and prints a loud
warning once it crosses ~150K tokens, telling you to enable packs.

---

## Why `compress: false` is non-negotiable here

For **code**, Tree-sitter compression is a fair trade: structure survives,
method bodies go — an agent can re-read real sources for details.

For a **knowledge base the text IS the payload**: wording, nuance, full
paragraphs of extracted knowledge. Compression would amputate exactly what
the base exists to preserve. Therefore every KB pack keeps
`compress: false, removeComments: false` — and the size problem is solved by
**splitting harder** (packs, subfolder splits), never by compressing.

---

## repomix.config.json (base config)

In pack mode this file is the **base config**: `kb_reindex.py` inherits its
`ignore` / `security` / `tokenCount` / output options into every generated
`.repomix/configs/<pack>.json`, overriding only the per-pack `include`,
`filePath`, and header. Its own `include`/`filePath` are used directly only in
legacy (no `index:` section) mode.

See `templates/repomix.config.json.template` for the full reference copy. Key
points, in either mode:

- `compress: false`, `removeComments: false` — see the section above.
- `ignore.customPatterns` excludes `raw/`, `processed/`, `assets/`, `review/`,
  `interactions/`, `setup/`, `scripts/`, `.repomix/`, logs, and all binary
  formats.
- `tokenCount.encoding: o200k_base`.
- Legacy `include` lists `AGENTS.md` for historical reasons; pack mode drops
  it (already in the system prompt).

---

## shell/reindex.sh

The reference script `knowledge-base/shell/reindex.sh` (copied into the
deployed base) runs: ingest → routing → quick lint → throttled consolidation →
**`kb_reindex.py --index-only`**, which builds the packs (or the legacy
monolith when packs are not configured). Windows uses `shell/reindex.bat`,
which delegates to the same `kb_reindex.py` — identical behavior, no Git Bash
required.

Manual index-only rebuilds:

```bash
python3 scripts/kb_reindex.py --index-only            # only stale packs
python3 scripts/kb_reindex.py --index-only --force    # everything
```

---

## Git hooks and auto-run

See `13_AUTORUN.md` for the full automation setup:
- File watcher (watchdog daemon)
- Git hooks (post-commit, pre-commit)
- Cron (periodic lint + reindex)

---

## Cross-references: the `[[wikilinks]]` convention

Files in `knowledge/` cross-reference each other via wikilinks:

```markdown
# Example in knowledge/domain/caching.md
We use [[DragonflyDB]] as a Redis-compatible cache (see [[infrastructure-decisions]]).
We dropped [[NATS]] in favor of Redis pub/sub (see [[decisions/2026-03__no-nats]]).
```

### Link formats

| Format | Resolves to |
|--------|-------------|
| `[[slug]]` | Search for `slug.md` in any `knowledge/` subfolder |
| `[[domain/caching]]` | Exact path: `knowledge/domain/caching.md` |
| `[[decisions/2026-03__no-nats]]` | Exact path: `knowledge/decisions/2026-03__no-nats.md` |

### Rules

1. Slug = filename without `.md`
2. On slug conflict (same filename in multiple folders) — use the full path
3. `kb_lint.py` validates every wikilink
4. Broken links → lint error
5. The AI agent **must** add wikilinks to related pages when creating/updating `knowledge/` files

### Optional automation

A Python helper can suggest wikilinks:
```python
def suggest_wikilinks(text: str, knowledge_slugs: dict) -> list:
    """Find mentions of entity names from knowledge/ and suggest [[wrapping]]."""
```

---

## Routing tables: navigation for scaled bases

When `knowledge/` holds > 50 files, a flat index becomes a context dump. Routing tables provide two-level navigation.

### `knowledge/routing-table.md` (top level)

```markdown
# Routing Table

## Domains
- [[rt/infrastructure]] — Docker, Traefik, DB, caching, networking
- [[rt/game-logic]] — clicks, settlements, economy, events, corps
- [[rt/frontend]] — React, PixiJS, HUD, biomes, scenes, i18n
- [[rt/auth]] — providers, sessions, JWT, brute-force, audit
- [[rt/devops]] — CI/CD, monitoring, deployment, backups

## Meta
- [[rt/profile]] — author, expertise, preferences
- [[rt/principles]] — working principles, quality bars
- [[rt/decisions-log]] — chronology of key decisions
```

### `knowledge/routing/rt-infrastructure.md` (second level)

```markdown
# Infrastructure

## Key pages
- [[domain/docker-swarm]] — why Swarm, not K8s
- [[domain/caching]] — DragonflyDB, caching patterns
- [[domain/database]] — PostgreSQL 16, migrations, indexes

## Adjacent areas
- → [[rt/devops]] for CI/CD and monitoring
- → [[rt/auth]] for authentication infrastructure
```

### Agent navigation

1. Reads `routing-table.md` (~20 lines)
2. Picks the right topic → jumps to a routing page
3. Finds concrete pages → reads them
4. **3 hops** instead of reading the entire index

The routing table is created and maintained by the AI agent. Lint verifies that all routing-table links are valid.
