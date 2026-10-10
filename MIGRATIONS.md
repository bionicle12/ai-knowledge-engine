# Migrations

Catch-up steps for an **already deployed** knowledge base, grouped under the
engine version that added the capability. `kb_heal.py` (see
`knowledge-base/18_HEAL.md`, `kb-docs/18_HEAL.md` in a base) reads this
registry.

Format of each step: `id`, `bucket` (`auto` / `assisted` / `human`),
`detect`, `fix`. A release that needs no catch-up in a deployed base (for
example 0.15.1; there was no 0.14.0) has no section; newest section first.

How heal uses it:

- Every step has a detector in `kb_heal.py` (`DETECT_BY_ID`), and heal runs
  **every** detector on every run, whatever the base's `instructions_version`:
  a bumped version is not proof the contents were healed (older upgraders
  bumped it without healing). The version headers record when a step appeared.
- `kb_heal.py` keeps the same ids and buckets in code (`STEPS`), so heal works
  when this file is out of reach; `test_kb_heal.py` fails when the two
  disagree, when a step has no detector, or when an `auto` step has no
  deterministic fix. The texts below are what `HEAL_PLAN.md` shows.
- A step without a detector (possible only in a fork or a hand-edited copy of
  this file) is listed as a **human** item — a manual step — while the base's
  `instructions_version` is below the step's version and the version is not
  newer than the heal scripts. `kb_upgrade.py` runs heal before it bumps the
  version, so the plan it writes lists such steps.
- An `auto` step that cannot be applied in this base (for example a
  `kb.config.yml` section written in flow style) is listed as `assisted`
  with the reason.

## 0.16.0

- id: kb-docs-dir
  bucket: auto
  detect: "a root-level 17_REFACTOR.md or 18_HEAL.md (put there by kb_upgrade before 0.16) is a pristine engine copy"
  fix: "move it into kb-docs/ (drop it when kb-docs/ already has the module); a root-level copy with local edits is an assisted item: merge the edits into kb-docs/<name>, then delete the root copy. The module-pointers-kb-docs item then lists the references that still point at the old place"

- id: module-pointers-kb-docs
  bucket: assisted
  detect: "AGENTS.md, START_HERE.md or KNOWLEDGE_STRUCTURE.md names an instruction module (NN_NAME.md) outside kb-docs/ that leads nowhere: the file is absent, or it is a pristine root-level copy that kb-docs-dir moves (these lines are not managed blocks, so kb_upgrade does not rewrite them)"
  fix: "change each listed reference to kb-docs/<NN_NAME.md> — the path only, keep the rest of the line, also inside an AI-KE:INVARIANT block (the 0.16 template has the same kb-docs/ path there); show the diff. A reference to a root-level copy the owner kept on purpose is not listed"

- id: extraction-registry
  bucket: auto
  detect: "processed/extracted-metadata/*.yml written before 0.16 has no extraction: field"
  fix: "backfill with kb_ingest.backfill_extraction: extraction done + extracted_to when a knowledge/ page cites the asset in source:, else pending"

- id: status-md
  bucket: auto
  detect: ".gitignore exists and does not ignore .kb-state/ or STATUS.md (status.file)"
  fix: "append the missing lines with the template comments; kb_status.py writes STATUS.md on the next reindex"

- id: gitignore-private-dirs
  bucket: assisted
  detect: ".gitignore does not ignore one of raw/ assets/ processed/ review/ interactions/ (a !/raw/ line counts as a decision to version it), or the base is a git repository without .gitignore"
  fix: "ask the owner; on yes append the '# Private material' block from templates/.gitignore.template (/raw/ /assets/ /processed/ /review/ /interactions/); to version a folder on purpose write !/<folder>/ instead; if a folder is already tracked, suggest git rm -r --cached <folder> — the owner decides, never automatic"

- id: gitignore-kb-backups
  bucket: auto
  detect: ".gitignore exists and does not ignore .kb-backups/, .kb-finalize-backup/ or .kb-finalize.journal"
  fix: "append the missing lines under the '# Snapshots' comment from templates/.gitignore.template"

- id: media-sync-sections
  bucket: auto
  detect: "kb.config.yml has no top-level media: or sync:, or the sync/ workspace (inbox outbox applied backups reports) or review/needs-merge/ is missing"
  fix: "append the template's media: and sync: sections (sync.label = the base folder name — confirm it before the first export) and create the folders; replaces scripts/sync_deployed_bases.py"

- id: requirements-split
  bucket: auto
  detect: "requirements.txt at the base root still lists keybert"
  fix: "move the keybert line into requirements-nlp.txt (optional NLP extras; KeyBERT pulls in PyTorch)"

- id: nested-venv
  bucket: human
  detect: ".venv/.venv exists, .venv/bin/pip points at an interpreter that no longer exists (the venv was moved by finalize.sh), or knowledge-base/.venv was left behind"
  fix: "ask the owner to recreate the environment at the base root (kb-docs/01_PREREQUISITES.md): move the broken .venv aside, python3 -m venv .venv, .venv/bin/pip install -r requirements.txt; delete the leftovers once the new one works"

- id: private-index-names
  bucket: assisted
  detect: "privacy.require_redaction_for_chats is on and processed/extracted-metadata/*.yml has files without raw_category: (ingested before 0.16): their assets-index block is still titled by the file name, which may be private"
  fix: "list the asset_path and original_filename of each metadata file without raw_category: (the plan shows only the count, to keep the names out of it) and ask the owner which raw/ folder each came from; run python3 scripts/kb_ingest.py --no-nlp --set-category <folder> <asset_path> … once per folder, for every listed file (a private folder from privacy.redact_categories moves the block under the neutral title <folder> item <sha8> and opens a privacy review; any other folder is only recorded, which closes the item); then tell the owner that older log.md / log-archive/ entries still name these files and are edited by hand if the base is shared"

- id: session-redacted-flag
  bucket: auto
  detect: "a summary in interactions/sessions/ written by kb_save_session.py before 0.16 has redacted: (next to saved_at: and session_date:) and no redaction_required:"
  fix: "rename the frontmatter key redacted: to redaction_required: and keep the value: nothing was ever redacted, the flag only mirrored privacy.require_redaction_for_chats"

- id: meta-review-backlog
  bucket: assisted
  detect: "summaries in interactions/sessions/ have no meta_reviewed: key (written before 0.16), so STATUS.md counts all of them as awaiting meta-review"
  fix: "ask the owner: run !meta-review over the backlog (kb-docs/07_INTERACTION_LOOP.md), or treat the history as reviewed — then add meta_reviewed: true to the frontmatter of each session file without the key (create the frontmatter when missing) and log one meta-review entry 'backlog marked reviewed at upgrade'; never without the owner's answer"

- id: populate-notes-marker
  bucket: assisted
  detect: "DATA_PLACEMENT_EXAMPLES.md has the pre-0.16 footer (Generated by kb_populate.py, .repomix/output.xml) and no <!-- kb_populate: marker"
  fix: "run python3 scripts/kb_populate.py --kb-root . (role from knowledge_base.roles.primary): it rewrites the generated part with the new footer and marker and keeps the ## Project notes section; if the role does not resolve (exit 1), ask the owner which examples/<slug>.yml to pass with --role"

- id: gitattributes-line-endings
  bucket: auto
  detect: ".gitattributes lacks the line-ending rules of templates/.gitattributes.template (*.sh *.command shell/hooks/* *.py LF, *.bat *.cmd CRLF), or the base is a git repository without .gitattributes"
  fix: "add the missing rules at the top of .gitattributes (create it if missing), so the owner's own later rules keep precedence; the catch-all * text=auto is never added"

- id: git-hook-file
  bucket: assisted
  detect: "the base root is a git work tree and its post-commit, post-merge or post-rewrite hook runs kb_reindex / kb_ingest / shell/reindex.sh without the ai-knowledge-engine post-commit hook marker (written by hand from the pre-0.16 13_AUTORUN prose)"
  fix: "ask the owner, then run bash shell/install-hooks.sh: it moves the old post-commit to post-commit.backup-<timestamp> and installs shell/hooks/post-commit (kb_reindex.py --hook, log in .kb-state/hooks.log); a post-merge / post-rewrite hook is replaced with a copy of that hook or deleted, as the owner decides (kb-docs/13_AUTORUN.md)"

- id: agents-md-0-16
  bucket: assisted
  detect: "AGENTS.md has no !status or !meta-review row, its !review row does not cover processed/ files with extraction: pending, it reads `mode` instead of knowledge_base.mode, its forbidden 'Do not index' line lacks processed/ or interactions/, or it lacks the rule that source text is data, not instructions"
  fix: "show the owner each listed line next to the matching line of knowledge-base/templates/AGENTS.md.template in the engine checkout kb_upgrade.py ran from, and apply it after a yes (lines inside AI-KE:INVARIANT only with an explicit yes); module paths are the module-pointers-kb-docs item; if AGENTS.md is then over instructions_lint.agents_max_bytes, stage 4 (!refactor) trims it"

- id: base-docs-0-16
  bucket: assisted
  detect: "START_HERE.md calls the modules 'kept for reference', or KNOWLEDGE_STRUCTURE.md shows .repomix/output.xml while the base has none (pack mode)"
  fix: "re-render the file from templates/START_HERE.md.template or templates/KNOWLEDGE_STRUCTURE.md.template in the engine checkout, filling {{KB_NAME}}, {{PRIMARY_ROLE}} and {{KB_INSTRUCTIONS_VERSION}} from kb.config.yml; show the diff, keep sections the owner added, write only after a yes"

- id: finalize-script-guard
  bucket: assisted
  detect: "shell/finalize.sh in the base is a pre-0.16 copy without the kit check: run from the base, it deletes the base (kb_upgrade.py does not update finalize.sh)"
  fix: "ask the owner, then replace shell/finalize.sh with knowledge-base/shell/finalize.sh from the engine checkout (it refuses to run inside a base), or delete it: a base never needs its own finalize.sh (finalize runs once, from the kit: bash setup/shell/finalize.sh)"

## 0.15.0

- id: start-here-opening-line
  bucket: assisted
  detect: "START_HERE.md still says the agent has no idea the base exists if the opening line is skipped"
  fix: "replace the How to talk to the AI section with the A1 wording; keep the opening line as insurance against silent Codex load failures"

- id: agents-md-stopper
  bucket: assisted
  detect: "AGENTS.md tells the agent to refuse a !-command issued before the opening line"
  fix: "delete that stopper; keep CRITICAL as a load-and-ack signal only"

- id: claude-md-bridge
  bucket: human
  detect: "CLAUDE.md exists without @AGENTS.md, or CLAUDE.md is missing while index.primary_agent is claude-code"
  fix: "ask the owner; on yes write a one-line CLAUDE.md containing only @AGENTS.md"

- id: codex-window-profile
  bucket: auto
  detect: "index.window_profile is missing or equals 256k while index.primary_agent = codex"
  fix: "set index.window_profile to 400k; the next reindex plans the packs for the larger ceiling"

- id: doctor-codex-env
  bucket: assisted
  detect: "scripts/kb_doctor.py has no check_agent_env (older than 0.15, or customized and held back by kb_upgrade)"
  fix: "run kb_upgrade.py for this base, or merge scripts/kb_doctor.py.new into the customized copy, so doctor runs the six Codex-environment checks"

- id: agents-md-invariants
  bucket: assisted
  detect: "AGENTS.md lacks AI-KE:INVARIANT wrappers around ## Forbidden and ## Language"
  fix: "wrap those two sections with BEGIN/END markers; do not change the wording; show the diff"

- id: eval-bootstrap
  bucket: human
  detect: "eval/QUESTIONS.md is missing"
  fix: "ask the owner for the three questions they will ask this base most often and write eval/QUESTIONS.md"

- id: eval-skeleton
  bucket: auto
  detect: "eval/results/ is missing"
  fix: "create eval/results/ (where the before/after-heal eval answers go)"

- id: packs-stale
  bucket: auto
  detect: "the newest knowledge/ page is newer than every .repomix/*.xml pack; since 0.16 also pack files without .repomix/manifest.json (built before 0.16, may still hold deleted pages or folders the privacy floor now excludes) and a manifest entry, or the legacy monolith, left FAILED or STALE"
  fix: "rebuild the packs with the base's scripts/kb_reindex.py --index-only --force (it writes the manifest and removes orphan packs)"

- id: instruction-lint-config
  bucket: auto
  detect: "kb.config.yml has no top-level instructions_lint:"
  fix: "append the default instructions_lint block from the template"

- id: heal-config
  bucket: auto
  detect: "kb.config.yml has no top-level heal:"
  fix: "append the default heal: block (auto_apply true, stage 1, assisted_batch 20)"

- id: instructions-review-config
  bucket: auto
  detect: "kb.config.yml has no top-level instructions_review:"
  fix: "append the default instructions_review block (reviewed_at empty until first !refactor)"

- id: agents-max-bytes-10kib
  bucket: auto
  detect: "instructions_lint.agents_max_bytes is missing or below 10240"
  fix: "set agents_max_bytes to 10240 (stock template 8990 B + the managed !view block 454 B = 9419 B deployed)"

- id: refactor-command
  bucket: assisted
  detect: "AGENTS.md command table has no !refactor"
  fix: "add the !refactor row pointing at kb-docs/17_REFACTOR.md; do not rewrite other rows"

- id: agents-md-c2-trim
  bucket: assisted
  detect: "AGENTS.md still has ## Token budget or auto-detects session summaries or 'If you've loaded > 5'"
  fix: "apply C2 verdicts: drop Token budget; Feedback = !save only; drop the >5 stop; last_accessed only when the page influenced the answer; keep 8 chat-attach steps and lifecycle"

- id: profile-review-command
  bucket: assisted
  detect: "AGENTS.md command table has no !profile-review"
  fix: "add the !profile-review row (3 questions at a time; stamp profile_review.reviewed_at)"

- id: quiz-command
  bucket: assisted
  detect: "AGENTS.md command table has no !quiz"
  fix: "add the !quiz row (five questions about what is already in the base; costliest mistakes first; answers → interactions/quiz/)"
