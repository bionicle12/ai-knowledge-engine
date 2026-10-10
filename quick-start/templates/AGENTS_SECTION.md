# AGENTS.md section template — Repomix pack index

> The init agent copies this block into the project's AGENTS.md, fills in the
> pack table, and deletes everything above the `---` line. Keep the final block
> SHORT (~30-40 lines): it is loaded into every session's system prompt, so
> every extra line here is a tax on every future task. Long architecture
> notes belong in docs/, not here. Never add token counts: they rot, and a
> stale "~72K" next to a 217K pack is what blows up context windows. Sizes
> live only in `.repomix/PACKS_STATUS.md`.

---

## Context index (Repomix packs)

The codebase is packed into semantic packs under `.repomix/` (gitignored,
rebuilt locally by git hooks). Manifest: `repomix.packs.json`. Sizes, build
state and problems: `.repomix/PACKS_STATUS.md` — the only place with numbers.

| Pack | Load when |
|------|-----------|
| `.repomix/catalog.xml` | Always first — directory map, no code |
| `.repomix/<domain-a>.xml` | <domain A tasks: …> |
| `.repomix/<domain-b>.xml` | <domain B tasks: …> |
| `.repomix/platform.xml` | Config / glue / small domains |
| `.repomix/migrations.xml` | DB schema tasks only |

### Loading rules

1. Before loading a pack, check its row in `.repomix/PACKS_STATUS.md`. A pack
   marked **OVER** (above the ceiling), **FAILED** or **STALE** is never loaded
   whole: use the catalog plus Grep/Read on the real files, and tell the user
   once that it needs a re-split (reinit mode of the init guide) or a rebuild.
2. Do NOT read any full-project XML dump. Never load more than 1 domain pack
   by default; 2 only when the task genuinely spans two domains.
3. Route first: read the pack table above (or `catalog.xml` if you need the
   file inventory), then load EXACTLY ONE domain pack for the task.
4. Edit code from real source files (Read/Grep), never from packed XML copies.
   Files listed as "in no pack" in PACKS_STATUS.md exist only in the sources.
5. **If you lose the thread mid-session**: do not re-read packs you already
   saw — re-read THIS table and `.repomix/PACKS_STATUS.md`, then reload only
   the one pack you need.

### Index maintenance

- Rebuilt automatically on commit/push/pull/rebase/branch switch by git hooks.
- Manual: `scripts/update-repomix-index.sh` (`--force` rebuilds all, `--check`
  only refreshes PACKS_STATUS.md; Windows: `scripts\update-repomix-index.bat`).
- After clone: `scripts/install-git-hooks.sh` (once).
- Problems in PACKS_STATUS.md (OVER, FAILED, files in no pack or in two,
  secret-like strings) → tell the user; re-split only with their approval.
