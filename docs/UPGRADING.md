# Upgrading deployed knowledge bases

The authoritative updater is `scripts/kb_upgrade.py` in the current
`ai-knowledge-engine` source checkout. A deployed KB records the engine version
it carries in `kb.config.yml → instructions_version`.

## Safe upgrade flow

1. Update or otherwise select the source checkout you trust.
2. Run a dry-run against the deployed KB.
3. Review any `customized` and `held` rows.
4. Run the upgrade.
5. In the base, say `!heal` if the summary lists remaining items, then run the
   doctor and reindex commands.

## What the upgrader maintains

The engine layer of the base, and nothing else:

| In the engine checkout | In the deployed base |
|---|---|
| `knowledge-base/scripts/kb_*.py` | `scripts/` |
| `knowledge-base/scripts/kb_viewer/**` (offline graph viewer) | `scripts/kb_viewer/` |
| `knowledge-base/shell/**` except `finalize.sh` (wrappers, `_kbpy.sh`, `hooks/`, …) | `shell/` |
| `knowledge-base/shell/*.bat`, `*.command` (double-click launchers) | the base root, where `finalize.sh` put them — or `shell/` when the base keeps them there. A launcher the base does not have yet joins the others: in `shell/` when every launcher the base has is there, else at the root |
| `knowledge-base/templates/requirements*.txt` (not `requirements-dev.txt`) | the base root |
| `knowledge-base/NN_*.md` and `knowledge-base/README.md` | `kb-docs/` |
| managed blocks of `knowledge-base/templates/AGENTS.md.template` (`AI-KE:VIEW`, `AI-KE:INDEX`, `AI-KE:STATUS`) | the same blocks in `AGENTS.md` |

It also appends the `index:` section to `kb.config.yml` when a base has none
(pack-based index, see `kb-docs/05_INDEX.md`) and sets `instructions_version`.
Every `kb.config.yml` change is a line edit: comments and the rest of the
file stay as they are.

The git hook itself is not touched: `shell/install-hooks.sh` installed a copy
of `shell/hooks/post-commit` into the repository's hooks folder. When that copy
differs from the base's `shell/hooks/post-commit` after the upgrade, the
summary says so; re-run `bash shell/install-hooks.sh` (it keeps the old copy
as `post-commit.backup-<timestamp>`).

It never modifies `knowledge/`, `raw/`, `processed/`, `assets/`, review
queues, interactions, role configuration, or any `AGENTS.md` text outside the
managed blocks. `AI-KE:INVARIANT` blocks are reported (`present` / `missing`),
never written — wrapping missing ones is left to `!heal`.

Catch-up that is not a file copy — new `kb.config.yml` sections such as
`media:` and `sync:`, the `sync/` workspace, moving old root-level
`17_REFACTOR.md` / `18_HEAL.md` into `kb-docs/` — is done by heal from the
`MIGRATIONS.md` entries (see [After the file sync: heal](#after-the-file-sync-heal)).

## First upgrade

Run the central updater by absolute path.

### Windows PowerShell

```powershell
$repo = "C:\path\to\ai-knowledge-engine"
$kb = "C:\path\to\kb-name"

python "$repo\scripts\kb_upgrade.py" --kb-root $kb --dry-run
python "$repo\scripts\kb_upgrade.py" --kb-root $kb
```

### macOS

```bash
repo="$HOME/path/to/ai-knowledge-engine"
kb="$HOME/path/to/kb-name"

python3 "$repo/scripts/kb_upgrade.py" --kb-root "$kb" --dry-run
python3 "$repo/scripts/kb_upgrade.py" --kb-root "$kb"
```

### Linux

```bash
repo="/path/to/ai-knowledge-engine"
kb="/path/to/kb-name"

python3 "$repo/scripts/kb_upgrade.py" --kb-root "$kb" --dry-run
python3 "$repo/scripts/kb_upgrade.py" --kb-root "$kb"
```

`--root` is accepted as an alias of `--kb-root`; without either, the current
directory is the base.

## Later upgrades from inside the KB

Every base carries `scripts/kb_update.py`, a thin launcher that always
delegates to the current central updater instead of carrying stale upgrade
rules.

```powershell
# Windows
cd C:\path\to\kb-name
python scripts\kb_update.py --dry-run
python scripts\kb_update.py
```

```bash
# macOS / Linux
cd /path/to/kb-name
python3 scripts/kb_update.py --dry-run
python3 scripts/kb_update.py
```

The launcher searches the current directory and its parents for
`ai-knowledge-engine`. If the source checkout is elsewhere, use either:

```text
--repo-root /path/to/ai-knowledge-engine
```

or set `AI_KNOWLEDGE_ENGINE_HOME`:

```powershell
$env:AI_KNOWLEDGE_ENGINE_HOME = "C:\path\to\ai-knowledge-engine"
```

```bash
export AI_KNOWLEDGE_ENGINE_HOME="/path/to/ai-knowledge-engine"
```

Every other option (`--dry-run`, `--accept`, `--accept-local`, …) is passed
through to `kb_upgrade.py`.

## Updating several `kb-*` bases

The central updater scans only immediate `kb-*` children containing
`kb.config.yml`. The exit code is the worst one over all bases.

```powershell
python C:\path\to\ai-knowledge-engine\scripts\kb_upgrade.py `
  --all-root C:\path\to\brain-my-ai --dry-run
```

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
  --all-root /path/to/brain-my-ai --dry-run
```

Remove `--dry-run` after reviewing every section of the batch plan.

`scripts/sync_deployed_bases.py` is deprecated. It prints a notice and runs
the regular upgrade on the folder you give it (the folder itself when it holds
`kb.config.yml`, plus each immediate subfolder that does), so customized files
get `.new` sidecars instead of being overwritten. Use `kb_upgrade.py
--kb-root` / `--all-root` instead.

## Understanding the plan

Each managed file gets one row:

| State | Meaning | Action |
|---|---|---|
| `up_to_date` | the deployed file equals the engine's (CRLF and LF count as equal) | none |
| `missing` | the base has no such file | copied |
| `clean_overwrite` | the deployed file is an unmodified copy of some earlier engine version | overwritten |
| `kept` | local edits, but the engine's version has not changed since the base's `instructions_version` | left alone, nothing to merge |
| `customized` | local edits, and the engine's version changed since then | original left alone; the new version is written next to it as `<file>.new` |
| `held` | the new version depends on a file that is `customized` or `held` (see below) | not installed yet: a new `kb_lint.py` would crash against an old, customized `kb_common.py` |
| `accepted` | you passed `--accept` for this file, or `--force` and the file is `customized` | local copy backed up, then overwritten |
| `accepted_local` | you passed `--accept-local` | local file kept as the merged result |

What a new file depends on, so that it waits with it:

- a script: the modules it imports (`kb_common.py` is imported by almost
  every script) and the scripts it runs — a string that is exactly a script
  name (optionally `scripts/…`), as in `_py("kb_lint.py", "--quick")`; a
  script named inside a longer message does not count;
- `kb_view.py` and `scripts/kb_viewer/**`: each other;
- a shell wrapper, hook or launcher: the `scripts/kb_*.py` it runs,
  `shell/_kbpy.sh` and the `shell/*.sh` wrappers it calls — comment lines
  (`#`, `REM`, `::`) and the `setup/scripts/…` probe that detects the deploy
  layout do not count;
- a `kb-docs/` module: every `kb_*.py` script it mentions — the new text
  describes the new scripts. A module the base does not have yet (a base from
  before 0.16 has no `kb-docs/`) has no older text to protect: it waits only
  for the scripts it mentions that the base does not have at all, so one
  customized script does not keep most of `kb-docs/` out.

The managed `AGENTS.md` blocks wait the same way for the scripts they describe
(`VIEW` → `kb_view.py`, `INDEX` → `kb_reindex.py`, `STATUS` → `kb_status.py`,
plus any script named in the block): the row says `held` and the block is left
as it is.

Once the live file is current (`up_to_date`, `missing`, `clean_overwrite`,
`accepted`) or builds on the current version (`kept`, `accepted_local`), a
leftover `<file>.new` is removed when it holds the engine's version or any
earlier engine version — for example the sidecars a pre-0.16 upgrader wrote.
A `.new` with any other content is left in place and the row says so.

A dry-run changes no file of the base, writes no `.new` sidecars and records
no decision (lint, run by the heal preview, may refresh its own caches in
`.kb-state/`).

### How pristine copies are recognised

`scripts/known_hashes.json` lists every committed version of each managed
file and managed block, and the releases that shipped it. A deployed file
equal to any of them is replaced without asking — no git tags and no git
history are needed, so an engine downloaded as a ZIP or cloned shallowly
works. When the registry does not know a file, the upgrader searches the
checkout's own git history as a fallback. The registry also answers "did the
engine's version change since the base's version?", which decides between
`kept` and `customized`.

Maintainers regenerate the registry with `python3 scripts/build_known_hashes.py`
before each release (`docs/MAINTENANCE.md`).

## Customized files

Show focused diffs:

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
  --kb-root /path/to/kb-name --dry-run --diff
```

A normal run writes `<file>.new` next to each customized file and keeps the
original. Resolve each one in one of two ways:

- **Keep your version.** Merge what you need from `<file>.new` into the live
  file, then:

  ```bash
  python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
    --kb-root /path/to/kb-name --accept-local kb_ingest.py
  ```

  The `.new` sidecar is removed and the decision is remembered (in
  `.kb-state/upgrade-local.json`) until either your file or the engine's
  version changes, so the next plain run does not ask again.

  `kb_common.py` is checked first: every `kbc.<name>` the engine scripts
  installed next to it use must be defined in your copy. When one is missing
  (the `.new` was not merged), `--accept-local kb_common.py` is refused: the
  row stays `customized` and names what is missing, the `.new` stays, and the
  scripts that import it stay `held` — installing them would only move the
  crash to their first run. Merge those names, or take the engine's version
  with `--accept kb_common.py`.

- **Take the engine's version.**

  ```bash
  python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
    --kb-root /path/to/kb-name --accept kb_ingest.py --accept kb_stt.py
  ```

  Your copy is saved first to
  `.kb-state/upgrade-backups/<YYYYMMDDTHHMMSS>/<path in the base>`, then
  overwritten; a `<file>.new` equal to the engine's version is removed.

Names may be written as `kb_ingest.py`, `scripts/kb_ingest.py`,
`shell/reindex.sh`, `reindex.bat`, `requirements.txt` or `kb-docs/05_INDEX.md`.
Both flags are repeatable; giving both for the same file is an error (exit 3);
an unknown name prints a warning. `--accept FILE` also replaces a `kept` file
and overrides an earlier `--accept-local` for that file.

`--force` means `--accept` for every `customized` file — every file that would
otherwise get a `.new` sidecar — with each local copy backed up the same way.
It leaves `kept` files and files you resolved with `--accept-local` alone;
name those with `--accept` to replace them.

Resolving a customized file releases the files held behind it on the same
run. `.kb-state/` is ignored by git; keep `upgrade-backups/` until you no
longer need the old copies.

## AGENTS.md managed blocks

`AGENTS.md` is a live file: agents legitimately evolve it while working in the
base. The upgrader reads the current `VIEW`, `INDEX` and `STATUS` blocks from
`knowledge-base/templates/AGENTS.md.template` and handles each block of the
deployed file like this:

- **Equal to the reference** — nothing to do (a leftover
  `AGENTS.md.<label>-block.new` holding the reference or an earlier one is
  removed).
- **Equal to a known earlier reference** — replaced (the same leftover
  sidecar is removed).
- **Missing** — inserted: `STATUS` right after the `INDEX` block, the others
  (and `STATUS` when there is no `INDEX` block) at the end of the file. A
  missing `AGENTS.md` is created.
- **Edited locally, reference unchanged since the base's version** — kept
  silently: your edit already builds on the current reference. A leftover
  sidecar holding the reference or an earlier one (a pre-0.16 upgrader left
  such files) is removed, unless it belongs to a merge this upgrader
  requested and the agent has not finished.
- **Edited locally, reference changed since then** — `AGENTS.md` stays
  untouched; the new reference block goes to a sidecar
  (`AGENTS.md.view-block.new`, `AGENTS.md.index-block.new`,
  `AGENTS.md.status-block.new`) and the upgrade prints a ready-to-paste prompt:

  > Compare AGENTS.md with AGENTS.md.index-block.new: integrate the
  > improvements from the new reference block into the corresponding managed
  > section of AGENTS.md WITHOUT losing any local customizations, then delete
  > AGENTS.md.index-block.new.

  The merge is requested once per reference version (remembered in
  `.kb-state/upgrade-local.json`). While the sidecar exists the row says
  `AI merge pending` and the run exits 2; once the agent has merged and
  deleted it, the block is kept on every later run. A pending block merge
  does not hold back the version bump.
- **Describes a held script** — left as it is (`held`) until that script is
  resolved.
- **Damaged markers** (a marker missing, duplicated or out of order) — the
  file stays untouched and the reference block goes to the sidecar for an AI
  merge.

`--force`, `--accept` and `--accept-local` apply to files only; block merges
always stay AI-mediated. A CRLF `AGENTS.md` keeps its line endings.

## Version bump

`instructions_version` is set to the checkout's `VERSION` (in place — a
trailing comment on that line survives) only when:

- no file is `customized` or `held`,
- heal did not fail, and
- `kb.config.yml` parses and can be edited.

Otherwise the run ends with `[WARN] instructions_version stays at <version>`
and exits 2; resolve the rows and run again. The version never moves
backwards: a base whose `instructions_version` is newer than the checkout is
refused (exit 3) before anything is written — update the checkout instead.

## After the file sync: heal

Every normal run (also when files were customized or held) ends with heal,
using the **base's own** `scripts/kb_heal.py` in a separate Python process —
so a base left inconsistent by the file sync fails here instead of being
reported as healed:

1. collect findings (lint and doctor run once; again only after an auto fix
   was applied);
2. `--apply auto` unless `heal.auto_apply: false`;
3. write `review/needs-heal/HEAL_PLAN.md` with the remaining items;
4. print a summary and `→ next: скажи агенту "!heal"`.

`--no-heal` skips all of it — no detect, no plan, no summary; the run prints
`Heal skipped (--no-heal)`. Run `python3 scripts/kb_heal.py --plan` in the
base later. A base without `scripts/kb_heal.py` (an old base whose new
`kb_heal.py` is held back) skips heal with a warning.

Heal stamps `heal.last_run.version` with the version the base is moving to —
or, when the bump waits, the newer of the base's `instructions_version` and
the previous stamp, never an older one.

`--dry-run` runs only the detect step, with the engine's copy of
`kb_heal.py` (the base's copy is not updated yet), and writes nothing:

```
Heal detect (dry-run, engine scripts, not written): auto=2 assisted=1 human=0
```

If heal crashes (for example a held, older `kb_common.py` lacks something the
base's `kb_heal.py` needs), the upgrade prints `[WARN] heal failed …` with the
error, keeps the version and exits 2. Run `python3 scripts/kb_doctor.py` and
`python3 scripts/kb_heal.py --plan` in the base.

If `kb.config.yml` does not parse, the file sync still completes and you get:

```
[WARN] heal skipped: ScannerError: while scanning a simple key …
  Fix kb.config.yml, then run: python3 scripts/kb_heal.py --plan
```

The auto bucket edits `kb.config.yml` line by line (for example the missing
`media:` / `sync:` sections), fills the `eval/` and `sync/` skeletons, appends
missing `.gitignore` lines, moves pristine root-level `17_REFACTOR.md` /
`18_HEAL.md` into `kb-docs/`, backfills the extraction registry, moves
`keybert` into `requirements-nlp.txt`, adds the line-ending rules to
`.gitattributes`, renames the old session flag `redacted:` to
`redaction_required:` and rebuilds stale packs. Every file it
edits is copied into `.kb-backups/` first (`kb_heal.py --rollback` undoes the
run and keeps files edited since; rebuilt packs are regenerated, not backed
up); re-running it changes nothing the second time. The plan then lists as an
assisted item any `AGENTS.md` / `START_HERE.md` / `KNOWLEDGE_STRUCTURE.md`
references that still point at the old module places. The assisted and human
buckets are walked with the
agent: say `!heal` in the base (`kb-docs/18_HEAL.md`; stage 4 is `!refactor`,
`kb-docs/17_REFACTOR.md`).

## Verification

After a successful upgrade:

```powershell
# Windows
python scripts\kb_doctor.py
python scripts\kb_view.py --background
```

```bash
# macOS / Linux
./shell/doctor.sh
python3 scripts/kb_view.py --background
```

Re-running `kb_update.py --dry-run` should show every file as `up_to_date`
or `kept` and the managed blocks as `up_to_date` or `edited` (kept).

## Exit codes

- `0` — already current, upgraded successfully, or a dry-run with nothing to
  review.
- `2` — something needs you: a `customized` or `held` file, a pending
  `AGENTS.md` block merge, a failed heal, or a `kb.config.yml` that does not
  parse or cannot be edited.
- `3` — no `kb.config.yml`, no `kb-*` base under `--all-root`, a base newer
  than the checkout, or `--accept` and `--accept-local` for the same file.

## Major versions and rollback

For a major version change, read `CHANGELOG.md` before applying the plan.
Files replaced through `--accept` / `--force` are under
`.kb-state/upgrade-backups/<timestamp>/`; heal's snapshots of the files its
auto fixes edited are under `.kb-backups/`. Anything else — including `instructions_version` — is restored
from version control or your own backup; knowledge content is outside the
updater's write scope.
