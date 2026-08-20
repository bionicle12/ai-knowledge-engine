# Repomix — Universal init/update/reinit guide for AI agents (v2)

> **Purpose:** This document is an instruction set for an AI agent. Read it and
> follow the steps to set up (or upgrade) a Repomix context index in any user
> project.
>
> **Core idea of v2:** one giant `output.xml` is an anti-pattern. On real
> projects it grows past the model's context window (a 452-file Symfony backend
> hit ~258K tokens — instant overflow on a 256K window *before the task even
> started*). Instead, the index is a set of **semantic domain packs**, each
> under a token ceiling, plus a small **catalog**, plus a short routing table in
> AGENTS.md. The agent loads the catalog and AT MOST ONE domain pack per task.
>
> **Reference templates** live next to this guide in `quick-start/templates/`:
> the update script, git hooks, hook installer, pack manifest and pack config
> examples, and the AGENTS.md section. Copy and adapt them — do not retype
> them from scratch.

---

## Prompts for users (paste into an AI agent session in the target project)

**Fresh project (init):**

> Read quick-start/INIT_GUIDE.md from <path-to-this-repo> and initialize the
> Repomix pack index in this project (mode: init). My context window is
> <256k/200k/1m>. Show me the proposed pack table before writing any configs.

**Already-initialized project — routine rebuild (update):**

> Run scripts/update-repomix-index.sh and report the pack status. If any pack
> exceeds the ceiling, tell me — do not re-split anything without my approval.

**Already-initialized project — old monolithic index, or packs went stale
(reinit):**

> Read quick-start/INIT_GUIDE.md from <path-to-this-repo> and REINITIALIZE the
> Repomix index in this project (mode: reinit). There may be an existing
> .repomix/output.xml, an old repomix.config.json and old git hooks — measure
> everything from scratch, propose a new pack split, show me the diff against
> the current setup, back up the old configs, and migrate. Do not delete my
> manual edits to repomix.packs.json without showing them to me.

Russian variants (равнозначны):

> Прочитай quick-start/INIT_GUIDE.md из <путь> и инициализируй пакетный
> Repomix-индекс в этом проекте (режим init). Окно контекста — <256k/200k/1m>.
> Покажи таблицу пакетов до записи конфигов.

> Прочитай quick-start/INIT_GUIDE.md из <путь> и ПЕРЕинициализируй
> Repomix-индекс (режим reinit): тут старый монолитный output.xml и старые
> хуки. Померь всё заново, предложи нарезку на пакеты, покажи diff со старой
> схемой, сделай backup старых конфигов и мигрируй.

---

## Mode selection (agent: do this first)

Detect the project's current state and pick the mode:

| State | Mode |
|-------|------|
| No `repomix.config.json`, no `.repomix/` | **init** |
| `repomix.packs.json` exists | **update** (or **reinit** if the user asked to re-split) |
| Only a monolithic `repomix.config.json` + `.repomix/output.xml` | **update-legacy** → recommend **reinit** if the monolith is >150K tokens |

Estimate monolith size without building: `tokens ≈ bytes / 4` for an existing
XML, or run `repomix --token-count-tree` (see Phase 2).

---

## Token budget profiles (constants)

| Window profile | Pack ceiling | Per-session budget | Catalog target |
|---------------|-------------|--------------------|----------------|
| `256k` (default, conservative) | **80K** | catalog + max 1 domain pack | 5–15K |
| `200k` | 60K | catalog + max 1 domain pack | 5–15K |
| `1m` | 150K | catalog + 1–2 domain packs | 5–15K |

Success metric: an agent on a 256K window **never** reads a ≥150K dump whole.
Comfortable whole-file reads top out at ~80–100K.

Merge threshold: domains under **15K** tokens get merged into a shared
`platform` (or `aux`) pack instead of getting their own file — 20 tiny packs
are as bad for routing as one giant one.

---

# Mode: init

## Phase 0: pre-analysis

Ask the user (skip what's obvious from the project):

1. **Project type / stack?** (drives include patterns)
2. **Context window?** (`256k` default / `200k` / `1m`) — sets the pack ceiling
3. **Legacy / archive folders** to exclude entirely?
4. **Priority: token economy or completeness?** For **code**, default to
   `compress: true, removeComments: true, removeEmptyLines: true`. For
   **knowledge bases / prose**, always `compress: false` — see the dedicated
   section at the end.

Automated analysis:

```bash
# Structure
find . -maxdepth 3 -type d ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/vendor/*' ! -path '*/target/*' ! -path '*/dist/*' ! -path '*/__pycache__/*' ! -path '*/.venv/*' | sort

# Git present?
git rev-parse --is-inside-work-tree 2>/dev/null && echo "GIT: YES" || echo "GIT: NO"

# Existing hooks / AGENTS.md
ls .git/hooks/ .husky/ 2>/dev/null; test -f AGENTS.md && echo "AGENTS.md: EXISTS"
```

## Phase 1: install / locate repomix

```bash
command -v repomix && repomix --version || npm install -g repomix
```

No global install available → `npx --yes repomix` works everywhere node does.
(The update script already falls back to npx automatically.)

**Windows note:** everything in this guide runs in Git Bash (bundled with Git
for Windows). Git executes `.sh` hooks through its own `sh.exe`, so hooks need
no special handling. For manual cmd/double-click runs the templates include
`.bat` wrappers.

## Phase 2: measure

Run a token census before deciding anything:

```bash
# Per-directory/per-file token costs (files >1K tokens)
repomix --token-count-tree 1000 --no-files -o /dev/null 2>/dev/null || repomix --token-count-tree 1000
```

If that's slow on a huge repo, estimate: `tokens ≈ chars / 3.8` (o200k_base,
mixed code). Record: total tokens, per-top-folder tokens, the top-10 fattest
files.

**Small projects still get packs.** Even when the whole project (compressed)
fits under the ceiling, do NOT fall back to a single monolithic `output.xml`:
projects grow unnoticed, and the monolith has no growth alarm. Instead create
the minimal pack setup — `catalog` + one `app` pack holding everything — under
the same manifest. It costs nothing extra, and the update script's ceiling
warning automatically tells you when the project has outgrown one pack and
needs a real domain split (reinit).

## Phase 3: cut domains (the individual part — never hardcode)

**This phase is a per-project decision, not a template.** The examples in
`templates/` show the FILE FORMAT only — the actual split must come from
measuring *this* project and thinking about what an agent will be asked to do
in it. Every stack cuts differently:

- **Symfony/Laravel-style backend:** domains follow business entities across
  layers (`src/Controller/Order*` + `src/Service/Order/` + its tests = one
  `orders` pack), migrations separate, framework `vendor/` excluded.
- **WordPress and similar CMS:** most of the tree is system code nobody edits
  (`wp-admin/`, `wp-includes/`, third-party plugins) and it is HUGE — exclude
  it from packs entirely (it may appear in the catalog tree at most). Index
  what actually gets edited: the custom theme, custom plugins, ACF/config
  exports. A "whole project" pack of a WordPress site is 95% dead weight.
- **JS/TS monorepo:** packs per workspace/package, shared libs as their own
  pack; generated bundles and design-token dumps excluded.
- **Data/ML project:** notebooks and datasets excluded or catalog-only;
  pipelines/models code packed by pipeline stage.

The question to answer for every candidate folder: *"will an agent ever be
asked to change this, and does it need to see it whole?"* — heavy,
never-edited framework/system/generated code is excluded (or catalog-only),
no matter how big it is; the packs exist for the data that matters.

Cluster the measured tree into semantic domains **by the kinds of tasks an
agent will get**, not by `src/` vs `tests/`:

1. **Candidates:** top-level folders (`src/Service/Task`, `app/modules/…`),
   name prefixes (`Inspection*`, `Task*`, `Map*`), and each domain's tests
   (`tests/Service/Task` belongs to the `tasks` pack, NOT to a tests pack).
2. **Merge** every domain under 15K into `platform`.
3. **Split** every domain over the ceiling: by subfolder, by moving its tests
   into a `<domain>-tests` pack (only as a last resort), or by extracting fat
   one-offs (imports, generated code, fixtures) into their own rarely-loaded
   pack.
4. `migrations` / schema dumps → separate pack, loaded only for schema tasks.
5. Always create the **catalog** pack: metadata only (`"files": false`), full
   directory structure, no code bodies.

**What to exclude from every pack:** vendor, node_modules, var, dist, build,
lock files, binaries, `.git`, IDE dirs, `.repomix/` itself, secrets/pem,
generated bundles, huge fixtures/xlsx/json dumps, **and `AGENTS.md` /
`CLAUDE.md`** — they are already in the system prompt; indexing them doubles
their cost.

Example split from a real Symfony backend (~258K monolith, 256K window) — a
sample of the *method*, not a template:

| Pack | Contents | ~Tokens |
|------|----------|---------|
| catalog | tree + inventory | 9K |
| inspections | cards, protocols, court + their tests | 72K |
| tasks | workflow, auto-tasks + tests | 40K |
| map, logs | small domains + tests | 13–14K each |
| platform | config, import, admin, glossary, support | 25–40K |
| migrations | schema | 22K |

## Phase 4: present the table, then write configs

**Show the user the proposed table** (pack / ~tokens / globs / when_to_load)
and let them adjust it **before** writing anything. The split IS the
per-project configuration.

After approval write:

```
repomix.packs.json           # manifest — commit (template: templates/repomix.packs.json.example)
.repomix/configs/<pack>.json # per-pack configs — commit (templates/configs/*.example)
repomix.config.json          # optional base config for bare `repomix` runs; if
                             # kept, point it at the catalog rather than a monolith
```

Per-pack configs (via `repomix -c`) are used instead of `--include` flags so
CLI/config merge semantics can never surprise us. Each pack's `watch` array in
the manifest lists its source roots — the update script uses them for
skip-if-fresh checks.

## Phase 5: infrastructure (scripts + hooks)

Copy from `quick-start/templates/`:

```
scripts/update-repomix-index.sh    # chmod +x
scripts/update-repomix-index.bat   # Windows manual wrapper
scripts/install-git-hooks.sh       # chmod +x
scripts/install-git-hooks.bat
.githooks/pre-push post-commit post-merge post-rewrite   # chmod +x
```

Then:

```bash
mkdir -p .repomix
./scripts/install-git-hooks.sh
```

`.gitignore` gets:

```
.repomix/*.xml
.repomix/update.log
.repomix/update.lock
.repomix/PACKS_STATUS.md
```

**Commit** `repomix.packs.json`, `.repomix/configs/`, `scripts/`, `.githooks/`.
The XML packs themselves stay local — which is exactly why the rebuild
machinery must be robust (PATH bootstrap, npx fallback, nohup, logging, always
exit 0 — all already inside the template script; do not simplify it).

Why these hooks: `post-commit` alone is not enough — `git push` doesn't fire
it, and merges/rebases change files without commits. `pre-push` runs
synchronously (with stdin detached — git feeds refs there); the rest run in
background via nohup so git stays fast.

Document in README (one line): *"After clone run `./scripts/install-git-hooks.sh`
to enable automatic AI-index rebuilds."*

No git in the project → skip hooks; the update script alone is the manual
`reindex` entry point.

## Phase 6: first build + verification

```bash
./scripts/update-repomix-index.sh --force
cat .repomix/PACKS_STATUS.md
```

Verify: every pack under the ceiling; catalog in the 5–15K band; the script
warns about any pack over the ceiling. Fix the split now, not later.

## Phase 7: AGENTS.md

Copy the block from `templates/AGENTS_SECTION.md` into the project's AGENTS.md,
fill in the pack table. Hard rules:

- **Never** write "read the full output.xml before large tasks" — that
  instruction is what blows up context windows.
- Keep the section ~30–40 lines. Long architecture text goes to `docs/`.
- Don't hardcode token numbers that will rot — the table points to
  `.repomix/PACKS_STATUS.md` for fresh values.
- Keep the "if you lose the thread mid-session" recovery rule from the
  template: it tells the agent to re-read the small routing table instead of
  re-reading packs when a long chat starts degrading.

## Init checklist

```
[ ] repomix available (global or npx)
[ ] Token census done; domains cut; table approved by user
[ ] repomix.packs.json + .repomix/configs/*.json written and committed
[ ] scripts/ + .githooks/ copied, executable, committed; hooks installed
[ ] .gitignore covers .repomix/ artifacts
[ ] First build: all packs under ceiling, catalog 5–15K
[ ] AGENTS.md: pack table + loading rules (short!), no "read everything" advice
```

---

# Mode: update

Routine rebuild — this is what hooks run; agents/users can also run it manually:

```bash
./scripts/update-repomix-index.sh            # skips fresh packs
./scripts/update-repomix-index.sh --force    # rebuilds everything
```

Behavior (already implemented in the template script — keep it intact):

- Per-pack skip-if-fresh via the manifest's `watch` roots (mtime comparison);
  manifest/config edits also trigger a rebuild.
- Writes `.repomix/PACKS_STATUS.md` with fresh token estimates.
- **Warns** when a pack exceeds the ceiling — the agent must then *offer* a
  re-split (reinit) to the user, never silently re-cut, and never silently
  let packs bloat.
- Legacy mode: no manifest → plain monolith rebuild + a warning at >150K
  suggesting reinit.
- Never blocks git (exit 0 everywhere), logs to `.repomix/update.log`.

Agent rules in update mode:

1. Do not rewrite `repomix.packs.json` — the user may have hand-tuned it.
2. A new top-level folder that matches no pack's globs → tell the user, propose
   adding it to an existing pack or creating a new one.
3. Ceiling warnings → propose reinit; apply only after approval.
4. **AGENTS.md is merged, never replaced.** It is a live file the team and
   agents evolve between runs. If its Repomix section needs refreshing, read
   the current file, edit ONLY what changed (pack table rows, stale numbers),
   keep every local addition, and show the diff before writing.

---

# Mode: reinit (migration / re-split)

When: monolith >150K; a pack outgrew the ceiling; the domain structure drifted;
or the project wants to adopt this guide's fixes over an old-style setup
("подкинуть скрипт заново и переразвернуть").

1. **Inventory the old setup:** existing `repomix.config.json`,
   `.repomix/*.xml`, `repomix.packs.json`, hooks in `.git/hooks/` and
   `.husky/`, the Repomix section in AGENTS.md. Old broken patterns to expect:
   post-commit-only hook, silent `command -v repomix` no-op, backgrounding
   without nohup, config in .gitignore, "read the full index" advice in
   AGENTS.md.
2. **Back up:** copy old configs + manifest to `.repomix/backup-<date>/`
   (never delete user files).
3. **Re-measure** from scratch (Phase 2) and **re-cut** domains (Phase 3).
4. **Show the diff**: old packs vs new packs (or "monolith → N packs"), with
   token numbers. If the user hand-edited an existing manifest, show their
   customizations explicitly before replacing anything. Wait for approval.
5. Write configs (Phase 4), refresh scripts/hooks from the current templates
   (Phase 5 — overwrite old copies of `update-repomix-index.sh`/hooks; the
   installer backs up foreign hooks automatically), rebuild (Phase 6), update
   the AGENTS.md section (Phase 7) — **delete** any old "DO read output.xml"
   instruction and stale token numbers. **Merge AGENTS.md, never regenerate
   it**: scripts and hooks are safe to overwrite from templates, but AGENTS.md
   accumulates the project's own rules between runs — edit the Repomix section
   in place, preserve everything else, show the diff before writing.
6. Remove the obsolete monolith `output.xml` from disk if packs replace it
   (after user approval), or leave it with a "do not read whole" note in
   AGENTS.md if the user wants a CI artifact.

---

# Knowledge bases and prose projects (non-code)

Two hard differences from code:

1. **`compress: false`, `removeComments: false` — always.** Tree-sitter
   compression strips "bodies", which for code is acceptable (structure
   survives) but for knowledge text destroys exactly the content the base
   exists to preserve. Wording, nuance and full paragraphs ARE the payload.
   The price is bigger packs — compensate by splitting more aggressively, not
   by compressing.
2. **Packs follow content sections, not code domains:** e.g. a writer's base →
   `core` (profile, principles, voice, routing tables), `domain`, `insights`,
   and the library shelf-by-shelf (`library-craft`, `library-marketing`, …).
   A "library of reference books" must NEVER share a pack with the working
   knowledge — books are loaded only when the task is about them.

For bases deployed from the AI Knowledge Engine, this is automated: the
`index:` section of `kb.config.yml` + `kb_reindex.py` build the packs and
auto-split oversized sections by subfolder (see `knowledge-base/05_INDEX.md`).
For ad-hoc prose projects, apply this guide manually with the same profiles
and the `compress: false` rule; binary sources (docx/pdf/pptx) are converted
to Markdown first (pandoc / marker) and the originals excluded, with short
descriptions in `assets-index/*.md`.
