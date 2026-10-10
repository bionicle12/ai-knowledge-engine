# 18 — Heal: catch-up after an upgrade

> Closes the loop that `kb_upgrade.py` deliberately leaves open: new scripts
> and new checks land, but the **contents** of an old base are not rewritten.
> Heal collects what is still wrong and applies only what needs no judgement.
>
> **Reference implementation:** `knowledge-base/scripts/kb_heal.py`.
> In a deployed base this module is `kb-docs/18_HEAL.md` and the script is
> `scripts/kb_heal.py` (`kb_upgrade.py` keeps both current).

---

## When

After every upgrade, and whenever `kb_doctor` warns `heal:after-upgrade` or
`heal:stage-stuck`, or `STATUS.md` shows a `heal:` line. The user (or the
upgrader) says `!heal`.

A fresh base with nothing to catch up is a **valid** outcome: say the base is
in order and stop.

Heal is **catch-up only**: `MIGRATIONS.md` steps, hanging `.new` sidecars,
`AI-KE:INVARIANT` blocks, `kb.config.yml` that heal cannot edit, L1 lint
errors, doctor errors. Content hygiene — stale pages and orphans — is not a
heal item; `python3 scripts/kb_lint.py` reports it (`kb-docs/09_LINT.md`). Lint
issues on pages under `_archive/` are not heal items either.

---

## Command

`!heal` → follow this module. Mechanics:

```bash
python3 scripts/kb_heal.py --plan          # write review/needs-heal/HEAL_PLAN.md
python3 scripts/kb_heal.py --plan --json   # same, and print the summary + items as JSON
python3 scripts/kb_heal.py --apply auto    # auto bucket only; backups in .kb-backups/
python3 scripts/kb_heal.py --verify        # roll back if the newest eval verdict says it regressed
python3 scripts/kb_heal.py --rollback      # undo the newest heal run
```

`--apply` accepts **only** `auto`. Assisted and human items are never applied
by the script. `--plan` and `--apply auto` both end by rewriting `HEAL_PLAN.md`
(after `--apply auto` it no longer lists the items just fixed) and
`STATUS.md`, unless `status.enabled: false`.

`kb_upgrade.py` runs the base's own `scripts/kb_heal.py` at the end of the
upgrade: it applies the auto bucket (unless `heal.auto_apply: false`) and
writes the plan. `--dry-run` stays dry: detect is printed, nothing is
written. Disable with `--no-heal`.

---

## The plan

`review/needs-heal/HEAL_PLAN.md`. Its first line is a machine-readable
summary that `kb_status.py` turns into the `heal:` line of `STATUS.md`:

```text
<!-- heal-summary: version=0.16.0 plan_id=1a2b3c4d stage=2 auto=0 assisted=3 human=1 -->
```

- `version` — the heal scripts' engine version.
- `plan_id` — first 8 hex digits of the SHA-256 of the sorted open item ids.
  The same open items give the same id.
- `stage` — the stage the base is in (see [Five stages](#five-stages-healstage)).
- `auto` / `assisted` / `human` — every open item per bucket, including
  locked and later-stage ones.

Below it: the stage, `assisted_batch`, the previous plan's id
(`previous plan: <id>`, with `— same open items` when nothing changed), a
summary, then the sections `auto`, `assisted` (at most `assisted_batch`
items; the rest under "deferred to later sessions"), `human`, "Later stages"
(items of stages after the current one, listed but not started) and "Locked"
(stage 4 trim while the measure gate is closed). Every item shows its id,
its stage, what was found and the fix. Each lint issue is its own item: two
broken links in one page are two items (`lint:broken-link:<page>` and
`…#2`).

---

## Cycle

1. **Detect.** Run `--plan`. Show the summary. If there are no findings —
   **«база в порядке»** and stop. Do not invent work.
2. **Baseline.** If `eval/QUESTIONS.md` exists, run it in a **fresh**
   session (ask the owner to open one — you cannot start it yourself). Save
   the answers in `eval/results/<YYYY-MM-DD>__before-heal.md`. Without the
   questions, stages 1–2 go ahead (they delete and shorten nothing); stage 3
   creates the questions before any trim.
3. **auto.** `python3 scripts/kb_heal.py --apply auto`. Idempotent; every
   file it changes is copied to `.kb-backups/` first. Do not apply assisted or
   human.
4. **assisted.** Walk the current stage **one item at a time**, in error-cost
   order (answers the base gets wrong first; cosmetics last). For each item:
   what we found, what we propose, one decision from the human. Cap:
   `heal.assisted_batch` (default 20) items per session. Log each decision as
   operation `heal`.
5. **human.** Leave checkboxes in `HEAL_PLAN.md`. `!heal` is not *finished*
   until they are closed, but they do not block daily work.
6. **Verify.** `--plan` again. If the plan says `— same open items` after you
   worked through items, that is the stagnation brake: stop and show the owner
   what will not heal. Re-run eval in a fresh session (again the owner opens
   it) → `eval/results/<date>__after-heal.md`. If it **regressed**, put a line that
   is exactly `eval: regressed` (or `verdict: failed`) in that file, run
   `--verify`, and **stop**. Do not continue "just in case".

---

## Brakes

| Brake | Rule |
|-------|------|
| Honest zero | No findings → stop immediately |
| Stagnation | The plan written after a working session says `previous plan: <id> — same open items` → stop and show what will not heal (on the first `--plan` of a session the flag only means nothing changed since the last plan) |
| Budget | Assisted queue longer than `assisted_batch` is split across sessions |
| Eval regression | Hard stop + `--verify` rolls back the newest heal run |

`--verify` reads the newest `eval/results/*after*.md`. It rolls back only
when that file has a line that is exactly `eval: regressed` or
`verdict: failed` (case-insensitive) **and** was written after the newest
backup — an older verdict judged an older state. A note such as "no
regressions" never triggers it, and a backup is rolled back only once.
`--apply auto` does not look at eval files.

---

## Five stages (`heal.stage`)

One launch = one stage. The next stage does not start until the current one
is closed: nothing open at this stage or below.

| Stage | Name | What it does | Risk |
|------:|------|--------------|------|
| 1 | **safe** | Environment, structure, config, the auto bucket, `AI-KE:INVARIANT` wrappers, private folders in `.gitignore`, private file names in old `assets-index/` titles, hand-written git hooks, an old `shell/finalize.sh` | None — nothing is deleted or shortened |
| 2 | **hygiene** | L1 lint errors (broken links, duplicate slugs, expired `valid_until`, missing frontmatter fields), `.new` sidecars, missing command rows and other pre-0.16 lines in `AGENTS.md` / `START_HERE.md` / `KNOWLEDGE_STRUCTURE.md` / `DATA_PLACEMENT_EXAMPLES.md`, the meta-review backlog of old session summaries | Low, local, reversible |
| 3 | **measure** | Create `eval/QUESTIONS.md`, take the before-heal baseline; `CLAUDE.md` bridge | None, but needs the owner |
| 4 | **trim** | `!refactor` on `AGENTS.md` (`kb-docs/17_REFACTOR.md`; the refactor restores its own backup, `--verify` does not undo it) | **High** — only after stage 3 |
| 5 | **content** | Profile review, instructions review, `!audit` by pack | Medium, expensive |

Heal moves the stage itself. The plan's stage is the configured
`heal.stage`, advanced past every stage that has nothing open;
`--apply auto` writes that value to `heal.stage` (and logs `heal.stage 1 → 2`).
Items of later stages appear under "Later stages" until then. Auto items are
applied whatever the stage. Setting `heal.stage` higher by hand shows later
items as current work — it never unlocks stage 4.

**Stage 4 is physically unavailable until stage 3 is closed.** Closed means
`eval/QUESTIONS.md` exists, has `## Q1.` / `## Q2.` / `## Q3.`, and is not an
unfilled `{{EVAL_*}}` template. `kb_heal.py --plan` lists trim findings as
**locked** until then, and heal never advances `heal.stage` past 3 while the
gate is closed. Do not bump `heal.stage` to 4 yourself to skip the gate.

A fresh base often finishes stages 1–3 in one sitting because there is
nothing to repair.

---

## Buckets

| Bucket | Who | Examples |
|--------|-----|----------|
| **auto** | Script, no questions | Missing `instructions_lint:` / `heal:` / `instructions_review:` / `media:` / `sync:` sections, `window_profile: 400k` for Codex, `eval/results/` and `sync/` folders, missing `.gitignore` lines for `.kb-state/`, `STATUS.md` and backups, pristine root-level `17_REFACTOR.md` / `18_HEAL.md` moved into `kb-docs/`, the extraction-registry backfill of old ingest metadata, `keybert` moved to `requirements-nlp.txt`, stale packs rebuilt, the line-ending rules added to `.gitattributes`, the old session flag `redacted:` renamed to `redaction_required:` |
| **assisted** | AI + one human decision per item | Broken wikilinks, duplicate slugs, expired pages, merge `.new` sidecars, wrap `AI-KE:INVARIANT`, private folders missing from `.gitignore`, a root-level module with local edits, module references in `AGENTS.md` / `START_HERE.md` / `KNOWLEDGE_STRUCTURE.md` that lead nowhere since the modules live in `kb-docs/` (`18_HEAL.md` → `kb-docs/18_HEAL.md`), the 0.16 `AGENTS.md` rows and rules, old `START_HERE.md` / `KNOWLEDGE_STRUCTURE.md` / `DATA_PLACEMENT_EXAMPLES.md` text, ingest metadata without `raw_category:` (the owner names each file's `raw/` folder), a hand-written git hook, a pre-0.16 `shell/finalize.sh` that can delete the base, session summaries without `meta_reviewed:`, an auto step this base cannot take (the reason is shown), doctor errors, `lint:crashed` / `doctor:crashed` when a check stops with an error (the rest of the plan is still built) |
| **human** | Owner only | Three eval questions, `CLAUDE.md` bridge, a nested or moved `.venv`, sign-off on a trimmed `AGENTS.md`, profile and instructions review, manual `MIGRATIONS.md` steps |

An auto step becomes **assisted**, with the reason, when this base cannot
take it: a `kb.config.yml` section in flow style (`index: {…}`), a
`scripts/kb_ingest.py` older than 0.16 for the extraction backfill, no
`scripts/kb_reindex.py` for stale packs.

`.gitignore` lines are appended only to an existing `.gitignore`. A git
repository without one is an assisted item (copy `templates/.gitignore.template`
after asking). To version one of `raw/`, `assets/`, `processed/`, `review/`,
`interactions/` on purpose, write `!/<folder>/` in `.gitignore`: heal takes
that as the owner's decision.

The `.gitattributes` line-ending rules (LF for shell scripts, the hook and
Python, CRLF for `.bat` / `.cmd`) go at the top of an existing file, so the
owner's later rules still win; a git repository without the file gets a new
one. The catch-all `* text=auto` is never added to an existing base.

---

## Config

```yaml
heal:
  auto_apply: true          # kb_upgrade.py applies the auto bucket
  stage: 1                  # 1 safe … 5 content; heal advances it
  assisted_batch: 20        # max assisted items per !heal session
  last_run:
    at: "2026-08-23"
    version: "0.15.0"       # instructions_version at last apply
```

`kb_doctor` warns when `instructions_version` moved but `heal.last_run.version`
did not, or when `heal.stage` is 2-4 and `last_run.at` is older than 14 days.

Two things heal will not do to this file. It **edits `kb.config.yml` line by
line** (`kb_common.config_set` / `config_append_block`) and never
round-trips it through a YAML dumper: every comment and the key order stay,
a commented-out line such as `# agents_max_bytes: 9216` is never edited, and
a block indented by four spaces stays four. The one comment it removes is the
template's commented-out `# last_run:` placeholder when it writes the real
`last_run`. And inside `kb_upgrade` it stamps `last_run.version` with the
version the base is *moving to*, not the one it still carries: heal runs
before the version bump on purpose (it needs the old value for manual
`MIGRATIONS.md` steps), so stamping the old one would make doctor report a
clean upgrade as unhealed.

A `heal:` section in flow style (`heal: {auto_apply: false, stage: 3}`)
cannot be edited line by line: heal leaves it as it is (it never adds a second
`heal:`) and lists the assisted item `heal-config-block-style` — rewrite it
one key per line.

A `kb.config.yml` that does not parse stops heal, not the upgrade: the file sync
completes, heal prints the YAML error (exit code 3) and the base is left alone
until you fix it.

---

## Backups and rollback

`--apply auto` copies every file it is about to change into
`.kb-backups/<YYYYmmddTHHMMSS>/files/` and records in `MANIFEST.json` the
SHA-256 of each file before and after, plus the folders it created. A run that
changes nothing writes no backup and no log entry.

`--rollback` undoes the newest heal run not rolled back yet: a file still
exactly as heal left it is restored (a file heal created is deleted, empty
folders it created are removed); a file edited since then is **kept** and
listed — compare it with the copy under `files/` by hand. A manifest path
that leads outside the base (`..`, a symlink) is **refused** and listed;
nothing there is written or deleted. Exit code 0 when everything was
restored, 2 when a file was kept or refused, 1 when no run is left to
undo. Run `--rollback` again to undo the run before. Each rollback is logged
as operation `heal`.

Rollback and `--verify` only look at folders heal wrote (a `MANIFEST.json`
from `kb_heal`). Anything else in `.kb-backups/` — a pre-0.16 `!refactor` copy, a
snapshot of your own — is never restored or marked, however new it is;
restore such a copy by copying its files back. A heal backup made before
0.16 (a `MANIFEST.txt` reading `kb_heal backup`) records no after-state:
rollback restores nothing from it, lists its files once for a manual
comparison (exit code 2) and marks it, so the next `--rollback` moves on to
the run before.

---

## Ownership

`review/needs-heal/` is a review queue: not indexed. `.kb-backups/` is
machine-local; gitignore it (the auto step `gitignore-kb-backups` does).
`MIGRATIONS.md` lives in the engine repo and lists catch-up steps (`id`,
`bucket`, `detect`, `fix`); `kb_heal.py` keeps the same ids and buckets in
code, so heal still works when the engine checkout is out of reach, and a
test fails when the two disagree. Heal runs every step's detector on every
run: after `kb_upgrade` bumps `instructions_version`, detect still runs — a
bumped version is not proof the contents were healed. The version headers
record when a step appeared; a step without a detector (only in a fork or a
hand-edited registry) is listed as a manual **human** item while the base's
`instructions_version` is below the step's version.
