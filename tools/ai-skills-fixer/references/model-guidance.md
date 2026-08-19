# Model guidance lifecycle (spec §13)

Prompt audits use dated model profiles, never one permanent rule set.
The cache lives in the store at `state/model-guidance/<model-id>.yml`.

## Cache entry format

```yaml
model: claude-fable-5            # public model identifier
provider: anthropic
aliases: [fable-5]               # names observed in clients
sources:                         # official URLs actually fetched
  - url: https://platform.claude.com/docs/...
    retrieved_at: 2026-08-19
retrieved_at: 2026-08-19
expires_after_days: 60
summary: |
  Applicable guidance, summarized in your own words.
migration_notes: |
  Differences that matter when moving skills to this model.
unresolved: []                   # claims you could not verify
status: verified                 # verified | unverified
last_audit: null
```

## Source priority

1. Official provider documentation.
2. Official product documentation for the agent harness.
3. Current local research articles as secondary analysis.
4. External primary research only where it directly supports an
   evaluation method.

## Refresh triggers

Research again when a configured or observed model version changes,
the cached profile expires, official URLs change materially, or a
skill contains model-specific behavior not covered by the cache.

## Unverified models

If an exact requested model version has no official documentation, set
`status: unverified`. You may recommend a clean baseline evaluation;
you must NOT invent model-specific rules, and `trained-default`/`relic`
removal recommendations are off the table for that model.

## Incremental migration method (default)

1. Run representative tasks on the new model with customization and
   third-party skills disabled.
2. Establish base behavior.
3. Enable the current skill; rerun the same tasks.
4. Remove or change one instruction group at a time.
5. Retain only measured improvements and true invariants.
