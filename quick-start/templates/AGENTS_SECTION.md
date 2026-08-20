# AGENTS.md section template — Repomix pack index

> The init agent copies this block into the project's AGENTS.md, fills in the
> pack table, and deletes everything above the `---` line. Keep the final block
> SHORT (~30-40 lines): it is loaded into every session's system prompt, so
> every extra line here is a tax on every future task. Long architecture
> notes belong in docs/, not here.

---

## Context index (Repomix packs)

The codebase is packed into semantic packs under `.repomix/` (gitignored,
rebuilt locally by git hooks). Manifest: `repomix.packs.json`. Fresh sizes:
`.repomix/PACKS_STATUS.md`.

| Pack | Load when | ~Tokens |
|------|-----------|---------|
| `.repomix/catalog.xml` | Always first — directory map, no code | ~9K |
| `.repomix/<domain-a>.xml` | <domain A tasks: …> | ~70K |
| `.repomix/<domain-b>.xml` | <domain B tasks: …> | ~40K |
| `.repomix/platform.xml` | Config / glue / small domains | ~30K |
| `.repomix/migrations.xml` | DB schema tasks only | ~20K |

### Loading rules

1. Do NOT read any full-project XML dump. Never load more than 1 domain pack
   by default; 2 only when the task genuinely spans two domains.
2. Route first: read the pack table above (or `catalog.xml` if you need the
   file inventory), then load EXACTLY ONE domain pack for the task.
3. Edit code from real source files (Read/Grep), never from packed XML copies.
4. Tests live inside their domain's pack — do not look for a separate tests pack.
5. **If you lose the thread mid-session** (you no longer remember the project
   layout or which pack covers what): do not re-read packs you already saw —
   re-read THIS table and `.repomix/PACKS_STATUS.md`, then reload only the one
   pack you need.

### Index maintenance

- Rebuilt automatically on commit/push/pull by git hooks.
- Manual: `scripts/update-repomix-index.sh` (`--force` to rebuild all;
  Windows: `scripts\update-repomix-index.bat`).
- After clone: `scripts/install-git-hooks.sh` (once).
- If the update script warns that a pack exceeds the ceiling — re-run the
  reinit mode of the Repomix init guide to re-split domains.
