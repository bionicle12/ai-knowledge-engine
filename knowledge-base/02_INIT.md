# 02 — Knowledge base initialization

> This module covers the clarification phase (questions for the user), the project structure creation, and — after modules 03–18 — the finish: doctor, `finalize.sh`, git hook.
>
> **Working directory:** the project root (the folder that holds `setup/` and `.venv/`), with the venv from `01_PREREQUISITES.md` active. Until Phase 1 copies the engine, run kit scripts as `python3 setup/scripts/…`; afterwards as `python3 knowledge-base/scripts/…` with `--root knowledge-base` / `--kb-root knowledge-base` (or `cd knowledge-base` and drop the flag).
> **Reference templates:** `setup/templates/kb.config.yml.template`, `KNOWLEDGE_STRUCTURE.md.template`, `DATA_PLACEMENT_EXAMPLES.md.template`, `START_HERE.md.template`, `.gitignore.template`, `.gitattributes.template`. The agent copies them into the deployed base root and parameterizes the placeholders.
> **Language:** write owner-facing text (START_HERE.md, KNOWLEDGE_STRUCTURE.md descriptions, project notes, eval questions) in the owner's language (`knowledge_base.language`). File and folder names, frontmatter keys, config keys and `!commands` stay in English.
> **Deployment helper:** `setup/shell/finalize.sh` runs **at the very end** (after `kb_doctor` exits 0) to flatten `knowledge-base/` into the project root — see "Finish the deployment".

---

## Deployment flow (where things end up)

The user copies the upstream `knowledge-base/` folder (modules `00_OVERVIEW.md` … `18_HEAL.md`, `README.md`, `scripts/`, `shell/`, `templates/`, `examples/`) into their project root, **renamed to `setup/`** so it stays separate from the base the agent builds. The agent reads `setup/00_OVERVIEW.md` first, then walks through the modules and **builds the base inside `<project-root>/knowledge-base/`**, with the venv from `01` at the project root. At the end `finalize.sh` promotes everything to the project root, fills `kb-docs/`, promotes the double-click launchers, and removes `setup/` and the empty `knowledge-base/` ("Finish the deployment" below). `00_OVERVIEW.md` draws both layouts (before and after finalize).

If the user wants the base to stay in a subfolder, skip finalize: `knowledge-base/` already holds `kb-docs/` and everything else. Then create the venv inside it (`01_PREREQUISITES.md`, "Base kept in a subfolder"). The default and recommended path is **flat at the project root after finalization**.

---

## Phase 0: clarify intent

Before creating the base, the AI agent **must** ask questions. Where the answers are obvious, propose sensible defaults.

### When the user did NOT specify a role

When the user says "deploy a base" without naming a role, the agent:

1. Lists **every** `setup/examples/*.yml` — its `role:` and the gist of `description:` — as a numbered menu, and adds "Custom role — describe it, and I'll prepare a configuration" as the last item:
   ```
   Available role templates:
    1. 📊 Marketing Director — strategy, brand, audience, campaigns
    2. 💻 Senior Software Engineer — architecture, code, debugging, technologies
    3. 🎯 Product Manager — prioritization, metrics, user research
   …
   17. Custom role — describe it, and I'll prepare a configuration
   ```
   Do not present a role as "not in the templates" when a file for it exists.
2. The user picks a number or describes their own role

### When the user specified a role

The AI agent finds a matching template in `setup/examples/` and moves on to **customization** (see below). No match → custom role.

### Customization after picking a role

After selecting a template the agent **does not just copy yml**, it asks clarifying questions:

1. **Look at the entities in the template — does it all fit, or is something extra/missing?**
   - Show the entity list with descriptions
   - The user can drop unneeded ones or add custom

2. **What specific tools/technologies/approaches do you use?**
   - For a programmer: "What stack? Rust, TypeScript, Python?"
   - For a musician: "Which DAW/tools? Suno, stems via Demucs?"
   - For a marketer: "What channels and analytics tools?"

3. **Anything unique about your approach?**
   - "I don't read sheet music but I make music with AI"
   - "I work alone, no team"
   - "I have a side game project"

4. **Want to add anything or keep as is?**
   - "As is" → still run the blind-spot pass and the four structure sketches;
     do not skip to folder creation
   - Anything to add → AI integrates it into the config, then continues

### Blind-spot pass (before any structure)

**Do not propose `knowledge/` folders yet.** People with this role usually
forget things that later force a layout rewrite. Interview first.

1. Run `python3 setup/scripts/kb_structure.py --role <slug> --blind-spots`.
   If the YAML has `blind_spots:`, use that list; otherwise the script derives
   defaults from entities and artefacts. **Custom role:** first author
   `knowledge-base/examples/<slug>.yml` from `setup/templates/role.yml.template`
   with the user (fill `blind_spots:` too), then pass
   `--from knowledge-base/examples/<slug>.yml` instead of `--role <slug>` here
   and in the next step.
2. Ask **in the printed order**. The first items are the ones that change
   the `knowledge/` layout (where abandoned work lives, whether artefacts
   earn folders, how old material is found, what stays immutable). Content
   gaps come after.
3. Record answers in the working notes. They feed the four sketches.

Do not invent a fifth questionnaire about folders. The next step is
sketches, not more form fields.

### Four structure variants (react, do not pick a number)

1. Run
   `python3 setup/scripts/kb_structure.py --role <slug> --write --kb-root knowledge-base`
   (it creates `knowledge-base/` if it does not exist yet).
2. That writes `knowledge-base/interactions/init/STRUCTURE_VARIANTS.md` — four
   sketches from the same role YAML: **by project / by artefact type / by
   time / by decision**. Show them in chat. The owner **reacts** (likes,
   dislikes, "this plus dated decisions", "hybrid"). They do not pick
   1–4 from a form.
3. There are four sketches, not ten. Material is the role YAMLs in
   `examples/` plus the blind-spot answers.
4. **Hybrid default:** if the reaction is "a bit of everything" or "as
   is", use the stock 12-folder tree in `KNOWLEDGE_STRUCTURE.md.template`.
   `kb_ingest.py --init-dirs` still creates those stock dirs as empty
   compatibility shelves; add extra folders the reaction needs.

### Mandatory questions (after the structure reaction)

1. **What raw data will be loaded?**
   - Documents, presentations, chats, code, audio, video, notes, articles

2. **What is forbidden to index?**
   - Secrets, tokens, third-party private data, medical/legal data

3. **Is personal context needed?**
   - Thinking style, creative interests, professional history, preferences

4. **Is there Git?**
   - If yes — after finalize, install the post-commit hook with
     `bash shell/install-hooks.sh` ("Finish the deployment", step 5)

5. **Which agent is primary?** Set `index.primary_agent` and `index.window_profile`
   in `kb.config.yml` from the answer:
   - **Codex** → `primary_agent: codex`, `window_profile: 400k`
   - **Cursor** → `primary_agent: cursor`, `window_profile: 256k`
   - **Claude Code** → `primary_agent: claude-code`; `window_profile: 1m` if
     they use a 1M-window model, otherwise `256k`. `finalize.sh` then writes
     the one-line `CLAUDE.md` (`@AGENTS.md`) without asking — Claude Code
     does not read `AGENTS.md` on its own.

6. **What three questions will you ask this base most often?** Write
   `eval/QUESTIONS.md` from `templates/eval/QUESTIONS.md.template`. For each
   question record: the question text, terms it must mention, and a rejected
   alternative it must NOT propose. The page it must cite usually does not
   exist yet: write the planned path (e.g. `knowledge/decisions/…`) or `TBD`,
   and fill it in once initial population has written that page. Create empty
   `eval/results/`. These are the before/after probes for later instruction
   edits — not indexed.

---

## Phase 1: copy the engine, create the structure

After the blind-spot pass and the owner's reaction to the four sketches,
copy the engine into the base — once, verbatim — and create the folders.

### Copy the engine files

```bash
mkdir -p knowledge-base/kb-docs
cp -R setup/scripts setup/shell setup/templates setup/examples knowledge-base/
rm -rf knowledge-base/scripts/tests                  # engine tests, not part of a base
find knowledge-base -name __pycache__ -type d -prune -exec rm -rf {} +
cp setup/[0-9][0-9]_*.md setup/README.md knowledge-base/kb-docs/
cp setup/templates/requirements*.txt knowledge-base/
cp setup/templates/.gitignore.template knowledge-base/.gitignore
cp setup/templates/.gitattributes.template knowledge-base/.gitattributes
```

(PowerShell: the same with `Copy-Item -Recurse` / `Remove-Item -Recurse`.)

- `kb-docs/` holds the instruction modules the deployed `AGENTS.md` and the
  script messages point to (`kb-docs/NN_NAME.md`); `setup/` disappears at the end.
- `.gitignore` keeps private material out of git by default: `raw/`, `assets/`,
  `processed/`, `review/`, `interactions/` (plus machine-local state). To version
  one of them, delete its line — and never push such a repository anywhere public.
- `.gitattributes` pins line endings (LF for shell scripts and the hook, CRLF
  for `.bat`), so a Windows checkout does not break the wrappers.
- Create both files in `knowledge-base/` even when the project root already has
  its own: the patterns (`/raw/`, `shell/hooks/*`) are relative to the folder
  that holds the file, so root copies would not cover `knowledge-base/raw/`.
  `finalize.sh` then adds the rules the root files lack at their top, so the
  project's own rules keep precedence (nothing is removed; a catch-all
  `* text=auto` is left out of an existing `.gitattributes`).

### Create the folders

```bash
python3 knowledge-base/scripts/kb_ingest.py --init-dirs --root knowledge-base
```

The tree below is the **hybrid default**. If the reaction chose one axis
(projects / artefacts / time / decisions), follow that sketch and keep unused
stock dirs only as empty shelves.

```text
knowledge-base/
├── AGENTS.md                   # AI agent instructions (from template 06)
├── KNOWLEDGE_STRUCTURE.md      # Description of every folder and rules
├── DATA_PLACEMENT_EXAMPLES.md  # "Got a PDF → drop it here"
├── START_HERE.md               # The owner's entry point (written at the finish)
├── kb.config.yml               # Role, entities, rules
├── repomix.config.json         # Indexer config
├── requirements*.txt           # Python dependencies (see 01)
├── .gitignore, .gitattributes
├── kb-docs/                    # Instruction modules 00 … 18 + README.md
├── shell/                      # Linux / CLI wrappers, git hook, launchers
│   ├── reindex.sh, watcher.sh, lint.sh, doctor.sh, export.sh, import.sh
│   ├── install-hooks.sh, hooks/post-commit, _kbpy.sh
│   ├── reindex.command, watcher-start.command, watcher-stop.command, export.command, import.command
│   └── reindex.bat, watcher-start.bat, export.bat, import.bat   # promoted to the root by finalize.sh
│
├── scripts/                    # Python pipeline (kb_ingest.py, kb_lint.py, …)
│
├── raw/                        # Raw data (NOT indexed); unknown → raw/unsorted/
│   └── documents/, work/, chats/, media/, personal-context/, reference/   # each with unsorted/
├── processed/                  # Converted artifacts (NOT indexed)
│   └── markdown/, transcripts/, ocr/, tables/, extracted-metadata/, nlp-meta/
│
├── knowledge/                  # ✅ Clean knowledge → INDEXED
│   ├── profile/                # Profile, expertise, strengths
│   ├── principles/             # Working principles, quality bars
│   ├── domain/                 # Domain area, market, knowledge (≈ world network)
│   ├── projects/               # Projects, cases, results
│   ├── decisions/              # Decisions: what, why, outcome
│   ├── voice/                  # Speaking, writing, explaining style
│   ├── timelines/              # Chronology, growth stages
│   ├── playbooks/              # Repeatable workflows (≈ experience network)
│   ├── insights/               # Synthesized higher-level conclusions
│   ├── opinions/               # Subjective takes with confidence and date
│   ├── routing/                # Routing tables for scaled navigation
│   ├── open-questions/         # Questions the base does not answer
│   └── _archive/               # Outdated pages, kept with a note (never stale)
│
├── assets/                     # Binary originals (NOT indexed)
│   └── documents/, presentations/, media/, images/, archives/
├── assets-index/               # ✅ MD descriptions of assets → INDEXED
│   └── documents.md, presentations.md, media.md, images.md, archives.md
│
├── review/                     # Review queues (NOT indexed)
│   ├── needs-classification/
│   ├── needs-ai-decision/
│   ├── needs-redaction/
│   ├── needs-merge/            # Cross-base merge packages (see 16_MERGE.md)
│   ├── needs-heal/             # Catch-up after upgrade (see 18_HEAL.md)
│   └── excluded-sensitive/
│
├── interactions/               # Feedback loop (NOT indexed directly)
│   ├── sessions/               # Dialog folders with timestamps
│   ├── insights/               # Extracted patterns
│   ├── meta-reviews/           # Periodic analysis
│   ├── init/                   # STRUCTURE_VARIANTS.md (E2) — not indexed
│   └── quiz/                   # !quiz answer sheets — not indexed
│
├── eval/                       # Manual instruction probes (NOT indexed)
│   ├── QUESTIONS.md            # Three typical questions (02_INIT Q6)
│   └── results/                # Before/after answer dumps — keep, do not gitignore
│
├── sync/                       # Cross-base import/export (NOT indexed; 16_MERGE.md)
│   └── inbox/, outbox/, applied/, backups/, reports/
│
└── .repomix/                   # Index packs, written by kb_reindex.py (see 05_INDEX.md)
```

The base has no `README.md` of its own: `START_HERE.md` is the owner's entry
point, and a project README at the root stays the project's.

---

## Phase 2: `kb.config.yml`

Copy `setup/templates/kb.config.yml.template` to `knowledge-base/kb.config.yml`
and edit **values only** — its header and section comments name the `kb-docs/`
module that documents each key, and scripts edit the file line by line later.
Placeholders:

- `{{KB_INSTRUCTIONS_VERSION}}` — the output of `python3 setup/scripts/kb_common.py --version`
  (the kit has no `VERSION` file)
- `{{DEPLOYED_AT}}` — today, ISO date
- `{{KB_NAME}}`, `{{PRIMARY_LANGUAGE}}`, `{{PRIMARY_ROLE}}` — from the interview;
  `{{PRIMARY_ROLE}}` is the `role:` title (or the file name) of the chosen
  `examples/<slug>.yml`: `!populate` finds the YAML by it
- `{{SPACY_MODEL}}` — the spaCy model for `knowledge_base.language`, e.g.
  `ru_core_news_md` or `en_core_web_md` — the one installed in `01_PREREQUISITES.md`
  (see `12_NLP_PREPROCESS.md`)
- `{{KB_LABEL}}` — see below
- `entities: {}` — run
  `python3 knowledge-base/scripts/kb_populate.py --entities-from <slug> --kb-root knowledge-base`
  (copies the role's `entities:` mapping into the config while it has none;
  `--dry-run` previews it; a custom role in `knowledge-base/examples/` is found
  too), then delete the entities the owner did not confirm and add the ones
  they asked for

### Example values for a hybrid role (programmer + hobby)

Only the edited keys are shown; the real file keeps every section and comment of the template.

```yaml
knowledge_base:
  name: "personal-professional-kb"
  mode: "default"            # default | super — the only place the mode lives
  language: "en"
  index_policy: "clean-knowledge-only"

  roles:
    primary: "Senior Software Engineer"
    hobbies:
      - "AI-assisted music production"
      - "Indie game development"

privacy:
  raw_indexing_allowed: false
  review_indexing_allowed: false
  interactions_indexing_allowed: false
  external_ai_allowed: false
  require_redaction_for_chats: true

language_policy:
  primary: "en"
  extraction_rule: "extract in primary language; preserve original terms / brand names verbatim"
  metadata_language: "en"  # for slugs, filenames, frontmatter keys

entities:
  # copied from examples/<slug>.yml, trimmed to what the owner confirmed

sync:
  # Only matters if the user runs this base on more than one machine.
  label: "work-laptop"          # {{KB_LABEL}} — how this base identifies itself
  export:
    sections: ["knowledge", "assets-index", "interactions", "meta", "config", "log"]
    with_assets: false
  import:
    strategy: "safe"
    similarity_threshold: 0.85
    backup: true
    move_applied: true
```

> **`{{KB_LABEL}}`** — ask only when the user says they work from several machines
> (e.g. a studio laptop and a work laptop). It must be **different in each
> deployment**: it is stamped onto every imported page as `merged_from:` and is
> what makes a merge traceable. When there is only one machine, set it to the
> same value as `knowledge_base.name`. See `16_MERGE.md`.

---

## Exclusion rules

Do NOT add to `knowledge/` and do NOT index:

- passwords, tokens, API keys, seed phrases, private keys
- banking details, passport data, third-party documents
- third-party private chats without permission to process
- medical data of others
- personal conflicts, gossip, intimate context
- unredacted raw chat exports

If the material is useful but sensitive → `review/needs-redaction/`.
If it can't be safely used → `review/excluded-sensitive/`.

`kb_ingest.py` does the first sort itself: while `privacy.require_redaction_for_chats`
is true (the default), files from the `privacy.redact_categories` folders
(default `raw/chats/`, `raw/personal-context/`) go to `review/needs-redaction/`,
and with `privacy.secret_scan` (default on) so do files that look like they hold
tokens, passwords or private keys (see `03_PIPELINE.md`).

---

## Frontmatter metadata

Every file in `knowledge/` must start with a YAML block between `---`:

```markdown
---
source: "assets/documents/2026-05-06__q2-strategy.pdf"
extracted_at: 2026-05-06
last_verified: 2026-05-06
confidence: high
importance: 6                # 1-10, set by the agent at extraction (11_PROVENANCE.md)
lifecycle: evolving          # permanent | evolving | temporal
tags: [strategy, growth, q2-2026]
supersedes: null
---

# Q2 growth strategy

...content...
```

`source`, `extracted_at`, `tags` and `lifecycle` are required (`kb_lint.py`
reports a page without them). This lets the AI agent:
- see **where** the knowledge came from and verify the source
- judge **freshness** (when extracted, when last verified, whether it ages at all)
- filter by tags
- understand the supersession chain (`supersedes`)

---

## Phase 3: modules 03–18

Continue with `03_PIPELINE.md` … `18_HEAL.md` **in order** and configure what
each one needs. Do not jump to the finish before module 18.

Read in full the modules that set the base up now: 03, 05, 06, 09, 10, 11, 12,
13, 14. The other modules describe work that runs later from `kb-docs/`, and
their defaults need no deployment step. Read only their opening summary, and
read the whole module when the owner wants that work now or its command runs:

- 04 — `!review`
- 07 — commands, modes, `!save` (`AGENTS.md` already carries the command table)
- 08 — using the base from other projects
- 15 — audio, video, scans, archives (read it in full when the owner named such files in Phase 0)
- 16 — several machines (`{{KB_LABEL}}` is set in Phase 2)
- 17 — `!refactor`
- 18 — `!heal`

Module 14 (initial population) needs, in this order:

1. The role YAML on disk. A custom role's `knowledge-base/examples/<slug>.yml`
   comes from Phase 0 (author it now if it is still missing); the base's scripts
   find it with `--role <slug>`.
2. `interactions/init/STRUCTURE_VARIANTS.md` — if missing, run
   `python3 knowledge-base/scripts/kb_structure.py --role <slug> --write --kb-root knowledge-base`
   (deterministic; no LLM).
3. `python3 knowledge-base/scripts/kb_populate.py --role <slug> --kb-root knowledge-base`
   — deterministic generation of `DATA_PLACEMENT_EXAMPLES.md`, no LLM tokens.
   If the role YAML has no `placement_examples:` section, `kb_populate.py` exits
   with an error; add the section to the YAML and re-run.
4. (Recommended) Read the generated file and append a `## Project notes` section
   with project-specific tips that don't fit in YAML (~1-2K tokens).

---

## Finish the deployment (after module 18)

1. **Generate `START_HERE.md`** by copying `templates/START_HERE.md.template` and
   parameterizing `{{KB_NAME}}` and `{{PRIMARY_ROLE}}`. This is the **first thing**
   the user reads after deployment.
2. **Generate `eval/QUESTIONS.md`** from `templates/eval/QUESTIONS.md.template`
   using the three typical questions from mandatory Q6. Leave `eval/results/` empty.
3. **Run the doctor:** `python3 knowledge-base/scripts/kb_doctor.py --root knowledge-base`.
   It **passes when it exits 0** — warnings are allowed (read them and fix what
   is cheap); errors are not. Fix and re-run until it exits 0.
4. **Run `bash setup/shell/finalize.sh`** (on Windows: from Git Bash) — the kit's
   copy; the base's own `shell/finalize.sh` refuses to run, because finalize
   deletes the folder that holds it. It:
   1. Validates the deployed base (`AGENTS.md`, `kb.config.yml`, `scripts/kb_ingest.py`)
      and refuses (exit 1, nothing changed) when an entry of `knowledge-base/` already
      exists at the project root — unless `--force`, which first moves those
      project-root entries to `.kb-finalize-backup/<timestamp>/` (nothing is deleted)
   2. **Promotes** every entry from `knowledge-base/` up to the project root, except
      `.git` and virtualenvs: they are never moved or deleted (a `knowledge-base/.venv`
      stays with a warning — the venv belongs at the project root, see 01). A
      `.gitignore` / `.gitattributes` the project root already has is not a
      conflict: the base's rules it lacks are added at its top (the project's
      own rules keep precedence)
   3. Copies the instruction modules from `setup/` into `kb-docs/` (existing files kept)
   4. Removes the empty `knowledge-base/` folder, promotes the `*.command` / `*.bat`
      launchers from `shell/` to the project root, refreshes executable bits
   5. Writes the one-line `CLAUDE.md` (`@AGENTS.md`) when `index.primary_agent` is
      `claude-code` or with `--claude-md`; otherwise it asks (no answer = no;
      `--no-claude-md` skips the question)
   6. Removes `setup/` last (`--keep-setup` keeps it)

   Exit codes: `0` done · `1` refused before anything changed · `2` stopped
   part-way. On `2` the run is recorded in `.kb-finalize.journal`: fix the reported
   problem (permissions, disk space…) and run `bash setup/shell/finalize.sh --resume`,
   which continues with the options of the first run (it refuses a damaged journal:
   then check what was already moved, delete the journal and finish by hand or
   re-run). `--dry-run` prints the plan.
   If `finalize.sh` refuses, DO NOT add `--force` unless the user agrees — diagnose
   first.
5. **Git (mandatory Q4 = yes):** from the (now flat) project root run
   `bash shell/install-hooks.sh`. It installs `shell/hooks/post-commit`, which
   refreshes the index packs and `STATUS.md` in the background after each commit
   (details: `kb-docs/13_AUTORUN.md`). A different hook that was already there
   (the owner's, or an edited copy of ours) is moved to
   `post-commit.backup-<timestamp>`. To keep the owner's own commands, restore
   their hook and call `shell/hooks/post-commit` from it instead.
6. Show the user a 3-5 line summary in chat that:
   - **Explicitly tells them**: *"Read `START_HERE.md` first, and start every new chat
     with: 'Use AGENTS.md as the main instruction'"* — in the owner's language
     (Claude Code users with `CLAUDE.md` can skip the phrase)
   - Lists the most actionable quickstart items
   - Mentions the watcher launcher relevant to their OS
