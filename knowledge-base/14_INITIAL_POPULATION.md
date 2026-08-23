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

---

## Path A: built-in role

1. User picks (or agent suggests) a role from `examples/`:
   `programmer-senior`, `marketing-director`, `creative-hybrid`, `product-manager`, `researcher`, `founder`, `content-creator`, `fiction-writer`.
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

3. Validate the file parses:
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

## Optional step: AI review pass

After `kb_populate.py` writes the file, the agent **should** read it and look for improvements:

| Goal | Examples of additions |
|------|-----------------------|
| Project-specific notes | "Drop your highway-clicker README first since most context is there" |
| Tool stack | "Your stack is Rust + React, so add `Cargo.toml` and `package.json` to early ingest" |
| User-stated preferences | "User said they hate slack export noise — emphasize `review/needs-redaction/`" |
| Quickstart sharpening | Pick the *one* file in the user's environment that will demonstrate value fastest |

The agent appends a `## Project notes` section at the bottom of the generated file (do **not** modify the auto-generated sections — they will be overwritten on re-run; only append below the footer).

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
| User edits `examples/<role>.yml` | Re-run `kb_populate.py` — file is overwritten cleanly |
| User wants different artifact set | Edit YAML → re-run script |
| `!populate` command from user | Re-run script + AI review pass |
| New role discovered post-deploy | Create new YAML (Path B), then run script |

> ⚠️ Project notes added by the agent in `## Project notes` survive only if the agent appends below the auto-generated footer. The script overwrites everything above it.

---

## Trigger points

| When | Action |
|------|--------|
| End of `02_INIT` (deployment) | Generate the initial `DATA_PLACEMENT_EXAMPLES.md` |
| User command `!populate` | Regenerate with the latest YAML state |
| Change to `kb.config.yml` (new entities) | Optional regeneration on the next session |

---

## Agent checklist

When deployment completes:

- [ ] Determined whether built-in role applies (Path A) or custom role is needed (Path B)
- [ ] (Path B only) Created `examples/<slug>.yml` from `templates/role.yml.template`, validated YAML parses
- [ ] Ran `python3 knowledge-base/scripts/kb_populate.py --role <role> --kb-root knowledge-base`
- [ ] Verified `DATA_PLACEMENT_EXAMPLES.md` was written
- [ ] (Recommended) Read the generated file and appended a `## Project notes` section with user-specific tips
- [ ] (Optional) Re-ran with `--create-samples` if the user wants format examples
- [ ] **Generated `START_HERE.md`** from `templates/START_HERE.md.template` (parameterize `{{KB_NAME}}` and `{{PRIMARY_ROLE}}`)
- [ ] **Wrote `eval/QUESTIONS.md`** from the three typical questions (mandatory Q6 in `02_INIT.md`); `eval/results/` exists and is empty
- [ ] Ran `python3 knowledge-base/scripts/kb_doctor.py --root knowledge-base` to confirm the install
- [ ] Ran `bash setup/shell/finalize.sh` — promotes the base to the project root, removes `setup/` and the empty `knowledge-base/`
- [ ] Showed the user a 3-5 line summary in chat. **Must include**:
  - "Read `START_HERE.md` first."
  - "Every new chat session: start with *'Используй AGENTS.md как основную инструкцию'*."
  - The OS-specific watcher launcher (`watcher-start.command` for macOS, `./shell/watcher.sh` for Linux, `watcher-start.bat` for Windows)
- [ ] Logged the operation in `log.md` (auto-handled if integrated)

---

## Integration

- **02_INIT:** at the end of Phase 1 ("Create structure") the agent moves to this module
- **03_PIPELINE:** `raw/_samples/` is not picked up by the pipeline (name starts with `_`)
- **05_INDEX:** `raw/_samples/` is excluded by the ignore pattern `raw/**`
- **10_LOG:** generation is recorded in `log.md` as `populate | DATA_PLACEMENT_EXAMPLES generated`

---

## Future improvements (Phase 4+)

- [x] `scripts/kb_populate.py` — automated yaml → markdown generation
- [x] `--create-samples` — placeholder format files
- [x] `templates/role.yml.template` — for custom roles
- [ ] Versioning of generated file (`generated_at`, `from_template_version`)
- [ ] Auto regeneration when entities change in `kb.config.yml`
- [ ] Translate sections into the base's primary language (use `language` from config)
- [ ] A/B test wording of quickstart based on user feedback
