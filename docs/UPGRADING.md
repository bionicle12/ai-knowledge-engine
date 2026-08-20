# Upgrading deployed knowledge bases

The authoritative updater lives in the current `ai-knowledge-engine` source
checkout. A deployed KB records its source version in
`kb.config.yml → instructions_version`.

## Safe upgrade flow

1. Update or otherwise select the source checkout you trust.
2. Run a dry-run against the deployed KB.
3. Review any `customized` files.
4. Run the upgrade.
5. Run the deployed doctor and reindex commands.

The upgrader changes reference scripts, `shell/*.sh`, the offline graph viewer,
and its own thin deployed launcher. It also appends or refreshes a marked
`!view` block inside `AGENTS.md`. Text outside that managed block is preserved.

It does not modify `knowledge/`, `raw/`, `processed/`, `assets/`, review
queues, interactions, role configuration, or other user-authored AGENTS
instructions.

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

## Later upgrades from inside the KB

The first upgrade installs `scripts/kb_update.py`, a thin launcher that always
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

## Updating several `kb-*` bases

The central updater scans only immediate `kb-*` children containing
`kb.config.yml`.

```powershell
python C:\path\to\ai-knowledge-engine\scripts\kb_upgrade.py `
  --all-root C:\path\to\brain-my-ai --dry-run
```

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
  --all-root /path/to/brain-my-ai --dry-run
```

Remove `--dry-run` after reviewing every section of the batch plan.

## Understanding the plan

- `up_to_date` — deployed content already equals the source.
- `missing` — the reference file or managed block will be added.
- `clean_overwrite` — the file matches a known historical upstream version.
- `customized` — the updater cannot prove replacement is safe; the normal run
  writes `<file>.new` and leaves the original untouched.

A dry-run never changes files and never writes `.new` sidecars.

## Customized files

Show focused diffs:

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
  --kb-root /path/to/kb-name --dry-run --diff
```

If inspection confirms that one file should use the upstream version, accept
only that file:

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
  --kb-root /path/to/kb-name \
  --accept kb_ingest.py \
  --accept kb_stt.py
```

Names may be written as `kb_ingest.py`, `scripts/kb_ingest.py`, or
`shell/reindex.sh`. `--accept` is repeatable and does not authorize overwriting
other customized files.

Use `--force` only when every customization in reference scripts may be
discarded:

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
  --kb-root /path/to/kb-name --force
```

## AGENTS.md is merged by an AI agent, never overwritten

`AGENTS.md` is a live file: agents legitimately evolve it while working in
the base (new commands, sharpened rules, role notes). The upgrader therefore
touches only its managed blocks (`AI-KE:VIEW`, `AI-KE:INDEX`), and even those
it auto-replaces **only when the deployed block text matches a known reference
version**. In every other case — local edits inside a managed block, or
damaged markers — it:

1. leaves `AGENTS.md` completely untouched;
2. writes the fresh reference block to a sidecar
   (`AGENTS.md.view-block.new` / `AGENTS.md.index-block.new`);
3. reports `AI merge required` (which also blocks the version bump, like any
   customized file) and prints a ready-to-paste prompt.

To finish the upgrade, ask the AI agent working in that base:

> Compare AGENTS.md with AGENTS.md.index-block.new: integrate the
> improvements from the new reference block into the corresponding managed
> section of AGENTS.md WITHOUT losing any local customizations, then delete
> the .new file.

Then re-run `kb_upgrade.py` — with the block matching the reference again, the
version bump proceeds. `--force` does NOT override this: forced runs discard
script customizations, but AGENTS.md merges always stay AI-mediated.

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

Re-running `kb_update.py --dry-run` should show all reference files and the
managed `!view` block as `up_to_date`.

## Exit codes

- `0` — dry-run completed without manual conflicts, already current, or
  upgraded successfully.
- `2` — one or more customized files or managed-marker conflicts require
  review.
- `3` — target/source discovery or KB validation failed.

## Major versions and rollback

For a major version change, read `CHANGELOG.md` before applying the plan.
Rollback should restore the deployed scripts and `instructions_version` from
version control or a backup; knowledge content is outside the updater's write
scope.
