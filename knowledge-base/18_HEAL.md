# 18 — Heal: catch-up after an upgrade

> Closes the loop that `kb_upgrade.py` deliberately leaves open: new scripts
> and new checks land, but the **contents** of an old base are not rewritten.
> Heal collects what is still wrong and applies only what needs no judgement.
>
> **Reference implementation:** `knowledge-base/scripts/kb_heal.py`.
> The agent copies this script during deployment (or `kb_upgrade.py` does).

---

## When

After every upgrade, and whenever `kb_doctor` warns `heal:after-upgrade` or
`heal:stage-stuck`. The user (or the upgrader) says `!heal`.

A fresh base with nothing to catch up is a **valid** outcome: say the base is
in order and stop.

---

## Command

`!heal` → follow this module. Mechanics:

```bash
python3 scripts/kb_heal.py --plan          # write review/needs-heal/HEAL_PLAN.md
python3 scripts/kb_heal.py --apply auto    # auto bucket only; backups in .kb-backups/
python3 scripts/kb_heal.py --verify        # rollback if eval/results/*after* says it regressed
python3 scripts/kb_heal.py --rollback      # restore the latest backup
```

`--apply` accepts **only** `auto`. Assisted and human items are never applied
by the script.

`kb_upgrade.py` already runs `--plan` and `--apply auto` at the end of
`upgrade_one` (including when customized files produced `.new` sidecars).
`--dry-run` stays dry: detect is printed, nothing is written. Disable with
`--no-heal` or `heal.auto_apply: false`.

---

## Cycle

1. **Detect.** Run `--plan`. Show the summary. If there are no findings —
   **«база в порядке»** and stop. Do not invent work.
2. **Baseline.** Run `eval/QUESTIONS.md` in a **fresh** session. Save answers
   in `eval/results/<YYYY-MM-DD>__before-heal.md`. If `eval/QUESTIONS.md` is
   missing, that is the first **human** item — start there.
3. **auto.** `python3 scripts/kb_heal.py --apply auto`. Idempotent. Backup
   first. Do not apply assisted or human.
4. **assisted.** Walk **one item at a time**, in error-cost order (answers
   the base gets wrong first; cosmetics last). For each item: what we found,
   what we propose, one decision from the human. Cap: `heal.assisted_batch`
   (default 20) items per session. Log each decision as operation `heal`.
5. **human.** Leave checkboxes in `HEAL_PLAN.md`. `!heal` is not *finished*
   until they are closed, but they do not block daily work.
6. **Verify.** `--plan` again. Re-run eval → `eval/results/<date>__after-heal.md`.
   If eval **regressed** (mark the file with `eval: regressed` or
   `verdict: failed`), run `--verify` / `--rollback` and **stop**. Do not
   continue "just in case".

---

## Brakes

| Brake | Rule |
|-------|------|
| Honest zero | No findings → stop immediately |
| Stagnation | Two consecutive plans with the same open ids → stop and show what will not heal |
| Budget | Assisted queue longer than `assisted_batch` is split across sessions |
| Eval regression | Hard stop + rollback from `.kb-backups/` |

---

## Five stages (`heal.stage`)

One launch = one stage. The next stage does not start until the current one
is closed (checkboxes done, `heal.stage` bumped). Record progress in
`kb.config.yml`.

| Stage | Name | What it does | Risk |
|------:|------|--------------|------|
| 1 | **safe** | Environment, structure, auto bucket, `AI-KE:INVARIANT` wrappers | None — nothing is deleted or shortened |
| 2 | **hygiene** | L1 defects: broken links, duplicate slugs, orphans, expired `valid_until`, `.new` sidecars | Low, local, reversible |
| 3 | **measure** | Create `eval/QUESTIONS.md`, take the before-heal baseline | None, but needs the owner |
| 4 | **trim** | `!refactor` on `AGENTS.md` | **High** — only after stage 3 |
| 5 | **content** | Profile review, contradictions, `!audit` by pack | Medium, expensive |

**Stage 4 is physically unavailable until stage 3 is closed.** Closed means
`eval/QUESTIONS.md` exists, has `## Q1.` / `## Q2.` / `## Q3.`, and is not an
unfilled `{{EVAL_*}}` template. `kb_heal.py --plan` lists trim findings as
**locked** until then. Do not bump `heal.stage` to 4 yourself to skip the gate.

A fresh base often finishes stages 1–3 in one sitting because there is
nothing to repair.

---

## Buckets

| Bucket | Who | Examples |
|--------|-----|----------|
| **auto** | Script, no questions | `window_profile: 400k` for Codex, default `instructions_lint:` / `heal:`, `eval/results/` skeleton |
| **assisted** | AI + one human decision per item | Broken wikilinks, duplicate slugs, orphans, expired pages, merge `.new` sidecars, wrap `AI-KE:INVARIANT` |
| **human** | Owner only | Three eval questions, profile review, sign-off on a trimmed `AGENTS.md`, `!refactor` |

---

## Config

```yaml
heal:
  auto_apply: true          # kb_upgrade.py applies the auto bucket
  stage: 1                  # 1 safe … 5 content
  assisted_batch: 20        # max assisted items per !heal session
  last_run:
    at: "2026-08-23"
    version: "0.15.0"       # instructions_version at last apply
```

`kb_doctor` warns when `instructions_version` moved but `heal.last_run.version`
did not, or when `heal.stage` is 2-4 and `last_run.at` is older than 14 days.

Two things heal will not do to this file. It **edits `kb.config.yml` line by
line** and never round-trips it through a YAML dumper, because the file is
hand-edited and full of comments that a dump would silently drop. And inside
`kb_upgrade` it stamps `last_run.version` with the version the base is *moving
to*, not the one it still carries: heal runs before the version bump on purpose
(it needs the old value to pick the `MIGRATIONS.md` range), so stamping the old
one would make doctor report a clean upgrade as unhealed.

A `kb.config.yml` that does not parse stops heal, not the upgrade: the file sync
completes, heal prints the YAML error and the base is left alone until you fix
it.

---

## Ownership

`review/needs-heal/` is a review queue: not indexed. `.kb-backups/` is
machine-local; gitignore it. `MIGRATIONS.md` lives in the engine repo and
lists catch-up steps (`id`, `bucket`, `detect`, `fix`). Heal runs each step's
detect function; version headers document when the capability appeared.
After `kb_upgrade` bumps `instructions_version`, detect still runs — a bumped
version is not proof the contents were healed.
