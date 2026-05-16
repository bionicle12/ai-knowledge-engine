# Upgrading a deployed knowledge base

> Guide for upgrading the reference scripts in an already-deployed knowledge base when the source repo (`ai-knowledge-engine`) ships a new version.

## How versioning works

- Source repo holds `VERSION` (e.g., `0.5.0`)
- A deployed KB records `instructions_version` in `kb.config.yml`
- When the deployed value lags the source, an upgrade is available

## When to upgrade

- New features land (new module, new command, new lint rule)
- Bug fixes in the reference scripts
- Security fixes

Check the source repo's `CHANGELOG.md` to see what changed and whether you need it.

## How to upgrade

### Step 1: get the latest source

```bash
cd /path/to/ai-knowledge-engine
git pull   # or download the latest release
cat VERSION
```

### Step 2: dry-run the upgrade

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
    --kb-root /path/to/your-kb \
    --dry-run
```

You will see a plan with one of these states per file:

- **up_to_date** — no change needed
- **missing** — the file is absent in the deployed KB; will be added
- **clean_overwrite** — your file matches the previous release's version exactly → safe to overwrite
- **customized** — you (or someone) modified the file locally → upgrade will write a `.new` sidecar instead of overwriting

### Step 3: actually upgrade

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
    --kb-root /path/to/your-kb
```

If everything is `up_to_date` or `clean_overwrite`, this is the whole story. Your `kb.config.yml` gets a fresh `instructions_version`.

### Step 4: handle customized files

If you see `customized` files, the upgrade tool wrote `<name>.new` next to each. Open them in your editor:

```bash
diff scripts/kb_lint.py scripts/kb_lint.py.new
```

Decide:
- If your customization is no longer needed → delete the original, rename `.new` to the original
- If your customization is still needed → port your changes onto the new version, then delete `.new`
- If you want to see a tidy unified diff first:

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
    --kb-root /path/to/your-kb \
    --diff
```

### Step 5: re-run smoke tests

```bash
cd /path/to/your-kb
./doctor.sh
```

The doctor script verifies the environment, dependencies, structure, and that the spaCy model loads. Fix any reported errors before continuing daily work.

### Step 6: re-bump if you handled customizations

After resolving every `.new`, run the upgrade again:

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py --kb-root /path/to/your-kb
```

This time it should report `up_to_date` and bump `instructions_version` cleanly.

## What the upgrade does NOT touch

- `kb.config.yml` (only the `instructions_version` field is updated)
- `repomix.config.json`
- `AGENTS.md`, `KNOWLEDGE_STRUCTURE.md`, `DATA_PLACEMENT_EXAMPLES.md` (your customizations)
- `knowledge/`, `raw/`, `processed/`, `assets/`, `assets-index/`
- `interactions/`, `review/`
- `log.md`

## Force mode

If you are certain you want to discard local changes to reference scripts:

```bash
python3 /path/to/ai-knowledge-engine/scripts/kb_upgrade.py \
    --kb-root /path/to/your-kb \
    --force
```

This treats every file as `clean_overwrite`. Use sparingly.

## Major-version bumps

When source `VERSION` jumps a major (e.g., `0.x → 1.0`), there may be breaking changes — config schema changes, removed flags, restructured directories. Read `CHANGELOG.md` carefully and check for migration notes here in `UPGRADING.md` (added under the version heading).

## Rollback

If an upgrade breaks your setup:

1. Restore each script from a backup or the previous git tag:
   ```bash
   git -C /path/to/ai-knowledge-engine show v0.4.0:knowledge-base/scripts/kb_lint.py > /path/to/your-kb/scripts/kb_lint.py
   ```
2. Manually edit `kb.config.yml`'s `instructions_version` back to the previous value
3. Investigate the breakage; if it's a bug, file an issue against `ai-knowledge-engine`
