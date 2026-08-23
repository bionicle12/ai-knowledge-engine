# 02 — Knowledge base initialization

> This module covers the clarification phase (questions for the user) and the project structure creation.
>
> **Reference templates:** `knowledge-base/templates/kb.config.yml.template`, `KNOWLEDGE_STRUCTURE.md.template`, `DATA_PLACEMENT_EXAMPLES.md.template`, `START_HERE.md.template`, `.gitignore.template`. The agent copies them into the deployed base root and parameterizes the placeholders.
> **Auto-init folders:** the structure can be created with one command — `python3 scripts/kb_ingest.py --init-dirs`.
> **Deployment helper:** `shell/finalize.sh` runs **at the very end** (after `kb_doctor` passes) to flatten `knowledge-base/` into the project root and remove `setup/` — see "Deployment flow" below.

---

## Deployment flow (where things end up)

The user copies the upstream `knowledge-base/` folder into their project root, **renamed to `setup/`** so it stays separate from the base the agent will build. Initial layout:

```
my-project/
└── setup/
    ├── 00_OVERVIEW.md … 14_INITIAL_POPULATION.md
    ├── README.md
    ├── scripts/
    ├── shell/
    ├── templates/
    └── examples/
```

The agent reads `setup/00_OVERVIEW.md` first, then walks through the modules. The base is **built inside `<project-root>/knowledge-base/`** during deployment:

```
my-project/
├── setup/                       ← still here, source instructions
└── knowledge-base/              ← agent builds the base in here
    ├── AGENTS.md, kb.config.yml, ...
    ├── scripts/, shell/, templates/, examples/    ← copied verbatim from setup/
    ├── raw/, processed/, knowledge/, assets/, ...
    ├── watcher-start.command, watcher-stop.command
    ├── reindex.bat, watcher-start.bat
    └── DATA_PLACEMENT_EXAMPLES.md, START_HERE.md
```

When everything is verified (kb_doctor passes, START_HERE.md is generated), the agent runs **finalize**:

```bash
bash setup/shell/finalize.sh
```

This script:
1. Validates the deployed base has the required files (`AGENTS.md`, `kb.config.yml`, `scripts/kb_ingest.py`)
2. **Promotes** every entry from `knowledge-base/` up to the project root
3. Removes the empty `knowledge-base/` folder
4. Removes the original `setup/` folder (use `--keep-setup` to keep it)
5. Refreshes executable bits on `*.sh` / `*.command` files
6. Asks whether the user works in Claude Code; on yes, writes a one-line
   `CLAUDE.md` containing `@AGENTS.md` (Claude Code does not read `AGENTS.md`)

**Final layout — flat at the project root, no `setup/`, no `knowledge-base/`:**

```
my-project/
├── kb.config.yml
├── AGENTS.md
├── KNOWLEDGE_STRUCTURE.md
├── DATA_PLACEMENT_EXAMPLES.md
├── START_HERE.md
├── repomix.config.json
├── requirements.txt
├── reindex.command, watcher-start.command, watcher-stop.command   (macOS — double-click)
├── export.command, import.command                                  (macOS — cross-base sync)
├── reindex.bat, watcher-start.bat, export.bat, import.bat          (Windows — double-click)
├── shell/        ← Linux/CLI: watcher.sh, reindex.sh, lint.sh, doctor.sh, export.sh, import.sh
├── scripts/      ← Python pipeline
├── templates/, examples/
├── raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/, eval/, sync/
├── .repomix/
└── .venv/
```

`finalize.sh` automatically promotes the `*.command` / `*.bat` launchers from `shell/` to the project root (so they're discoverable in Finder/Explorer for double-clicking). The `*.sh` wrappers stay only in `shell/` — invoking them is a Linux/CLI thing.

If finalize fails (conflicts, missing files), the project stays in the pre-finalize state — nothing is partially flattened, the user can retry.

If for some reason the user wants the base in a subfolder, they can simply skip finalize. But the default and recommended path is **flat at the project root after finalization**.

---

## Phase 0: clarify intent

Before creating the base, the AI agent **must** ask questions. Where the answers are obvious, propose sensible defaults.

### When the user did NOT specify a role

When the user says "deploy a base" without naming a role, the agent:

1. Scans `examples/*.yml` and shows the available templates:
   ```
   Available role templates:
   1. 📊 Marketing Director — strategy, brand, audience, campaigns
   2. 💻 Senior Software Engineer — architecture, code, debugging, technologies
   3. 🎨 Creative Hybrid — programmer + music + gamedev
   ```
2. Additionally suggests **creative options** not in the templates:
   ```
   Or I can suggest:
   4. 🎯 Product Manager — prioritization, metrics, user research
   5. ✍️ Content creator — copywriting, social media, personal brand, monetization
   6. 🔬 Researcher / Analyst — data, hypotheses, publications
   7. 🏢 Startup Founder — product, team, investors, market
   8. 🎬 Porn director in the Balabanov style — screenwriting for gritty auteur films
   9. Custom role — describe it, and I'll prepare a configuration
   ```
3. The user picks a number or describes their own role

### When the user specified a role

The AI agent finds a matching template in `examples/` and moves on to **customization** (see below).

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

1. Run `python3 scripts/kb_structure.py --role <slug> --blind-spots`
   (or `--from examples/<slug>.yml`). If the YAML has `blind_spots:`, use
   that list; otherwise the script derives defaults from entities and
   artefacts. Custom roles: fill `blind_spots:` in
   `templates/role.yml.template` while authoring the YAML.
2. Ask **in the printed order**. The first items are the ones that change
   the `knowledge/` layout (where abandoned work lives, whether artefacts
   earn folders, how old material is found, what stays immutable). Content
   gaps come after.
3. Record answers in the working notes. They feed the four sketches.

Do not invent a fifth questionnaire about folders. The next step is
sketches, not more form fields.

### Four structure variants (react, do not pick a number)

1. Run
   `python3 scripts/kb_structure.py --role <slug> --write --kb-root knowledge-base`
   (cwd already inside the deployed base → `--kb-root .`).
2. That writes `interactions/init/STRUCTURE_VARIANTS.md` — four sketches
   from the same role YAML: **by project / by artefact type / by time /
   by decision**. Show them in chat. The owner **reacts** (likes,
   dislikes, "this plus dated decisions", "hybrid"). They do not pick
   1–4 from a form.
3. There are four sketches, not ten. Material is the 16 role YAMLs in
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
   - If yes — set up auto-update via post-commit hook

5. **Which agent is primary?** Set `index.primary_agent` and `index.window_profile`
   in `kb.config.yml` from the answer:
   - **Codex** → `primary_agent: codex`, `window_profile: 400k`
   - **Cursor** → `primary_agent: cursor`, `window_profile: 256k`
   - **Claude Code** → `primary_agent: claude-code`; `window_profile: 1m` if
     they use a 1M-window model, otherwise `256k`

6. **What three questions will you ask this base most often?** Write
   `eval/QUESTIONS.md` from `templates/eval/QUESTIONS.md.template`. For each
   question record: the question text, a page it must cite, terms it must
   mention, and a rejected alternative it must NOT propose. Create empty
   `eval/results/`. These are the before/after probes for later instruction
   edits — not indexed.

---

## Phase 1: create structure

After the blind-spot pass and the owner's reaction to the four sketches,
create folders. The tree below is the **hybrid default**. If the reaction
chose one axis (projects / artefacts / time / decisions), follow that
sketch and keep unused stock dirs only as empty shelves.

The AI agent creates in the project root:

```text
knowledge-base/
├── README.md                   # What this base is, how to use it
├── AGENTS.md                   # AI agent instructions (from template 06)
├── KNOWLEDGE_STRUCTURE.md      # Description of every folder and rules
├── DATA_PLACEMENT_EXAMPLES.md  # "Got a PDF → drop it here"
├── kb.config.yml               # Role, entities, rules
├── repomix.config.json         # Indexer config
├── requirements.txt            # Python dependencies
├── reindex.command, watcher-start.command, watcher-stop.command   # macOS launchers
├── export.command, import.command                                 # macOS: cross-base sync
├── reindex.bat, watcher-start.bat, export.bat, import.bat         # Windows launchers
├── shell/                      # Linux / CLI wrappers
│   ├── reindex.sh
│   ├── watcher.sh
│   ├── lint.sh
│   ├── doctor.sh
│   ├── export.sh
│   └── import.sh
│
├── scripts/
│   └── kb_ingest.py            # Pipeline (see 03_PIPELINE.md)
│
├── raw/                        # Raw data (NOT indexed)
│   ├── unsorted/               # Don't know where → here
│   ├── work/unsorted/          # Working documents
│   ├── chats/unsorted/         # Chat / conversation exports
│   ├── media/unsorted/         # Video, audio, recordings
│   ├── personal-context/unsorted/  # Personal context
│   └── reference/unsorted/     # Reference materials, articles
│
├── processed/                  # Converted artifacts (NOT indexed)
│   ├── markdown/
│   ├── transcripts/
│   ├── ocr/
│   ├── tables/
│   └── extracted-metadata/
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
│   └── open-questions/         # Questions the base does not answer
│
├── assets/                     # Binary originals (NOT indexed)
│   ├── documents/
│   ├── presentations/
│   ├── media/
│   ├── images/
│   └── archives/
│
├── assets-index/               # ✅ MD descriptions of assets → INDEXED
│   ├── documents.md
│   ├── presentations.md
│   ├── media.md
│   ├── images.md
│   └── archives.md
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
├── sync/                       # Cross-base import/export (NOT indexed)
│   ├── inbox/                  # Drop bundles from the other machine here
│   ├── outbox/                 # Bundles this base produced
│   ├── applied/                # Bundles already imported
│   ├── backups/                # Pre-import snapshots
│   └── reports/                # Merge reports
│
├── setup/                      # Seed instructions (NOT indexed)
└── .repomix/
    └── output.xml
```

---

## Phase 2: `kb.config.yml`

The agent creates the config based on user answers.

### Example for a hybrid role (programmer + hobby)

```yaml
knowledge_base:
  name: "personal-professional-kb"
  mode: "local-first"
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
  # Described by the user via examples/ or manually
  # see examples/*.yml

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

---

## Frontmatter metadata

Every file in `knowledge/` must start with a YAML block between `---`:

```markdown
---
source: "assets/documents/2026-05-06__q2-strategy.pdf"
extracted_at: 2026-05-06
last_verified: 2026-05-06
confidence: high
tags: [strategy, growth, q2-2026]
supersedes: null
---

# Q2 growth strategy

...content...
```

This lets the AI agent:
- see **where** the knowledge came from and verify the source
- judge **freshness** (when extracted, when last verified)
- filter by tags
- understand the supersession chain (`supersedes`)

---

## Phase 3: Initial Population

After creating the structure and config the agent **must** proceed to `14_INITIAL_POPULATION.md`:

1. Read the chosen role template (`examples/<role>.yml`) and find the `placement_examples:` section.
2. **If the role is custom (not in `examples/`)**: create `examples/<slug>.yml` from `templates/role.yml.template` first by walking the user through the placeholders. The YAML must exist on disk **before** populating.
3. If `interactions/init/STRUCTURE_VARIANTS.md` is missing, run
   `python3 scripts/kb_structure.py --role <slug> --write --kb-root knowledge-base`
   first (deterministic; no LLM). Then run
   `python3 scripts/kb_populate.py --role <slug> --kb-root knowledge-base`
   (where `knowledge-base/` is the deployed base directory the agent built)
   — deterministic generation, no LLM tokens.
4. (Recommended) Read the generated file and append a `## Project notes` section with project-specific tips that don't fit in YAML (~1-2K tokens).
5. **Generate `START_HERE.md`** by copying `templates/START_HERE.md.template` and parameterizing `{{KB_NAME}}` and `{{PRIMARY_ROLE}}`. This is the **first thing** the user reads after deployment.
6. **Generate `eval/QUESTIONS.md`** from `templates/eval/QUESTIONS.md.template` using the three typical questions from mandatory Q6. Leave `eval/results/` empty.
7. **Run `kb_doctor.py`** to confirm everything is wired correctly.
8. **Run `bash setup/shell/finalize.sh`** — promotes `knowledge-base/` contents to the project root, removes `setup/` and the empty `knowledge-base/` folder. After this the user's project is flat and tidy.
9. Show the user a 3-5 line summary in chat that:
   - **Explicitly tells them**: *"Read `START_HERE.md` first, and start every new chat with: 'Используй AGENTS.md как основную инструкцию'."*
   - Lists the most actionable quickstart items
   - Mentions the watcher launcher relevant to their OS

If the role template has no `placement_examples:` section — `kb_populate.py` exits with an error; add the section to the YAML and re-run.

If `finalize.sh` refuses (file conflicts, missing required files), DO NOT force unless the user agrees — diagnose first.
