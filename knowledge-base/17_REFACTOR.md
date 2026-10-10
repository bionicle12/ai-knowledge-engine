# 17 — Refactor: return instruction debt

> Two-step trim of live instruction files. Analysis is separated from
> the rewrite so the owner chooses, and the agent does not invent extra
> rules. Counterpart to `!heal` stage 4 (`kb-docs/18_HEAL.md`).
>
> There is **no** `kb_refactor.py`. The agent follows this module.

---

## When

Lint warns `agents-bytes`, `instruction-absolutes`, `work-ordering` or
`instructions-review` (`instructions_review.reviewed_at` is stale); a new model generation arrived;
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
- Managed blocks `AI-KE:INDEX`, `AI-KE:VIEW`, `AI-KE:STATUS` — leave
  them. `kb_upgrade.py` owns them: it compares each with the engine's
  `templates/AGENTS.md.template`, keeps a local edit only while that
  reference block is unchanged, and asks for a merge when it changes
- Files outside the base, including `~/.codex/AGENTS.md`
- `knowledge/**` content pages (that is `!audit` / `!review`)

---

## Fresh sessions

The eval runs need a **fresh session** — one that has not seen this
refactor. You cannot open one yourself. Ask the owner, in one message:
"Please open a new chat in this base, paste the three questions from
`eval/QUESTIONS.md`, and save the answers as `eval/results/<file>`" — or
start a sub-agent with a clean context if the tool has one. Never answer
the questions in the session that audits or rewrites.

## Cycle

1. **Baseline.** Fresh session. Answer `eval/QUESTIONS.md`. Write
   `eval/results/<YYYY-MM-DD>__before-refactor.md`. If the three
   questions are missing, stop and treat that as a `!heal` human item
   (stage 3). If a page a question `must cite` does not exist yet (a
   young base), the question measures nothing — ask the owner to swap it
   for one the base can already answer. Do not trim without a measure.
2. **Step 1 — audit (no writes).** Line-by-line, in the five categories
   of the table below. Output a table: id, excerpt, category, proposed
   action, why. **Stop.** Ask the owner concrete questions with
   answer options. Do not rewrite yet.
3. **Step 2 — rewrite from decisions only.** After the owner answers:
   assemble the new text from those verdicts. Add nothing they did
   not choose. Backup first: copy every file you will change into
   `.kb-state/refactor-backups/<YYYYMMDDTHHMMSS>/`, keeping its path
   relative to the base root. Not into `.kb-backups/`: that folder holds
   `kb_heal.py`'s own runs, and heal's `--verify` / `--rollback` skip a
   folder heal did not write. Write the new `AGENTS.md` (and other
   scoped files only if a verdict said so).
4. **After.** Fresh session. Answer the same three questions →
   `eval/results/<YYYY-MM-DD>__post-refactor.md`. The owner compares
   before and after against the `must cite` / `must mention` /
   `must NOT propose` lines and adds one verdict line on its own:
   `eval: ok` or `eval: regressed`. The verdict is not the rewriting
   session's call. Use no other wording. On `eval: regressed` copy
   every file from the backup folder back to its path and **stop**.
   `kb_heal.py --verify` never undoes a refactor: it judges heal runs by
   the `*after*` files in `eval/results/` — which is why this file is
   named `post-refactor`.
5. **Stamp.** In `kb.config.yml` (edit those lines only; keep the
   comments) set `instructions_review.reviewed_at` to today,
   `reviewed_model` to the model that just ran, `clean_run_baseline`
   to the post-refactor result path. Log operation `refactor`.

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

1. One fresh session **without** `AGENTS.md` — raw capability on
   `eval/QUESTIONS.md`. Ask the owner to run it outside the base (a
   chat opened in an empty folder, so `AGENTS.md` is not loaded) and
   save the answers as `eval/results/<date>__clean-run.md`.
2. One fresh session **with** the base loaded as usual. Save as
   `eval/results/<date>__instructed.md`.
3. The owner compares the two. If instructed is worse than
   clean-run, the instructions are the debt — run `!refactor` from step 1. If instructed is better or
   equal, stamp `instructions_review` and stop.

---

## Brakes

| Brake | Rule |
|-------|------|
| Honest zero | Nothing over threshold and review is fresh → stop |
| No measure | No `eval/QUESTIONS.md` → do not write a shorter `AGENTS.md` |
| Eval regression | Verdict line `eval: regressed` → copy the files back from `.kb-state/refactor-backups/<stamp>/` and stop |
| `--global` | Report only; never write outside the base |
| INVARIANT | Never change the wording inside the wrappers |

---

## Config

```yaml
instructions_review:
  reviewed_at: "2026-08-23"
  reviewed_model: "gpt-5.6-codex"
  clean_run_baseline: "eval/results/2026-08-23__post-refactor.md"
```

Lint (`kb-docs/09_LINT.md`) warns when `reviewed_at` is older than
`instructions_lint.review_stale_days` (default 90). Missing
`reviewed_at` is not a warning — heal can append the block.
