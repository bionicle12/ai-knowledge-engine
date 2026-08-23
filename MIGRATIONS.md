# Migrations

Catch-up steps for a **already deployed** knowledge base after the engine
version that added the capability. `kb_heal.py` (iteration F) reads this
registry and takes the range between the base's `instructions_version` and
the current repo `VERSION`.

Format of each step: `id`, `bucket` (`auto` / `assisted` / `human`),
`detect`, `fix`.

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
  detect: "Claude Code is used and CLAUDE.md is missing or does not contain @AGENTS.md"
  fix: "ask the owner; on yes write a one-line CLAUDE.md containing only @AGENTS.md"

- id: codex-window-profile
  bucket: auto
  detect: "index.window_profile is missing or equals 256k while index.primary_agent = codex"
  fix: "set window_profile to 400k and rebuild packs"

- id: doctor-codex-env
  bucket: auto
  detect: "scripts/kb_doctor.py has no check_agent_env"
  fix: "upgrade scripts so doctor runs the six Codex-environment checks"

- id: agents-md-invariants
  bucket: assisted
  detect: "AGENTS.md lacks AI-KE:INVARIANT wrappers around ## Forbidden and ## Language"
  fix: "wrap those two sections with BEGIN/END markers; do not change the wording; show the diff"

- id: eval-bootstrap
  bucket: human
  detect: "eval/QUESTIONS.md is missing"
  fix: "ask the owner for the three questions they will ask this base most often and write eval/QUESTIONS.md"

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
  fix: "add the !refactor row pointing at 17_REFACTOR.md; do not rewrite other rows"

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
