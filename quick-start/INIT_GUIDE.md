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
> **Reference templates** live next to this guide in `quick-start/templates/`
> of the AI Knowledge Engine checkout: the update script, git hooks, hook
> installer, pack manifest and pack config examples, and the AGENTS.md
> section. Copy them to the exact destinations in Phase 5 (never into the
> project's own `templates/` folder — Twig, Blade, Django… use that name) and
> adapt them; do not retype them from scratch.

---

## Prompts for users (paste into an AI agent session in the target project)

**Fresh project (init):**

> Read quick-start/INIT_GUIDE.md from <path-to-this-repo> and initialize the
> Repomix pack index in this project (mode: init). My context window is
> <400k/256k/200k/1m>. Show me the proposed pack table before writing any configs.

**Already-initialized project — routine rebuild (update):**

> Run scripts/update-repomix-index.sh and report .repomix/PACKS_STATUS.md. If
> any pack is OVER or FAILED, or files are in no pack, tell me — do not
> re-split anything without my approval.

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
> Repomix-индекс в этом проекте (режим init). Окно контекста — <400k/256k/200k/1m>.
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
| `400k` (Codex) | **120K** | catalog + max 1 domain pack | 5–15K |
| `256k` (Cursor / conservative default) | **80K** | catalog + max 1 domain pack | 5–15K |
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
2. **Context window?** (`400k` Codex / `256k` default / `200k` / `1m`) — sets the pack ceiling
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

# Existing hooks / hook manager / AGENTS.md
ls "$(git rev-parse --git-path hooks)" .githooks/ .husky/ 2>/dev/null
git config --get core.hooksPath && echo "HOOK MANAGER: core.hooksPath is set (see Phase 5)"
test -f AGENTS.md && echo "AGENTS.md: EXISTS"
```

## Phase 1: install / locate repomix

```bash
command -v repomix && repomix --version || npm install -g repomix
```

No global install available → `npx --yes repomix@1.14.0` works everywhere
node does. The update script falls back to npx automatically and always runs
the version pinned in the manifest's `repomix_version` (default `1.14.0` — the
version the template ignore globs were verified on), never "latest".
PACKS_STATUS.md names the repomix version of the last build.

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
lock files, binaries, `.git`, IDE dirs, `.repomix/` itself, secrets (`.env`
files, keys, certificates — the config templates end with these patterns in a
form that works on repomix 1.14.0; keep them), generated bundles, huge
fixtures/xlsx/json dumps, **and `AGENTS.md` / `CLAUDE.md`** — they are
already in the system prompt; indexing them doubles their cost.

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
the manifest lists its source folders/files — real paths, never name prefixes
(`docs/plan/08.`) or globs: the update script rebuilds a pack when a file under
them is added, removed, renamed or edited, and reports a watch path that does
not exist. The union of all watch paths is also what the coverage check
(Phase 6) expects to find in exactly one pack; list files that no pack holds on
purpose (fixtures, generated code) in the manifest's `coverage_ignore` (git
pathspecs, `*` also matches `/`). Do not put token counts in the manifest.

**Ignore-glob gotcha (verified on repomix 1.14.0).** When a config has an
`include` list, ignore `customPatterns` of the form `**/*Name*` or `**/.env*`
(bare `**/` prefix, no file extension) are **silently not applied** — the pack
builds without error and comes out 2–4× fatter than measured (or with the
`.env` files inside). Patterns with an explicit root (`src/**/*Name*`), a file
extension (`**/*Name*.php`) or a doubled prefix (`**/**/*Name*`) DO work.
Always write cross-domain ignores in a working form, e.g. `src/**/*Order*.php`
+ `tests/**/*Order*.php`, never `**/*Order*`. Other repomix versions may
behave differently — which is why the npx fallback is pinned and the update
script re-checks coverage on every run.

**Cross-pack ownership.** Domains cut by name prefix overlap: one file can
match two packs' includes (`InspectionProtocol` matches both `*Inspection*`
and `*Protocol*`; a `Service/Task/CourtDecisionResolver` matches a tasks dir
glob and a court name glob). Decide a priority order between domains, then
give the losing pack an explicit ignore for the winner's patterns — every
file must end up in EXACTLY one pack. The coverage check in Phase 6 catches
what you miss.

## Phase 5: infrastructure (scripts + hooks)

Copy each template to exactly this place in the **project root** (`<engine>` =
the AI Knowledge Engine checkout this guide lives in). Never copy the
`templates/` folder itself: many projects already have their own `templates/`
(Twig, Blade, Django, Jinja) and the Repomix files do not belong there.

| From `<engine>/quick-start/templates/` | To `<project>/` |
|----------------------------------------|-----------------|
| `scripts/update-repomix-index.sh` (+ `.bat`) | `scripts/update-repomix-index.sh` (+ `.bat`) — `chmod +x` the `.sh` |
| `scripts/install-git-hooks.sh` (+ `.bat`) | `scripts/install-git-hooks.sh` (+ `.bat`) — `chmod +x` the `.sh` |
| `githooks/post-commit`, `post-merge`, `post-rewrite`, `post-checkout`, `pre-push` | `.githooks/<same name>` — `chmod +x` |
| `repomix.packs.json.example` | `repomix.packs.json` (filled in, Phase 4) |
| `configs/catalog.json.example`, `configs/domain-pack.json.example` | `.repomix/configs/<pack>.json` (one per pack, Phase 4) |
| `AGENTS_SECTION.md` | merged into `AGENTS.md` (Phase 7) |

Then:

```bash
mkdir -p .repomix
./scripts/install-git-hooks.sh
```

The installer copies the hooks into the folder git really runs them from
(`git rev-parse --git-path hooks`, so it also works from a linked worktree).
An existing hook that differs is backed up next to it
(`<hook>.bak-<timestamp>`) and the diff is printed. If `core.hooksPath` is
set (husky, lefthook, …), git ignores `.git/hooks`: the installer copies
nothing, exits 1 and prints the one-liners to add to the hook manager's hooks
instead (`core.hooksPath=.githooks` is detected and works as is).

**Project-specific hook logic** (a CI gate in `pre-push`, a formatter in
`post-commit`) goes into an executable `.githooks/<hook>.local`. Every
template hook runs its `.local` first, with git's arguments and stdin; a
failing `pre-push.local` blocks the push. The template hooks themselves stay
identical to the templates, so a refresh never loses anything.

`.gitignore` gets (build output stays local, the configs are versioned):

```gitignore
# Repomix index: build output stays local; configs are versioned
.repomix/*
!.repomix/configs/
```

This covers the packs, `PACKS_STATUS.md`, `coverage.txt`, the build state
(`packs.state`), the log and its rotated copy, the lock and reinit backups
(`.repomix/backup-*/`). The update script reports in PACKS_STATUS.md when
`.gitignore` does not cover its files.

`.gitattributes` gets (sh scripts and hooks break with CRLF on Windows
checkouts, `.bat` labels with LF):

```gitattributes
scripts/update-repomix-index.sh text eol=lf
scripts/install-git-hooks.sh text eol=lf
scripts/update-repomix-index.bat text eol=crlf
scripts/install-git-hooks.bat text eol=crlf
.githooks/* text eol=lf
```

**Commit** `repomix.packs.json`, `.repomix/configs/`, `scripts/`, `.githooks/`,
`.gitignore`, `.gitattributes`. The XML packs themselves stay local — which is
exactly why the rebuild machinery must be robust (PATH bootstrap, pinned npx
fallback, nohup, locking, logging, always exit 0 — all already inside the
template script; do not simplify it).

Why these hooks: `post-commit` alone is not enough — `git push` doesn't fire
it, merges/rebases change files without commits, and switching branches
changes files without any of them (`post-checkout`, branch checkouts only).
`pre-push` runs synchronously (with stdin detached — git feeds refs there)
but never waits for a build that is already running; the rest run in
background via nohup so git stays fast. When hooks fire in a row (a rebase of
5 commits, `commit --amend`), a run that finds a build in progress only
queues a re-check that the running build performs when it finishes — usually
two builds, never more than three passes per run; a re-check queued after the
last pass waits for the next hook or manual run. `git reset --hard` and `git stash` fire no hook: the next hook or
a manual run picks those changes up (freshness is decided by the file list and
contents, so nothing is missed, only delayed).

Document in README (one line): *"After clone run `./scripts/install-git-hooks.sh`
to enable automatic AI-index rebuilds."*

No git in the project → skip hooks; the update script alone is the manual
`reindex` entry point (without git it also cannot check coverage).

## Phase 6: first build + verification

```bash
./scripts/update-repomix-index.sh --force
cat .repomix/PACKS_STATUS.md
```

Verify in PACKS_STATUS.md: no pack marked OVER or FAILED; catalog in the
5–15K band (a `files: false` catalog may come in under 5K — that's fine, less
routing tax); no "Problems" section. Fix the split now, not later.

**Coverage check (automatic, on every run).** Sizes alone don't prove the
split is right — a silently-dropped ignore (see the glob gotcha in Phase 4) or
a domain overlap leaves packs looking plausible while files are orphaned or
double-indexed. The update script compares the text files under all watch
paths (git-tracked or untracked-but-not-ignored; `AGENTS.md`, `CLAUDE.md`,
`.repomix/` and the secret files the config templates exclude are left out)
with the `<file path="…">` entries of every pack and
reports in PACKS_STATUS.md:

- **files in no pack** (orphans) — add them to a pack, or to
  `coverage_ignore` when leaving them out is intended;
- **files in two or more packs** (duplicates) — resolve with cross-pack
  ignores per the ownership priority chosen in Phase 3.

The check knows the exclusions above and `coverage_ignore`, not repomix's own
default ignore list (lock files and the like) or a `.repomixignore`: files
repomix skips by itself show up as "in no pack" — list them in
`coverage_ignore`. Outside a git work tree the check cannot run;
PACKS_STATUS.md then says "Coverage not checked" as a note, not a problem.

The full lists are in `.repomix/coverage.txt`. The target is 0 and 0. On a
real reinit this check caught 5 duplicated files and a platform pack that had
silently ballooned from 34K to 160K with zero build warnings.

The same run also greps every pack for secret-like strings (GitHub, AWS,
Slack, Stripe, OpenAI-style keys, PEM private keys) and records what repomix's
own secret check excluded — both appear under "Problems" (file paths only,
never the values) and in `.repomix/update.log`.

## Phase 7: AGENTS.md

Copy the block from `templates/AGENTS_SECTION.md` into the project's AGENTS.md,
fill in the pack table. Hard rules:

- **Never** write "read the full output.xml before large tasks" — that
  instruction is what blows up context windows.
- Keep the section ~30–40 lines. Long architecture text goes to `docs/`.
- **No token numbers** anywhere in AGENTS.md (the template table has no size
  column): they rot — a pack listed as "~72K" grew to 217K unnoticed. Sizes,
  OVER/FAILED flags and problems live only in `.repomix/PACKS_STATUS.md`.
- Keep the rule "a pack marked OVER, FAILED or STALE in PACKS_STATUS.md is
  never loaded whole".
- Keep the "if you lose the thread mid-session" recovery rule from the
  template: it tells the agent to re-read the small routing table instead of
  re-reading packs when a long chat starts degrading.

## Init checklist

```
[ ] repomix available (global, or the pinned npx fallback)
[ ] Token census done; domains cut; table approved by user
[ ] repomix.packs.json (watch = real paths) + .repomix/configs/*.json written and committed
[ ] scripts/ + .githooks/ copied to the Phase 5 destinations, executable, committed; hooks installed
[ ] .gitignore and .gitattributes blocks from Phase 5 added
[ ] First build: PACKS_STATUS.md shows no OVER/FAILED, catalog 5–15K
[ ] PACKS_STATUS.md has no Problems: 0 files in no pack, 0 in two packs, no secrets
[ ] AGENTS.md: pack table without token numbers + loading rules (short!), no "read everything" advice
```

---

# Mode: update

Routine rebuild — this is what hooks run; agents/users can also run it manually:

```bash
./scripts/update-repomix-index.sh            # rebuilds changed packs only
./scripts/update-repomix-index.sh --force    # rebuilds everything
./scripts/update-repomix-index.sh --check    # builds nothing: refreshes PACKS_STATUS.md,
                                             # exit 1 when it has warnings
```

Behavior (already implemented in the template script — keep it intact):

- Per-pack freshness from the file list and index state under the manifest's
  `watch` paths (git; a plain file listing without git) plus file mtimes, the
  pack's manifest entry and its config: added, deleted, renamed and edited
  files all trigger a rebuild. The first run after a script upgrade rebuilds
  every pack once.
- Writes `.repomix/PACKS_STATUS.md` on every run: per pack the token count
  repomix reported, `ok`/`OVER` against the ceiling (for fresh packs too),
  `fresh`/`rebuilt`/`STALE`/`FAILED` and the build time; a header with the
  time, HEAD and repomix version; banner lines for OVER/FAILED/STALE packs; a
  "Problems" section (coverage, watch paths that do not exist, secrets,
  outdated `.gitignore`, a leftover monolithic `output.xml`).
- A pack whose build fails keeps its row as `FAILED (old copy)` or
  `FAILED (no output)` and is retried on the next run; the log records the
  real exit code and the tail of repomix's output.
- A pack whose config's `output.filePath` is not its manifest `output` is not
  built: its row says `FAILED (config writes …)` and "Problems" names both
  paths (repomix would write a file the manifest does not know).
- Pack XMLs in `.repomix/` that no manifest pack produces any more (renamed or
  dropped packs) are deleted (only files with the repomix header;
  `output.xml` is only reported).
- **Warns** when a pack exceeds the ceiling — the agent must then *offer* a
  re-split (reinit) to the user, never silently re-cut, and never silently
  let packs bloat.
- Legacy mode: no manifest → plain monolith rebuild + a warning at >150K
  suggesting reinit.
- One build at a time (`flock`, or a `mkdir` lock on macOS/Git Bash); hook
  runs (`--background`, and `--no-wait` in pre-push) never wait for it — they
  queue one re-check. A manual run waits up to 5 minutes. Never blocks git (exit 0
  everywhere except `--check`), logs to `.repomix/update.log` (rotated to
  `update.log.1` above 1 MB).

Agent rules in update mode:

1. Do not rewrite `repomix.packs.json` — the user may have hand-tuned it.
2. Read the "Problems" section of PACKS_STATUS.md: files in no pack → tell the
   user, propose adding them to an existing pack or a new one (or to
   `coverage_ignore`); a watch path that does not exist → propose the real
   path; secret-like strings → propose the exclusion right away.
3. OVER / ceiling warnings → propose reinit; apply only after approval.
4. **AGENTS.md is merged, never replaced.** It is a live file the team and
   agents evolve between runs. If its Repomix section needs refreshing, read
   the current file, edit ONLY what changed (pack table rows, removal of old
   token numbers), keep every local addition, and show the diff before writing.
5. Older setups (no `post-checkout` hook, the four-line `.repomix/…`
   `.gitignore` list, token counts in AGENTS.md or the manifest) → propose the
   reinit steps 5–6 below.

---

# Mode: reinit (migration / re-split)

When: monolith >150K; a pack outgrew the ceiling; the domain structure drifted;
or the project wants to adopt this guide's fixes over an old-style setup
("подкинуть скрипт заново и переразвернуть").

1. **Inventory the old setup:** existing `repomix.config.json`,
   `.repomix/*.xml`, `repomix.packs.json`, `.githooks/`, the installed hooks
   (`git rev-parse --git-path hooks`, `core.hooksPath`, `.husky/`), the Repomix
   section in AGENTS.md. Old broken patterns to expect: post-commit-only hook,
   silent `command -v repomix` no-op, backgrounding without nohup, config in
   .gitignore, "read the full index" advice and token numbers in AGENTS.md,
   `watch` entries that are name prefixes.
2. **Back up:** copy old configs + manifest to `.repomix/backup-<date>/`
   (never delete user files; the Phase 5 `.gitignore` block keeps backups out
   of git).
3. **Re-measure** from scratch (Phase 2) and **re-cut** domains (Phase 3).
4. **Show the diff**: old packs vs new packs (or "monolith → N packs"), with
   token numbers. If the user hand-edited an existing manifest, show their
   customizations explicitly before replacing anything. Wait for approval.
5. **Refresh scripts and hooks, keeping local logic.** Before overwriting any
   project copy of `scripts/update-repomix-index.sh`, `scripts/install-git-hooks.sh`
   or `.githooks/*`, diff it against the new template
   (`diff -u .githooks/pre-push <engine>/quick-start/templates/githooks/pre-push`).
   Lines that come from no template (a CI gate, extra commands) are
   project-specific: show them to the user and move hook logic into
   `.githooks/<hook>.local` (executable) before copying the template over;
   never drop them silently. Then run the installer — it backs up and diffs
   any installed hook it replaces.
6. Write configs (Phase 4), update `.gitignore`/`.gitattributes` (Phase 5),
   rebuild (Phase 6), update the AGENTS.md section (Phase 7) — **delete** any
   old "DO read output.xml" instruction and all token numbers. **Merge
   AGENTS.md, never regenerate it**: it accumulates the project's own rules
   between runs — edit the Repomix section in place, preserve everything else,
   show the diff before writing.
7. Remove the obsolete monolith `output.xml` from disk if packs replace it
   (after user approval), or leave it with a "do not read whole" note in
   AGENTS.md if the user wants a CI artifact (PACKS_STATUS.md keeps
   reporting it). Leftover pack XMLs of renamed packs are deleted by the
   update script itself.

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
