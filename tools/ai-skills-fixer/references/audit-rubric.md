# Prompt-debt classification rubric (spec §11)

The audit produces evidence and recommendations, never an automatic
verdict. Deterministic detectors (the `audit` command) flag candidates;
you classify each meaningful instruction into exactly one class and
justify it.

## Classes (§11.2)

| Class | Meaning | Typical action |
|---|---|---|
| `invariant` | Information the model cannot infer (org facts, paths, contracts) | keep |
| `safety-boundary` | Permission or destructive-action constraint | keep, never weaken |
| `output-contract` | Externally required format or artifact | keep |
| `domain-knowledge` | Narrow or org-specific knowledge | keep if current |
| `workflow-value` | Repeatable process that changes execution | keep if evidence supports it |
| `trained-default` | Generic behavior current models already provide | removal candidate |
| `relic` | Workaround for an older model or non-reproducing failure | removal candidate |
| `conditional-rule` | Useful rule stated too absolutely | rewrite as conditional |
| `duplicate` | Repeated locally or on another instruction surface | deduplicate |
| `conflict` | Incompatible with another active instruction | resolve explicitly |
| `process-overconstraint` | Steps prescribed without evidence they help | simplify candidate |
| `deterministic-candidate` | Should be code or validation, not prose | extract to script |
| `model-specific` | Valid only for a documented model family/version | gate on guidance cache |

Rules that bind you:

- Security, permission, business, and required-output constraints do
  NOT become removal candidates merely because they rarely trigger.
- `trained-default` and `relic` claims about the current model require
  a fresh entry in the model-guidance cache (see
  [model-guidance.md](model-guidance.md)); without one, mark the class
  as suspected and do not recommend removal.
- Detector signals (`absolute-rule`, `generic-prompting`,
  `model-reference`, `duplicate-paragraph`) are hints with false
  positives; always read the surrounding text before classifying.

## Recommendation states (§11.3)

keep · keep but disable implicit invocation · refactor in place
upstream · update from upstream · replace with maintained equivalent ·
catalog-only · disable · quarantine for security review · create local
adaptation · manual review required.

Never blend usage confidence, quality risk, security risk, overlap,
freshness, and evaluation benefit into one score — report them as
separate fields.

## Local adaptation gates (§12)

Propose a local adaptation ONLY when all six hold:

1. the skill serves a current frequent/occasional/protected need;
2. upstream is materially stale, abandoned, or incompatible;
3. the defect is supported by an audit or reproducible failure;
4. updating upstream or a maintained alternative is impractical;
5. disabling would remove needed unique value;
6. the source license allows adaptation.

Decision order: keep upstream → update upstream → replace with
maintained equivalent → disable if not needed → local adaptation last.
