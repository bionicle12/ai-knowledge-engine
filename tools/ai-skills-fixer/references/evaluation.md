# Evaluation (spec §16) — post-MVP, Phase 5

Not implemented yet. When it lands, each selected skill gets two
suites:

- **Activation suite** — direct/indirect/incomplete/negative/ambiguous
  requests; metrics: activation precision and recall, false and missed
  activation rates.
- **Task-value suite** — base model vs current skill vs proposed
  revision, same model/effort/tools/fresh context; objective checks
  before model judging; several repetitions for non-deterministic
  tasks. Lower token use counts as an improvement only when the result
  still satisfies the acceptance bar.

Until Phase 5, do not claim measured benefit or harm — say the
evaluation has not been run.
