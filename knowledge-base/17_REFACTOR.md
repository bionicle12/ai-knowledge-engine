# 17 — Refactor: return instruction debt

> Two-step trim of live instruction files. Analysis is separated from
> the rewrite so the owner chooses, and the agent does not invent extra
> rules. Counterpart to `!heal` stage 4 (`18_HEAL.md`).
>
> There is **no** `kb_refactor.py`. The agent follows this module.

---

## When

Lint warns `agents-bytes`, `instruction-absolutes`, or `work-ordering`;
`instructions_review.reviewed_at` is stale; a new model generation arrived;
or the owner said `!refactor`.

A base that is already under the lint thresholds and recently reviewed is
a **valid** outcome: say so and stop.

---

## Command

`!refactor` → follow this module.

`!refactor --global` → **report only**. Compare `~/.codex/AGENTS.md` (or
`$CODEX_HOME/AGENTS.override.md` if that file is non-empty) with this
base's `AGENTS.md`. List overlaps and contradictions. **Do not write**
any file outside the base. Do not edit `~/.codex/*`.

---

## Scope

Default (inside the base only):

- `AGENTS.md`
- `kb.config.yml` (instruction-related keys: `instructions_lint`,
  `instructions_review`, `mode_profiles` comments — not `knowledge/`)
- `KNOWLEDGE_STRUCTURE.md`
- `DATA_PLACEMENT_EXAMPLES.md`

Never:

- `AI-KE:INVARIANT` bodies (`forbidden`, `language`) — report if they
  conflict with something else; do not rewrite the wording
- `AI-KE:INDEX` / `AI-KE:VIEW` unless you also update the matching
  blocks in the engine `kb_upgrade.py` (deployed bases: leave them;
  they are managed)
- Files outside the base, including `~/.codex/AGENTS.md`
- `knowledge/**` content pages (that is `!audit` / `!review`)

---

## Cycle

1. **Baseline.** Fresh session. Answer `eval/QUESTIONS.md`. Write
   `eval/results/<YYYY-MM-DD>__before-refactor.md`. If the three
   questions are missing, stop and treat that as a `!heal` human item
   (stage 3). Do not trim without a measure.
2. **Step 1 — audit (no writes).** Line-by-line, same five categories
   as C1 (`docs/proposals/agents-md-audit.md` in the engine, or the
   table below). Output a table: id, excerpt, category, proposed
   action, why. **Stop.** Ask the owner concrete questions with
   answer options. Do not rewrite yet.
3. **Step 2 — rewrite from decisions only.** After the owner answers:
   assemble the new text from those verdicts. Add nothing they did
   not choose. Backup first: copy the scoped files into
   `.kb-backups/<timestamp>/`. Write the new `AGENTS.md` (and other
   scoped files only if a verdict said so).
4. **After.** Fresh session. Answer the same three questions →
   `eval/results/<YYYY-MM-DD>__after-refactor.md`. If the after file
   says `eval: regressed` / `verdict: failed` / `регресс`, restore
   the backup and **stop**.
5. **Stamp.** Set `instructions_review.reviewed_at` to today,
   `reviewed_model` to the model that just ran, `clean_run_baseline`
   to the after-refactor result path. Log operation `refactor`.

---

## Categories (step 1)

| # | Name | If the owner agrees |
|---|------|---------------------|
| 1 | invariant — the model would not know this | keep |
| 2 | trained default | delete |
| 3 | relic — written for an old model or a bug that is gone | delete |
| 4 | 90% rule written as always/never | rewrite as a condition |
| 5 | conflict / internal duplicate | keep one side |

`AI-KE:INVARIANT` blocks are category 1 automatically. Do not put them
in the decision set.

---

## Clean run (model change)

When the owner switches primary model (or `instructions_review` is
stale):

1. One fresh session **without** treating `AGENTS.md` as law — raw
   capability on `eval/QUESTIONS.md`. Save as
   `eval/results/<date>__clean-run.md`.
2. One fresh session **with** the base loaded as usual. Save as
   `eval/results/<date>__instructed.md`.
3. If instructed is worse than clean-run, the instructions are the
   debt — run `!refactor` from step 1. If instructed is better or
   equal, stamp `instructions_review` and stop.

---

## Brakes

| Brake | Rule |
|-------|------|
| Honest zero | Nothing over threshold and review is fresh → stop |
| No measure | No `eval/QUESTIONS.md` → do not write a shorter `AGENTS.md` |
| Eval regression | Restore `.kb-backups/` and stop |
| `--global` | Report only; never write outside the base |
| INVARIANT | Never change the wording inside the wrappers |

---

## Config

```yaml
instructions_review:
  reviewed_at: "2026-08-23"
  reviewed_model: "gpt-5.6-codex"
  clean_run_baseline: "eval/results/2026-08-23__after-refactor.md"
```

Lint (`09_LINT.md`) warns when `reviewed_at` is older than
`instructions_lint.review_stale_days` (default 90). Missing
`reviewed_at` is not a warning — heal can append the block.
