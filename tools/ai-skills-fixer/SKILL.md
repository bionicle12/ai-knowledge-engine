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
  skills without an explicit approved change plan.

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
  candidate without touching the worktree; `source promote <id>` —
  move the checkout to that candidate (installed skills change only
  through a new approved plan). A source ID is one path component:
  lowercase letters, digits, `.`, `_`, `-`, starting with a letter or
  digit (no `/`, `:` or `..`); without `--id` it is derived from the URL.
  Credentials embedded in the URL are dropped from the registry, plans,
  and messages; git keeps the URL it cloned from in the checkout's own
  `.git/config` (never copied into a release or a host skill), so
  prefer a git credential helper for private repos. A skill folder that
  is a link resolving outside the checkout (or into `.git`) makes the
  source untrusted: `source add` refuses it and `reconcile` stops.
  Linked folders that are not skills themselves are never searched.
- `catalog [id]` — list skills provided by registered sources.
- `usage` — advisory usage evidence from host session logs (offline,
  aggregate counts only; not-observed never means unused, and
  uniform counts across skills are catalog-listing baseline noise).
- `audit [name]` — structural lint + prompt-debt signals; reports are
  persisted to `state/reports/` when the store exists.
- `profile show` / `profile set <skill-id> <state> [--targets ...]` —
  the deterministic write path for profile decisions.
- `reconcile [--machine-id ID] [--prune]` — dry-run plan (desired vs
  installed): install/adopt/update/review/quarantine/noop operations
  with preconditions, the host user roots, a deterministic content-hash
  plan ID, and a lockfile proposal, saved under `state/plans/`. Nothing
  is applied without `--apply`. Plans only change direct children of a
  host's user skill root; a single-skill source installs under its
  source ID. Whatever the planner cannot prove safe becomes a `review`
  op (never applied) with its reason in `notes.review_reasons`: a copy
  that differs from the source, an `excluded` skill whose installed
  copy is not an exact copy or a managed link of that source (your own
  same-named skill is never quarantined), a managed release edited in
  place, a source skill with symlinks resolving outside it, or a
  same-named skill nested in a folder of the root. The printed apply
  command repeats `--home` when one was given.
- `reconcile --apply <plan-id> [--home PATH]` — apply a saved approved
  plan. Refuses a plan file whose content no longer hashes to its ID
  (edited after approval), that touches anything but a direct child of
  a recorded user root, or whose recorded user roots differ from the
  ones discovered now for `--home` and the environment (pass the same
  `--home` as `reconcile`; a plan saved by an older version is refused
  too — run `reconcile` again), then checks config-hash and
  source-commit drift, re-checks every op's precondition, backs up
  replaced content under `state/backups/`, and validates after each
  install. The apply record
  is written before and during the run as a journal. On any failure the
  failing op's partial effects are undone, completed ops are rolled
  back, and anything that cannot be undone is marked `needs-recovery`
  in the record. Requires explicit user approval of the exact plan.
- `rollback <apply-id>` — restore the pre-apply state byte-identically
  from the apply record and backups. Progress is saved after every
  undone op: if content changed after the apply blocks one step, the
  command stops with that op marked `needs-recovery`; resolve it and
  run the same `rollback` again to finish.
- Releases under `releases/` are read-only snapshots (files, and on
  POSIX folders too; `.git` folders are never copied); one that no
  longer matches its content hash is never reused or linked again.
- `eval` (spec §16) is not implemented — see
  [references/evaluation.md](references/evaluation.md).
- Exit codes: `0` success, `2` safe stop (validation/§19 condition,
  including a refused plan), `3` plan drift or failed precondition,
  `1` any other error.

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
- Lint `unsafe-symlink` (error): a symlink inside the skill resolves
  outside it — absolute, climbing with `..`, escaping only once another
  link is followed (`x -> .`, `up -> x/..`), or looping. Links are
  resolved one component at a time with the skill folder as the top.
  Treat it as a supply-chain red flag; reconcile never installs such a
  source skill and no release is made of it.

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
4. `reconcile` → present the exact plan, including every review reason
   → apply only after the user approves that plan ID
   (`reconcile --apply <plan-id>`), then verify. `rollback <apply-id>`
   restores the previous state; after a failed apply, report any
   `needs-recovery` op with the recorded reason before retrying.
5. Host specifics (paths, capabilities, telemetry) live under
   [references/hosts/](references/hosts/). Local adaptations pass all
   six §12 gates or are not proposed at all.
