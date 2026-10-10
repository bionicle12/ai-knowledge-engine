# 05 — Indexing and Repomix

> Configure the Repomix index: what is indexed, what is excluded, how it auto-updates.
>
> **Reference template:** `knowledge-base/templates/repomix.config.json.template`. The agent copies it to the deployed base root as `repomix.config.json` and parameterizes if needed.
> **Reference scripts:** `knowledge-base/scripts/kb_reindex.py` (the pipeline and the index build), `knowledge-base/scripts/kb_status.py` (`STATUS.md`) and the thin wrapper `knowledge-base/shell/reindex.sh`, copied into `scripts/` and `shell/` of the deployed base.

---

## Principle: clean data only

The Repomix index contains **only**:
- `knowledge/**/*.md` — extracted knowledge
- `assets-index/**/*.md` — descriptions of binary files
- Meta files: `KNOWLEDGE_STRUCTURE.md`, `DATA_PLACEMENT_EXAMPLES.md`
  (not `README.md`: the base has none of its own, and a project README at the
  root stays out of the packs; not `kb.config.yml`: `AGENTS.md` has the agent
  read it directly at session start, so a packed copy would cost its tokens twice)

**Not indexed:** `raw/`, `processed/`, `assets/`, `review/`, `interactions/`, `setup/`, `scripts/`, **and `AGENTS.md`** — it is already loaded into every session's system prompt; indexing it charges its tokens twice.

**Privacy floor in code.** `kb_reindex.py` adds these ignore patterns to every
pack config (and to the legacy build as `--ignore`), whatever
`repomix.config.json` or an explicit `packs:` list says:

- `raw/**`, `review/**`, `interactions/**` — each one unless its
  `privacy.raw_indexing_allowed` / `review_indexing_allowed` /
  `interactions_indexing_allowed` flag in `kb.config.yml` is explicitly `true`;
- always: `processed/**`, `assets/**`, `sync/**`, `eval/**`, `setup/**`,
  `kb-docs/**`, `.kb-state/**`, `.kb-backups/**`, `.kb-finalize-backup/**`,
  `.repomix/**`, `.venv/**`, `venv/**`, `.git/**`, `node_modules/**`,
  `log.md`, `log-archive/**`,
  `STATUS.md` (and `status.file` when it is set to another path), `.env`,
  `.env.*`, `**/*.pem`, `**/*.key`.

Files matching them are never pack members, not even in token estimates.

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
| `400k` (Codex) | 120K |
| `256k` (Cursor / conservative default) | 80K |
| `200k` | 60K |
| `1m` (Claude Code 1M) | 150K |

- `core.xml` — author profile, principles, voice, routing tables, the two meta
  files. Small by design; always safe to load.
- One pack per `knowledge/` section (`domain.xml`, `insights.xml`, …). The
  names `core`, `aux` and `knowledge-root` are reserved: a section called
  `knowledge/core/` is packed as `knowledge-core.xml` and never overwrites
  the real core pack.
- Pages directly under `knowledge/` (for example `glossary.md`; the routing
  table itself is core) form `knowledge-root.xml`, or go into `aux.xml` while
  they are small. Every page of `knowledge/` lands in exactly one pack, except
  top-level folders starting with `_` or `.` (such as `_archive/`), which are
  never packed.
- A section **over the ceiling is split by subfolder automatically**:
  `knowledge/library/craft/` → `library-craft.xml`, and so on. A reference
  library never shares a pack with working knowledge — book packs load only
  when the task is about them.
- Sections under ~15K merge into a shared `aux.xml` (routing between twenty
  micro-files is as bad as one giant file).
- `.repomix/PACKS_STATUS.md` — auto-generated table of packs with fresh token
  estimates; agents read it instead of hardcoded numbers (details below).
- `.repomix/audit/<pack>__request.md` — `!audit` brief per pack (new session,
  `file:line` + quote required) plus `CROSS_PACK__request.md` (titles only).

The agent's loading rule (already in the AGENTS.md template): route via
`knowledge/routing-table.md`, then load `core` plus **at most one** domain
pack per task.

Configuration lives in the `index:` section of `kb.config.yml`
(see `templates/kb.config.yml.template`): `window_profile`, optional
`pack_token_ceiling` / `merge_below_tokens` overrides, `repomix_version` and
`npx_fallback` (see "Installing repomix" below), and `packs: auto`
(recommended) or an explicit pack list. In an explicit list a pack name is
used as a file name: path separators become `-`, a leading dot is dropped,
and a repeated name gets a `-2` suffix (with a warning).

```yaml
index:
  packs:
    - name: library-craft
      include: ["knowledge/library/craft/**"]
      when_to_load: "writing-craft questions"
```

`kb_reindex.py` plans the packs, generates `.repomix/configs/<pack>.json`
from the base `repomix.config.json`, builds only stale packs, and **warns
when a pack exceeds the ceiling** — that is the signal to sub-split further
(deeper subfolders, or an explicit `packs:` list).

### Freshness: `.repomix/manifest.json`

After every build `kb_reindex.py` records, per pack, the SHA-256 of its
generated config, of every member file (`files`) and of the ignore files
repomix applies on top of the config (`ignore_sha256`: `.gitignore`,
`.ignore` and `.repomixignore` in the base root and in every member's
folder, `.git/info/exclude`, and the `.gitignore` files above the base up to
the root of an enclosing git work tree), plus the state and the time of the
last successful build. A pack is **fresh** only when its output exists and
all three equal the last successful build — so a deleted, renamed or edited
page always triggers a rebuild, so does hiding or un-hiding a page with
`.gitignore`, and a `touch` without a content change does not. The first run
after an upgrade rebuilds every pack once (older bases have no manifest).

repomix writes each pack into `.repomix/<name>.xml.building` (`-o`); only
when it exits 0 **and** wrote that file does the file replace the pack. A
build that fails or writes nothing is `FAILED` and leaves the previous copy
exactly as it was; that copy never counts as fresh.

After each build `kb_reindex.py` compares the pack's members with the
`<file path=…>` entries of the XML it got (`output.style: xml`, the default).
repomix drops a file silently when its security check finds credential-looking
text in it, or when a `.gitignore` / `.ignore` / `.repomixignore` hides it.
Such files are recorded per pack (`left_out` in the manifest), printed, listed
in `PACKS_STATUS.md` under "Left out by repomix", and counted on the `index:`
line of `STATUS.md` for as long as the pack stays fresh. `kb_lint.py`'s
`secret` check names the lines (`09_LINT.md`).

Packs that left the plan (a renamed section, an edited `packs:` list) are
**removed**: their `.repomix/<name>.xml`, `configs/<name>.json` and
`audit/<name>__request.md`. The legacy `.repomix/output.xml` is never
deleted; in pack mode the run only reminds you that it is safe to delete.

### `.repomix/PACKS_STATUS.md`

Rewritten on every index run — also when nothing could be built — from the
manifest: the check time and the builder used, then one row per pack.

| Column | Meaning |
|--------|---------|
| ~Tokens | Size of the built pack (o200k estimate); for a pack that is not built, the estimate from its source files. `⚠ OVER` follows the number when the pack is over the ceiling. |
| Last build | `rebuilt <time>` (built in this run), `fresh (built <time>)`, `FAILED` (the build failed or wrote no output) or `STALE — repomix unavailable`; the last two add `copy from <time> kept` when an older build is still on disk. |
| Load when | The routing hint. |

A summary line counts `OVER ceiling`, `FAILED` and `STALE` packs by name
and lists orphan packs removed in this run. When the whole index could not be
built (an invalid `repomix.config.json`, an empty explicit list) the file
starts with `**Index not built:** <reason>`.

Bases deployed before pack mode keep working: without an `index:` section
(or with `index.enabled: false`) `kb_reindex.py` builds the old monolithic
index — the base `repomix.config.json`'s `output.filePath`, normally
`.repomix/output.xml` — with the privacy floor, through the same temporary
file, and prints a loud warning once it crosses ~150K tokens, telling you to
enable packs. It records the result in `.repomix/manifest.json`
(`"mode": "legacy"`) and writes `PACKS_STATUS.md` with a single
`output.xml (legacy monolith)` row (ceiling: 150K). A base that goes back
from packs to legacy mode loses its pack files (`.xml`, configs, audit
requests): nothing would refresh them any more.

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
`filePath`, and header, and appending the privacy floor (above) to
`ignore.customPatterns`. Its own `include`/`filePath` are used directly only
in legacy (no `index:` section) mode.

See `templates/repomix.config.json.template` for the full reference copy. Key
points, in either mode:

- `compress: false`, `removeComments: false` — see the section above.
- `ignore.customPatterns` excludes `raw/`, `processed/`, `assets/`, `review/`,
  `interactions/`, `eval/`, `kb-docs/`, `.kb-state/`, `.kb-backups/`,
  `setup/`, `scripts/`, `.repomix/`, logs, `STATUS.md`, `HEAL_PLAN.md`,
  secrets files and all binary formats.
- `tokenCount.encoding: o200k_base`.
- The file must be **plain JSON**. repomix itself tolerates trailing commas
  and comments, Python does not: when `kb_reindex.py` cannot parse the file it
  builds nothing, exits 1, and `PACKS_STATUS.md` says why (the file's ignore
  list is part of what keeps private folders out of the index).

---

## Installing repomix

`kb_reindex.py` uses `repomix` from `PATH` (`npm install -g repomix@1.14.0`;
needs Node.js). Without it, and with `index.npx_fallback: true` (the
default), it runs `npx --yes repomix@<index.repomix_version>` — the version is
pinned (`1.14.0` by default), never `@latest`; the first run downloads it.
With neither available, packs that need a build stay `STALE`, the run prints
how to install repomix and **exits 1**; packs that are already fresh need no
repomix at all.

---

## Running the pipeline: `kb_reindex.py` and `shell/reindex.sh`

`scripts/kb_reindex.py` is the one implementation. `shell/reindex.sh`
(Linux/macOS) only starts it, passing every flag through and returning its
exit status; the Windows double-click launcher `shell/reindex.bat` starts it
without flags; the watcher (`--no-ingest`: it has just ingested) and the git
hook (`--hook`: index and `STATUS.md` only) call it too — one implementation,
so the steps and messages never drift. A full run:

1. ingest (`kb_ingest.py`);
2. routing pages (`kb_route.py`);
3. quick lint (`kb_lint.py --quick`);
4. consolidation, at most every `autorun.consolidation_interval_hours`
   (default 24; `.last_consolidation` marker): lint report, NLP batch, and —
   when `autorun.consolidation_on_reindex` is true (default) —
   `kb_reflect.py --check-threshold`; on `THRESHOLD_MET` it runs
   `kb_reflect.py --generate`, which logs the reflection request in `log.md`;
5. index (packs, or the legacy monolith);
6. `STATUS.md` (below).

| Flag | Effect |
|------|--------|
| *(none)* | Full pipeline. |
| `--quick` | Skip consolidation (step 4). `--no-watch` is a deprecated alias. |
| `--no-ingest` | Skip ingest (the watcher uses it: it has just ingested). |
| `--no-index` | Skip the index (step 5). |
| `--index-only` | Index + `STATUS.md` only. |
| `--force` | Rebuild every pack, fresh or not. |
| `--hook` | Git-hook mode, see below. |

Exit status: `0` when every step that ran succeeded; `1` when `kb_ingest.py`
failed (the other steps still run), the index is incomplete (repomix
unavailable, a pack `FAILED`, invalid `repomix.config.json`) or another run
kept the pipeline lock; `2` when the root has no `kb.config.yml` — run from a
folder that is not a base, the script writes nothing there (`--hook` exits 0).

**One run at a time.** Every run holds the `pipeline` lock
(`.kb-state/locks/pipeline.lock`); the scripts it starts share it. A second
run waits up to 10 minutes, then exits 1.

```bash
python3 scripts/kb_reindex.py --index-only            # only stale packs
python3 scripts/kb_reindex.py --index-only --force    # everything
./shell/reindex.sh --quick                            # same flags via the wrapper
```

---

## `STATUS.md`: the session hand-off

`scripts/kb_status.py` writes `<base>/STATUS.md` (`status.file`) at the end of
every `kb_reindex.py` run, in every mode including `--hook`, unless
`status.enabled: false`. The agent reads it at session start (`!status` runs
the script). It is gitignored and never indexed.

```markdown
# KB status — 2026-09-24T10:00:00+03:00 (generated by kb_status.py, do not edit)

- review queues: needs-ai-decision 3 (oldest 12d) → !review
- merge queue: 2 (oldest 1d) → !merge
- extraction pending in processed/: 9 (oldest 30d) → !review
- stuck in raw/**/unsorted: 2 (duplicate 1, error 1) → python3 scripts/kb_ingest.py --status
- reflection due (changes 31 ≥ 25) → !reflect
- heal: 4 open (assisted 3, human 1) → !heal
- index: 1 pack OVER ceiling, 0 FAILED → see .repomix/PACKS_STATUS.md
- sessions awaiting meta-review: 5 → !meta-review
- lint: 0 errors, 4 warnings → python3 scripts/kb_lint.py
```

Only non-zero lines appear, each ending with the command that resolves it;
with nothing pending the file says `- all clear`. At most one line per input,
so the file stays under 20 lines:

| Line | Input |
|------|-------|
| review queues / merge queue / extraction pending / stuck in unsorted | `kb_ingest.collect_status()` (`kb_ingest.py --status`); `review/needs-merge/` is the merge queue (`!merge` resolves it, `!review` leaves it alone), every other `review/needs-*` folder but `needs-heal` a review queue |
| reflection due | `kb_reflect.check()` — decision `THRESHOLD_MET` |
| heal | the `<!-- heal-summary: … -->` comment on the first line of `review/needs-heal/HEAL_PLAN.md` (written by `kb_heal.py`); without that comment, the number of files waiting in `review/needs-heal/`. That folder is never listed among the review queues: `!heal` resolves it, not `!review` |
| index | `.repomix/manifest.json`: packs over the ceiling, `FAILED`, `STALE` ("not rebuilt"), files repomix left out of a built pack (`left_out`, "left out by repomix"); `index: not built` when the whole build stopped; in legacy mode `index: legacy output.xml FAILED` / `not rebuilt (repomix unavailable)` / `OVER ceiling` |
| sessions awaiting meta-review | `interactions/sessions/**/*.md` without `meta_reviewed: true` in the frontmatter |
| lint | `.kb-state/lint-summary.json` written by `kb_lint.py` |

Every input is optional: a missing or unreadable one drops its line (with a
warning on stderr), never the file.

`status.file` must stay inside the base, and an existing file there is
overwritten only when it is empty or was written by `kb_status.py` (its first
line is the header above). Otherwise — `AGENTS.md`, `kb.config.yml`, a
knowledge page — the script warns and writes `STATUS.md` instead; if that is
someone else's file too, it writes nothing and exits 1. Without a
`kb.config.yml` in the root it exits 2.

```bash
python3 scripts/kb_status.py            # write STATUS.md and print it
python3 scripts/kb_status.py --print    # print only, write nothing
python3 scripts/kb_status.py --json     # {generated_at, file, enabled, all_clear, items: [{key, text, command}]}
```

---

## Git hooks and auto-run

See `13_AUTORUN.md` for the full automation setup:
- File watcher (watchdog daemon) — runs `kb_reindex.py --no-ingest` after it
  has ingested a change
- Git hooks (`shell/install-hooks.sh` installs `shell/hooks/post-commit`)
- Cron (periodic lint + reindex)

The post-commit hook runs `python3 scripts/kb_reindex.py --hook` in the
background: index + `STATUS.md` only — no ingest, routing, lint or
reflection request. It waits at most 5 seconds for the pipeline lock and
otherwise skips (the next run catches up); a filesystem without lock support
also skips. Everything it prints goes to `.kb-state/hooks.log`, and it always
exits 0.

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

Every reindex (step 2, `kb_route.py`) regenerates `knowledge/routing/<section>.md` for each
non-empty section and an auto-managed block (`<!-- AUTO-ROUTING:BEGIN -->` … `END`) inside
`routing-table.md`; the AI agent maintains everything outside that block. Lint verifies that all
routing-table links are valid.
