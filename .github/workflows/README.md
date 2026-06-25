# CI workflows — PERMANENTLY DISABLED (by design)

> ⛔ **There is no CI for this repository, and that is intentional. Do not
> enable it.**

## Why this repo has no CI

This repository is a **download-only template**. It is:

- **never deployed** anywhere (no server, no service, no package release),
- **never built** into an artifact,
- **not a contributor-traffic project** that benefits from PR validation.

People simply **clone or download** it and then initialize a knowledge base in
**their own project** by following the instruction modules in `knowledge-base/`.
There is literally nothing to ship. Running GitHub Actions here only burns
Actions minutes and produces **noisy failures "into the void"** for a repo that
will never be deployed.

So CI is **off on purpose** — not by oversight.

## For AI agents and contributors (please read)

Agents repeatedly try to "fix" the missing CI. **Don't.** Specifically:

- ❌ Do **not** rename `ci.yml.disabled` to `ci.yml` (or `*.yaml`).
- ❌ Do **not** create any new file under `.github/workflows/` with a `.yml` /
  `.yaml` extension.
- ❌ Do **not** add other CI providers (Actions, Travis, CircleCI, etc.).
- ✅ Run checks **locally** instead: `pytest` from the repo root.

This is a standing project decision. If you think CI is needed, that's almost
certainly wrong for this repo — leave it disabled.

## Status

| File | State |
|------|-------|
| `ci.yml.disabled` | Disabled. The `.disabled` suffix keeps GitHub from detecting it. Kept only as a historical reference of what a test pipeline *would* look like. As an extra safety net it also has no `push`/`pull_request` triggers. |

## How GitHub decides whether to run a workflow

GitHub Actions only runs files matching `.github/workflows/*.yml` or
`*.yaml`. Because the only workflow here ends in `.disabled`, **nothing runs**.
Keep it that way.

## Running tests locally (the supported way)

```bash
pip install -r knowledge-base/templates/requirements.txt
pip install -r knowledge-base/templates/requirements-dev.txt
pytest
```
