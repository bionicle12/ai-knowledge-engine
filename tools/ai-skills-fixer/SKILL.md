---
name: ai-skills-fixer
description: Use when inventorying, auditing, or curating installed AI agent skills across Claude Code, Codex, Cursor, and Antigravity — detects copies and their provenance, duplicate names, structural lint issues, and token cost; manages a declarative store with source registry, profile, dry-run reconciliation plans, drift-checked apply, and rollback. Never mutates installed skills without an explicitly approved plan ID.
---

# AI Skills Fixer

Repository-local tool for curating AI agent skills. Design:
[docs/superpowers/specs/2026-08-19-ai-skills-fixer-design.md](../../docs/superpowers/specs/2026-08-19-ai-skills-fixer-design.md).

Division of labor (non-negotiable):

- Python collects facts, validates files, and calculates hashes. It never
  decides whether a skill is useful.
- The agent interprets facts and recommends. It never mutates installed
  skills without an explicit approved change plan (Phase 3+; Phase 1 has
  no mutation paths at all).

## Commands

```bash
python3 tools/ai-skills-fixer/scripts/run.py <command> [--json]
```

- `inventory [--source-repo PATH]...` — read-only scan of installed
  skills with provenance, duplicates, lint, and size estimates.
- `init [--machine-id ID]` — create the managed store (default:
  sibling `skill-repositories/`; override with `--store-root` or
  `AI_SKILLS_FIXER_STORE_ROOT`).
- `doctor` — environment and store checks.
- `source add <url|path> [--id ID] [--ref REF]` — clone into the store
  and register; `source refresh [id]` — fetch and record an update
  candidate without touching the worktree.
- `catalog [id]` — list skills provided by registered sources.
- `usage` — advisory usage evidence from host session logs (offline,
  aggregate counts only; not-observed never means unused, and
  uniform counts across skills are catalog-listing baseline noise).
- `audit [name]` — structural lint + prompt-debt signals; reports are
  persisted to `state/reports/` when the store exists.
- `profile show` / `profile set <skill-id> <state> [--targets ...]` —
  the deterministic write path for profile decisions.
- `reconcile [--machine-id ID]` — dry-run plan (desired vs installed):
  install/adopt/review/quarantine/noop operations with preconditions,
  deterministic content-hash plan ID, and a lockfile proposal, saved
  under `state/plans/`. Nothing is applied without `--apply`.
- `reconcile --apply <plan-id>` — apply a saved approved plan. Checks
  config-hash and source-commit drift first, re-checks every op's
  precondition, backs up replaced content under `state/backups/`,
  validates after each install, and auto-rolls-back completed ops on
  partial failure. Requires explicit user approval of the exact plan.
- `rollback <apply-id>` — restore the pre-apply state byte-identically
  from the apply record and backups.
- Exit codes: `0` success, `2` safe stop (validation/§19 condition),
  `3` plan drift or failed precondition, `1` any other error.

## Interpreting the output

- `provenance.level`: `exact` (byte-identical to the source checkout),
  `probable` (identical content, different folder name), `modified-copy`
  (name matches a source skill, content differs), `unknown`.
- A `modified-copy` may simply come from a different ecosystem with the
  same skill name. Register that ecosystem's repo as another
  `--source-repo` before concluding the user edited anything.
- Plugin- and system-managed skills (`root_kind` of `plugin`/`system`)
  are never name-matched and must be handled through the owning client,
  not by editing files.
- Token counts are size-based estimates (chars/4), always labeled.
  Absence of usage telemetry is never evidence of non-use.

## Workflow for the agent

1. Run `inventory --json` with every locally cloned source repo;
   summarize per-host counts, provenance breakdown, duplicates, and
   lint errors — lead with what the user would act on. Interpret
   provenance per [references/provenance.md](references/provenance.md).
2. To fill or revise the profile, run the adaptive questionnaire from
   [references/questionnaire.md](references/questionnaire.md): category
   questions first, then batched per-skill decision cards; record every
   decision via `profile set`.
3. `audit [--json]` produces deterministic evidence: structural lint,
   prompt-debt signals, cross-skill boilerplate, and model-guidance
   cache status. Classify instructions per
   [references/audit-rubric.md](references/audit-rubric.md); claims
   that the current model "already does this" require a fresh cache
   entry per [references/model-guidance.md](references/model-guidance.md).
4. `reconcile` → present the exact plan → apply only after the user
   approves that plan ID (`reconcile --apply <plan-id>`), then verify.
   `rollback <apply-id>` restores the previous state.
5. Host specifics (paths, capabilities, telemetry) live under
   [references/hosts/](references/hosts/). Local adaptations pass all
   six §12 gates or are not proposed at all.
