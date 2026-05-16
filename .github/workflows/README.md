# CI workflows — currently DISABLED

> 🚫 **Do not enable CI without an explicit request from the project owner.**
>
> The repo is local-only at the moment — there is no public GitHub instance,
> no deployment, and no contributor traffic that would benefit from CI runs.
> Running workflows would consume Actions minutes for no gain.

## Status

| File | State |
|------|-------|
| `ci.yml.disabled` | Disabled. The `.disabled` suffix prevents GitHub Actions from picking it up. |

## What the workflow does (when enabled)

When activated, `ci.yml` runs five jobs:

- **test** — pytest on Python 3.11 / 3.12 (Ubuntu) and 3.12 (macOS), with coverage upload to Codecov
- **doctor** — `kb_doctor.py --self-test --skip-nlp` smoke check
- **lint-shell** — `bash -n` syntax check + shellcheck (warnings only) on all `*.sh` files
- **validate-yaml** — verifies role examples and `kb.config.yml.template` parse cleanly
- **check-translations** — runs `scripts/check_translations.py` (non-blocking)

## How to enable

When you're ready (e.g., made the repo public, want PR validation):

```bash
git mv .github/workflows/ci.yml.disabled .github/workflows/ci.yml
git commit -m "ci: re-enable workflows"
git push
```

That's it. The file's contents are unchanged — only its filename was tweaked
to fall outside GitHub's workflow detection (`*.yml` / `*.yaml`).

## How to confirm CI is disabled

```bash
ls .github/workflows/
# Should show only files ending in .disabled (and this README).
# If you see *.yml or *.yaml — workflows are LIVE.
```

## Why use `.disabled` instead of deleting

- **History preserved.** When CI is needed, one rename brings it back exactly as it was.
- **Discoverable.** Future contributors see the disabled file and understand the workflow exists, just paused.
- **Reversible.** Deleting and re-adding loses the file's git history; renaming keeps `git blame` and prior commits.
