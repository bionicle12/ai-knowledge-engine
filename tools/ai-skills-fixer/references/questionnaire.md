# Adaptive profile questionnaire (spec §10)

Goal: fill the profile with informed user decisions, asking as few
questions as possible. Combine detected evidence (inventory, catalog,
usage) with answers; inspect only workspace roots the user has put in
scope.

## Flow

1. Infer likely categories from the user's project roots and inventory.
2. Ask category-level questions first. Scale: frequent / occasional /
   interested / excluded / unsure.
3. Skip every skill in explicitly excluded categories.
4. Group remaining skills in batches of five to ten.
5. Prioritize: duplicates, expensive discovery metadata, ambiguous
   usage, high-risk skills.
6. Persist category answers in `profiles/default.yml` under a
   `domains:` map with the answer date; later sessions re-ask only
   missing or expired categories.

Categories: frontend, backend, mobile, desktop, embedded; databases,
analytics, machine learning, data engineering; cloud, containers,
CI/CD, observability; architecture, testing, debugging, code review,
security; documentation, scientific writing, UI/UX, SEO, marketing,
payments, messaging, blockchain.

## Decision card (mandatory before any per-skill question)

- plain-language name;
- what the skill does;
- when it is useful;
- what it adds beyond likely base-model behavior;
- overlap with other installed skills;
- discovery and invocation size (from inventory, labeled estimates);
- observed usage with confidence (never equate not-observed with
  unused);
- source and freshness (provenance level, source commit date);
- known risks or compatibility concerns;
- your recommendation with a short reason.

## Decisions → profile states

| Decision | State via `profile set` |
|---|---|
| use frequently | `enabled` |
| use occasionally | `occasional` |
| keep only in the catalog | `catalog-only` |
| exclude | `excluded` |
| undecided | `undecided` |
| compare with similar skills | stays `undecided` until the comparison is shown and another decision is taken |

Record every decision through
`profile set <skill-id> <state> [--targets ...]` — never edit the YAML
silently during a questionnaire session.
