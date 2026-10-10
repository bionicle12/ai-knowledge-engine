# 14 — Initial Population Helper

> After `02_INIT` completes, the agent **must** generate a personalized `DATA_PLACEMENT_EXAMPLES.md` for the chosen role. This eliminates the "empty folders" effect: the user looks at `raw/work/unsorted/` and has no idea what to drop there.
>
> **Reference template:** `knowledge-base/templates/DATA_PLACEMENT_EXAMPLES.md.template` — a starting skeleton.
> **Reference role template (for custom roles):** `knowledge-base/templates/role.yml.template`.
> **Reference generator (preferred):** `scripts/kb_populate.py` — yaml → markdown without LLM tokens.
> **Structure sketches (before folders):** `scripts/kb_structure.py` — four variants + blind-spot list from the same YAML (`02_INIT.md`).
> **Source of examples:** the `placement_examples:` section inside `examples/<role>.yml`.
>
> ⚠️ **Path note:** during deployment the base lives at `<project-root>/knowledge-base/`, so `--kb-root knowledge-base` is the correct argument while building. After `setup/shell/finalize.sh` the base is flat at the project root and re-runs use `--kb-root .` (or omit the flag, since cwd is the root). The examples below assume the deployment-time path.

---

## Two paths

The agent has two ways to produce `DATA_PLACEMENT_EXAMPLES.md`:

| Path | When | Cost |
|------|------|------|
| **A. Built-in role** — user picked an existing template | Run `kb_populate.py --role <role>` then optional review | ~50 tokens (just to invoke the script) |
| **B. Custom role** — user invented a new role | Build `examples/<slug>.yml` from `role.yml.template`, save it, then path A | ~3-8K tokens (yaml authoring) + script invocation |

Both end with **the same optional review step** where the agent reads the generated file and adds project-specific notes the YAML couldn't capture.

### How `--role` finds the YAML

`--role` takes the file name (`programmer-senior` or `programmer-senior.yml`)
**or** the `role:` title inside the YAML (`"Senior Software Engineer"`,
case-insensitive). The script looks in `<kb-root>/examples/` (default: the
current directory) first, then in the `examples/` next to its own `scripts/`
folder — so a custom role saved in `knowledge-base/examples/` is found even
when `setup/scripts/kb_populate.py` runs. `kb_structure.py --role` resolves
roles the same way. Without `--role` and `--from`, the role is
`knowledge_base.roles.primary` from `<kb-root>/kb.config.yml` (that is what
`!populate` uses), so `roles.primary` must be a YAML's file name or its
`role:` title. An unknown role exits 1 and lists the known ones; when the role
came from `roles.primary`, the message says so.

---

## Path A: built-in role

1. User picks (or agent suggests) a role from `examples/` — every `*.yml` there
   is a role (`ls examples/`), e.g. `programmer-senior`, `marketing-director`,
   `product-manager`, `researcher`, `founder`, `content-creator`,
   `fiction-writer`, `psychologist-gestalt`.
2. Agent runs (during deployment, before `finalize.sh`):
   ```bash
   python3 knowledge-base/scripts/kb_populate.py --role <role> --kb-root knowledge-base
   ```
   Or, if the agent's cwd is already inside `knowledge-base/`:
   ```bash
   python3 scripts/kb_populate.py --role <role> --kb-root .
   ```
3. (Optional) `--create-samples` flag also writes `raw/_samples/` placeholder files.
4. Agent **reads** the generated `DATA_PLACEMENT_EXAMPLES.md` and proceeds to the review step (below).

This path uses **0 LLM tokens** for the actual generation — `kb_populate.py` is pure templating.

`--dry-run` prints the file instead of writing it; `--json` prints a summary.

---

## Path B: custom role (invented on the fly)

When the user describes a role that isn't in `examples/`, the agent **must create the YAML first** before any populating happens.

### B.1. Create the role YAML

1. Copy `templates/role.yml.template` to `knowledge-base/examples/<slug>.yml` (in the deployed base, while it still lives at `<project>/knowledge-base/`).
2. The agent fills placeholders by **interviewing the user**:
   - `{{ROLE_TITLE}}` — short title
   - `{{ROLE_DESCRIPTION}}` — 2-3 sentences
   - `entities:` — 3-5 entries with `why` and `knowledge_paths`
   - `raw_data_examples:` — 5-10 typical artifact types
   - `ai_assistant_tasks:` — 5-7 tasks the assistant should be useful for
   - **`placement_examples:`** — the part `kb_populate.py` consumes:
     - `intro` — 1-2 paragraphs in the user's voice
     - `by_artifact` — 5-9 concrete artifact entries
     - `quickstart` — 3-5 first-impression steps
     - `do_not_drop` — 3-5 role-specific exclusions

3. Use the same text as `role:` for `knowledge_base.roles.primary` in
   `kb.config.yml` (the `{{PRIMARY_ROLE}}` placeholder, `02_INIT.md` Phase 2).
   `!populate` runs without `--role` and finds the YAML by that title; a
   title that matches no `examples/*.yml` makes it exit 1.
4. Validate the file parses:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('knowledge-base/examples/<slug>.yml'))"
   ```

### B.2. Then run kb_populate

Once the YAML is on disk, the workflow is identical to Path A:

```bash
python3 knowledge-base/scripts/kb_populate.py --role <slug> --kb-root knowledge-base
```

> **Why save the YAML first instead of generating directly?** Two reasons:
> 1. The YAML becomes a reusable artifact — re-running `kb_populate.py` after edits is cheap and deterministic.
> 2. The user can refine the role over time (add entities, tweak placement) without re-engaging the LLM.

---

## Helper: copy the role's entities into `kb.config.yml`

`kb.config.yml` starts with `entities: {}`. Once the config exists
(`02_INIT.md`, Phase 2), copy the role's `entities:` mapping instead of
retyping it:

```bash
python3 knowledge-base/scripts/kb_populate.py --entities-from <role> --kb-root knowledge-base
```

- `<role>` is resolved like `--role` (file name or title; custom roles in
  `knowledge-base/examples/` included).
- The edit is line-based: every other key, comment and blank line of
  `kb.config.yml` stays as it was. The block starts with a
  `# Copied from … by kb_populate.py --entities-from` comment.
- It only fills a missing or empty `entities:` (`entities:`, `entities: {}`).
  When the config already has entities, nothing changes (exit 0, message
  "already has entities") — those are the owner's.
- Then drop the entities the owner did not confirm and add the ones they
  asked for, by hand.
- `--dry-run` shows the block that would be copied (or says the config
  already has entities) and leaves `kb.config.yml` untouched; with `--json`
  the summary carries `"dry_run": true` and `"would_copy"`.
- No `kb.config.yml` in `--kb-root` → exit 2; a role without `entities:` → exit 1.

---

## Optional step: AI review pass

After `kb_populate.py` writes the file, the agent **should** read it and look for improvements:

| Goal | Examples of additions |
|------|-----------------------|
| Project-specific notes | "Drop your highway-clicker README first since most context is there" |
| Tool stack | "Your stack is Rust + React, so add `Cargo.toml` and `package.json` to early ingest" |
| User-stated preferences | "User said they hate slack export noise — emphasize `review/needs-redaction/`" |
| Quickstart sharpening | Pick the *one* file in the user's environment that will demonstrate value fastest |

The generated part ends with the line

```markdown
<!-- kb_populate: everything above is regenerated; notes added below this line are kept on re-run -->
```

The agent appends a `## Project notes` section **below that line**. Do not
edit anything above it: a re-run rewrites everything above the marker and
keeps everything below it. (A file generated before the marker
existed keeps its `## Project notes` section — from that heading to the end
of the file — and gets the marker on the next run.)

This pass typically costs ~1-2K tokens and is genuinely valuable. If the user is on a tight budget, skip it and proceed.

---

## Optional step: `raw/_samples/`

If the user wants format examples (or `--create-samples` was passed):

```bash
python3 knowledge-base/scripts/kb_populate.py --role <role> --create-samples --kb-root knowledge-base
```

This writes `raw/_samples/<artifact-slug>.example.md` for each artifact in `placement_examples.by_artifact`. The folder is excluded from ingest (name starts with `_`).

---

## When to regenerate

| Trigger | Action |
|---------|--------|
| User edits `examples/<role>.yml` | Re-run `kb_populate.py` — the generated part is rewritten, notes below the marker are kept |
| User wants different artifact set | Edit YAML → re-run script |
| `!populate` command from user | `python3 scripts/kb_populate.py --kb-root .` (role from `knowledge_base.roles.primary`) + AI review pass |
| New role discovered post-deploy | Create new YAML (Path B), then run script |

---

## Trigger points

| When | Action |
|------|--------|
| End of `02_INIT` (deployment) | Generate the initial `DATA_PLACEMENT_EXAMPLES.md` |
| User command `!populate` | Regenerate with the latest YAML state |
| Change to `kb.config.yml` (new entities) | Optional regeneration on the next session |

---

## Agent checklist

For module 14 during deployment:

- [ ] Determined whether built-in role applies (Path A) or custom role is needed (Path B)
- [ ] (Path B only) Created `examples/<slug>.yml` from `templates/role.yml.template`, validated YAML parses
- [ ] `kb.config.yml` has the confirmed entities (`--entities-from <role>`, then trimmed by hand)
- [ ] Ran `python3 knowledge-base/scripts/kb_populate.py --role <role> --kb-root knowledge-base`
- [ ] Verified `DATA_PLACEMENT_EXAMPLES.md` was written
- [ ] (Recommended) Read the generated file and appended a `## Project notes` section below the `<!-- kb_populate: … -->` line
- [ ] (Optional) Re-ran with `--create-samples` if the user wants format examples
- [ ] Continued with module 15. `START_HERE.md`, `eval/QUESTIONS.md`, the doctor run, `finalize.sh` and the summary for the user come after module 18 (`02_INIT.md`, "Finish the deployment")

`kb_populate.py` records every write in `log.md` as
`populate | DATA_PLACEMENT_EXAMPLES generated` (role, source YAML, whether notes
were kept) when `--kb-root` holds a `kb.config.yml`; a folder without one gets
the file but no log entry.

---

## Integration

- **02_INIT:** this module runs in Phase 3 (modules 03–18), after `kb.config.yml` and `STRUCTURE_VARIANTS.md` exist
- **03_PIPELINE:** `raw/_samples/` is not picked up by the pipeline (name starts with `_`)
- **05_INDEX:** `raw/_samples/` is excluded by the ignore pattern `raw/**`
- **10_LOG:** generation is recorded in `log.md` as `populate | DATA_PLACEMENT_EXAMPLES generated`

---

## Future improvements (Phase 4+)

- [x] `scripts/kb_populate.py` — automated yaml → markdown generation
- [x] `--create-samples` — placeholder format files
- [x] `templates/role.yml.template` — for custom roles
- [x] `--entities-from` — copy a role's entities into `kb.config.yml`
- [ ] Versioning of generated file (`generated_at`, `from_template_version`)
- [ ] Auto regeneration when entities change in `kb.config.yml`
- [ ] Translate sections into the base's primary language (use `language` from config)
- [ ] A/B test wording of quickstart based on user feedback
