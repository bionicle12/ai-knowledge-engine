# Interpreting provenance (spec §9)

Levels, from strongest to weakest:

- `exact` — content hash and folder name match a skill in a registered
  source at its current checkout. Safe to adopt into a managed release.
- `probable` — identical content, different folder name. Confirm the
  rename with the user before adopting.
- `modified-copy` — the name matches a source skill but content
  differs. Two very different explanations: (a) the user edited a copy,
  (b) the skill comes from another ecosystem with the same name.
  Register the other ecosystem's repository as a source before
  concluding anything; diff against the source before recommending.
- `declared` — a source is stated in metadata but not independently
  verified.
- `unknown` — no defensible source. Never rewrite unknown provenance
  as a fact.

Hard rules:

- Plugin- and system-managed skills (`root_kind` of `plugin`/`system`)
  are never name-matched and are changed only through the owning
  client's own mechanism (spec §18).
- A hash mismatch against today's checkout does not mean the copy was
  edited — the source may simply have moved on. Commit history
  resolution arrives with the lockfile; until then say "differs from
  the current checkout", not "was modified".
