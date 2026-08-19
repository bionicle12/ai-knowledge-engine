# AI Skills Fixer — Design Specification

Status: design approved in discussion; awaiting written-spec review
Date: 2026-08-19

## 1. Purpose

`ai-skills-fixer` is a repository-local, agent-operated tool for curating AI
agent skills across Linux, Windows, and macOS. It inventories installed skills,
recovers their provenance, measures their discovery and context cost, identifies
obsolete or conflicting instructions, recommends a smaller useful set, and
applies only user-approved changes.

The tool uses a hybrid architecture:

- deterministic Python code collects facts, validates files, calculates hashes,
  prepares plans, and applies exact approved changes;
- an AI agent interprets those facts, researches current model guidance, asks
  the user about ambiguous needs, and recommends semantic changes;
- YAML manifests define the desired state shared between machines;
- machine-local YAML contains only platform-specific paths and overrides.

Python must not decide whether a skill is useful or rewrite skill instructions
autonomously. The agent must not mutate installed skills without first producing
an explicit change plan and receiving approval.

## 2. Problem statement

The current machine has skills spread across many agent-specific directories.
Large subsets are copied from a shared upstream repository, while other skills
come from plugins or Git repositories connected through symlinks. This creates
several problems:

1. The same skill can exist as independent copies in several clients.
2. Copied skills lose an explicit link to their source repository and commit.
3. Updating an upstream collection does not reliably update all clients.
4. Blindly linking clients to a live upstream branch would activate unreviewed
   changes immediately.
5. A large skill inventory increases discovery metadata and can hide or
   truncate useful skill descriptions.
6. Many public skills encode generic advice already learned by newer models,
   old prompting workarounds, repeated instructions, or conflicting rules.
7. Different model families require different migration judgments. A prompt
   rule that helps one current model may waste tokens or degrade another.
8. Existing usage logs do not provide complete, uniform skill telemetry across
   all agent clients.
9. A skill that is irrelevant to the user's work should not remain active only
   because it exists in a large public catalog.

## 3. Goals

The first complete version must:

- run from the `ai-knowledge-engine` repository;
- discover skill locations without assuming one operating system or one fixed
  home-directory layout;
- support a shared base profile for Linux, Windows, and macOS, with local
  per-machine exceptions;
- store cloned repositories in a sibling `skill-repositories` directory;
- support both repositories containing one skill and repositories containing
  many skills;
- keep source repositories, selected skills, machine configuration, and the
  generated lockfile as separate concepts;
- give the user a short, useful explanation before asking whether an individual
  skill is needed;
- combine observed evidence with a short adaptive questionnaire about the
  user's work domains;
- distinguish "usage not observed" from "unused";
- audit prompt debt against current official model guidance and dated local
  research;
- preserve security, permission, business, and output-contract invariants;
- generate an exact dry-run plan before changing any installed directory;
- support backup, quarantine, and rollback;
- fetch upstream changes without activating them automatically;
- create a locally maintained adaptation only as a last resort;
- optionally compare no-skill, current-skill, and revised-skill behavior with
  isolated evaluations.

## 4. Non-goals

The initial implementation will not:

- install every skill from every registered repository;
- run expensive evaluations for the entire public catalog;
- delete skills automatically because no usage was found;
- rewrite every skill that fails a style heuristic;
- create local forks merely to normalize formatting;
- use one universal prompt-migration rule for every model family;
- scan an entire filesystem without explicit bounded roots;
- automatically create, configure, or push a remote Git repository;
- silently change plugin-managed or system-bundled skills;
- make network access, destructive operations, or model API spending implicit.

## 5. Primary design decisions

### 5.1 Repository-local control plane

The orchestration skill and deterministic tooling live in:

```text
ai-knowledge-engine/tools/ai-skills-fixer/
```

The default managed store is the sibling directory:

```text
<ai-knowledge-engine-parent>/skill-repositories/
```

For the current Linux workspace this resolves to:

```text
/home/popovalpe/www/main/skill-repositories/
```

The path is calculated from the resolved repository root, not embedded as a
constant. A command-line option and machine-local configuration may override
it.

### 5.2 Shared intent, local installation details

The logical source registry, desired skill set, and lockfile are shared across
machines. Operating-system paths, installed clients, link strategy, and
machine-specific exclusions remain local.

This produces one common skill policy without pretending that Linux, Windows,
and macOS expose the same filesystem or client capabilities.

### 5.3 Immutable active releases

Agent skill directories must not point to a mutable upstream branch. Active
skills point to an immutable release created from a pinned commit. Fetching an
upstream repository updates only the mirror/source checkout and creates an
update candidate.

Promotion to an active release requires:

```text
fetch -> diff -> static audit -> semantic audit -> optional eval -> approval -> apply
```

### 5.4 Declarative reconciliation

Users may edit YAML manually or ask an agent to edit it. The reconciler compares
the declared desired state with the actual machine state and emits a plan.

Without `--apply`, reconciliation is read-only.

### 5.5 Progressive disclosure

`SKILL.md` contains only the core workflow and routing instructions. Detailed
rubrics, host-specific knowledge, model notes, and schemas live in referenced
files. Repeated deterministic work is implemented as scripts.

## 6. Proposed repository layout

### 6.1 Tool package

```text
tools/ai-skills-fixer/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── scripts/
│   ├── ai_skills_fixer.py
│   └── ai_skills_fixer/
│       ├── cli.py
│       ├── discovery.py
│       ├── inventory.py
│       ├── provenance.py
│       ├── frontmatter.py
│       ├── linting.py
│       ├── usage.py
│       ├── sources.py
│       ├── releases.py
│       ├── planner.py
│       ├── installer.py
│       ├── rollback.py
│       └── doctor.py
├── references/
│   ├── audit-rubric.md
│   ├── questionnaire.md
│   ├── provenance.md
│   ├── evaluation.md
│   ├── model-guidance.md
│   └── hosts/
│       ├── codex.md
│       ├── claude-code.md
│       ├── cursor.md
│       └── generic-agent-skills.md
├── schemas/
│   ├── repositories.schema.json
│   ├── profile.schema.json
│   ├── machine.schema.json
│   ├── lock.schema.json
│   ├── inventory.schema.json
│   └── change-plan.schema.json
├── assets/
│   └── templates/
│       ├── repositories.yml
│       ├── profile.yml
│       └── machine.local.yml
├── evals/
│   ├── cases/
│   └── rubrics/
└── tests/
```

No auxiliary README is required inside the skill package. `SKILL.md` is the
agent entry point; project documentation remains under `docs/`.

### 6.2 Managed skill store

```text
skill-repositories/
├── registry/
│   ├── repositories.yml
│   └── skills.lock.yml
├── profiles/
│   └── default.yml
├── machines/
│   └── <machine-id>.local.yml
├── sources/
├── releases/
├── local/
└── state/
    ├── inventories/
    ├── plans/
    ├── reports/
    ├── backups/
    └── evaluations/
```

The store may itself be initialized as a private Git repository for syncing
`registry/` and `profiles/`. The tool must not initialize or push that Git
repository without an explicit user request.

Recommended ignored paths are:

```text
sources/
releases/
state/
machines/*.local.yml
```

## 7. Configuration model

### 7.1 Source registry

`registry/repositories.yml` declares where skills can be obtained. It does not
select which skills are active.

Collection example:

```yaml
schema_version: 1

repositories:
  antigravity-awesome:
    url: https://github.com/sickn33/antigravity-awesome-skills.git
    ref: v7.3.0
    layout:
      type: collection
      roots:
        - skills
```

Single-skill example:

```yaml
  my-single-skill:
    url: https://github.com/example/my-skill.git
    ref: main
    layout:
      type: single
      skill_path: .
```

A collection may declare several roots. Discovery must still validate that a
candidate directory contains a readable `SKILL.md` rather than trusting the
layout declaration blindly.

### 7.2 Shared profile

`profiles/default.yml` declares the desired logical set:

```yaml
schema_version: 1

skills:
  - id: antigravity-awesome:backend-architect
    state: enabled
    targets: [codex, claude, cursor]

  - id: antigravity-awesome:postgresql-optimization
    state: occasional
    targets: [codex, claude]

  - id: antigravity-awesome:blockchain-developer
    state: excluded

  - id: superpowers:systematic-debugging
    state: protected
    targets: [codex, claude]
```

Supported logical states are:

- `enabled`: make the skill available on the named targets;
- `occasional`: retain it for explicit or low-noise use when the host supports
  that behavior;
- `catalog-only`: fetch and index it but do not expose it to agents;
- `excluded`: explicitly outside the user's needs;
- `undecided`: requires profile review;
- `protected`: do not disable automatically.

### 7.3 Machine-local configuration

`machines/<machine-id>.local.yml` contains runtime details only:

```yaml
schema_version: 1
machine_id: linux-desktop
store_root: auto

agents:
  codex:
    enabled: true
    install_path: auto
    strategy: auto

  claude:
    enabled: true
    install_path: auto
    strategy: auto

profile_overrides:
  disable: []
  additional_targets: {}
```

Machine overrides may remove a skill from a device or change its targets, but
they do not silently edit the shared base profile.

### 7.4 Generated lockfile

`registry/skills.lock.yml` is generated and should not be hand-edited. For each
selected skill it records:

- source ID and URL;
- requested ref;
- resolved commit;
- skill path within the repository;
- content hash;
- discovered skill name and description;
- release path identifier;
- audit status and audit timestamp;
- tested model profiles when available.

Changing a requested ref does not update the lockfile until the candidate has
been resolved and approved.

`source refresh` only fetches metadata and prepares an update candidate. When a
requested ref changes, `reconcile` includes the resulting lockfile and release
changes in its dry-run plan; only applying that exact approved plan promotes the
candidate.

## 8. Cross-platform host discovery

Each host adapter implements the same interface:

```text
detect() -> host installation candidates
discover_roots() -> skill discovery roots with evidence
inspect_capabilities() -> supported installation strategies
inventory() -> effective installed skills
plan_install() -> non-mutating proposed action
validate_install() -> post-apply discovery check
```

Discovery order:

1. Detect operating system and home directory using runtime APIs.
2. Inspect relevant environment overrides.
3. Inspect existing client configuration when its format is documented.
4. Check documented default locations.
5. Inspect existing skill directories within bounded configured roots.
6. Assign evidence and confidence to each candidate.
7. Let the agent choose when evidence is sufficient.
8. Ask the user when multiple materially different candidates remain.

The tool must not recursively search entire disks. Default bounded roots are the
resolved home directory, the current repository, its parent, and explicitly
configured paths.

Installation strategies are capabilities rather than OS assumptions:

- symbolic link;
- Windows directory junction;
- materialized copy;
- native plugin/package installation;
- disabled configuration entry where the client supports it.

`strategy: auto` selects the safest strategy supported by both the platform and
the host adapter. The plan must show the selected strategy before application.
Post-install validation is mandatory; a filesystem operation succeeding does
not prove that a client discovered the skill.

## 9. Inventory and provenance

Inventory records the physical and effective state separately.

Physical facts include:

- directory and real path;
- file type: directory, symlink, junction, or materialized copy;
- hash of the complete skill artifact;
- `SKILL.md` metadata and size;
- bundled scripts, references, assets, and executable files;
- Git repository root, remote, commit, and dirty status when discoverable;
- matching source-repository candidates by content hash;
- broken links and missing referenced files.

Effective host facts include:

- discovery root and precedence;
- duplicate names visible to one host;
- plugin namespace, if any;
- enabled or disabled state;
- whether the host may truncate or omit metadata;
- whether implicit invocation can be disabled;
- validation confidence.

Provenance confidence levels:

- `exact`: content hash and path match a known source commit;
- `probable`: content matches a known skill but the source commit is unresolved;
- `modified-copy`: a known source is strongly indicated but content differs;
- `declared`: source is stated in metadata but not independently verified;
- `unknown`: no defensible source was found.

The tool must never rewrite unknown provenance as a fact.

## 10. Adaptive user profile and skill questionnaire

The profile workflow combines detected evidence with user answers. It may
inspect only repositories or workspace roots the user has placed in scope.

Initial categories include:

- frontend, backend, mobile, desktop, embedded;
- databases, analytics, machine learning, data engineering;
- cloud, containers, CI/CD, observability;
- architecture, testing, debugging, code review, security;
- documentation, scientific writing, UI/UX, SEO, marketing, payments,
  messaging, and blockchain.

Answers use a small stable scale:

- frequent;
- occasional;
- interested;
- excluded;
- unsure.

The questionnaire must be adaptive:

1. Infer likely categories from configured project roots.
2. Ask category-level questions before skill-level questions.
3. Skip individual questions for explicitly excluded categories.
4. Group remaining skills in batches of five to ten.
5. Prioritize duplicates, expensive metadata, ambiguous usage, and high-risk
   skills.

Before asking whether an individual skill is needed, show a decision card:

- plain-language name;
- what the skill does;
- when it is useful;
- what it adds beyond likely base-model behavior;
- overlap with other installed skills;
- discovery and invocation size;
- observed usage with confidence;
- source and freshness;
- known risks or compatibility concerns;
- recommendation with a short reason.

The available decisions are:

- use frequently;
- use occasionally;
- keep only in the catalog;
- exclude;
- compare with similar skills;
- undecided.

## 11. Skill audit model

The audit produces evidence and recommendations, not an automatic verdict.

### 11.1 Structural checks

- readable and valid frontmatter;
- portable `name` and `description`;
- name/folder consistency;
- description specificity and trigger boundaries;
- body length and progressive disclosure;
- referenced files exist;
- scripts declare prerequisites and use relative paths safely;
- host-specific fields are separated from portable core instructions.

### 11.2 Prompt-debt classification

Each meaningful instruction may be classified as:

- `invariant`: information or constraint the model cannot infer;
- `safety-boundary`: permission or destructive-action constraint;
- `output-contract`: externally required format or artifact contract;
- `domain-knowledge`: narrow or organization-specific information;
- `workflow-value`: a repeatable process that changes task execution;
- `trained-default`: generic behavior the current model reliably provides;
- `relic`: workaround for an older model or a non-reproducing failure;
- `conditional-rule`: useful rule stated too absolutely;
- `duplicate`: repeated locally or in another instruction surface;
- `conflict`: incompatible with another active instruction;
- `process-overconstraint`: prescribes steps without evidence that they help;
- `deterministic-candidate`: should be implemented as code or validation;
- `model-specific`: valid only for a documented model family or version.

Security, permission, business, and required output constraints do not become
removal candidates merely because they rarely trigger.

### 11.3 Recommendation states

- keep;
- keep but disable implicit invocation;
- refactor in place upstream;
- update from upstream;
- replace with a maintained equivalent;
- catalog-only;
- disable;
- quarantine for security review;
- create local adaptation;
- manual review required.

No single blended score may hide important trade-offs. Usage confidence,
quality risk, security risk, overlap, freshness, and evaluation benefit remain
separate fields.

## 12. Local adaptation policy

A locally maintained adaptation may be created only when all of the following
are true:

1. The skill serves a current frequent, occasional, or protected user need.
2. The upstream version is materially stale, abandoned, or incompatible with
   current requirements.
3. The defect is supported by an audit or a reproducible task failure.
4. Updating upstream or using a maintained alternative is not practical.
5. Disabling the skill would remove needed unique value.
6. The source license allows adaptation.

Decision order:

```text
keep current upstream
-> update upstream
-> replace with maintained equivalent
-> disable if not needed
-> create local adaptation only if still necessary
```

Local adaptations live under `skill-repositories/local/`. Their portable
`SKILL.md` remains minimal. A sidecar metadata file records the original URL,
commit, path, license, reason for adaptation, audit findings, and validated
model profiles.

## 13. Model guidance lifecycle

Prompt audits must use dated model profiles rather than one permanent rule set.

For each active model family, the guidance cache records:

- provider and public model identifier;
- aliases observed in clients;
- official source URLs;
- retrieval date;
- summarized applicable guidance;
- important migration differences;
- unresolved or undocumented claims;
- expiration policy;
- last audit run using the profile.

Source priority:

1. Official provider documentation.
2. Official product documentation for the agent harness.
3. Current local research articles as secondary analysis.
4. External primary research where it directly supports an evaluation method.

The tool researches again when:

- a configured or observed model version changes;
- the cached profile expires;
- official guidance URLs change materially;
- a skill contains model-specific behavior not covered by the cache.

If an exact requested model version has no official documentation, its profile
is `unverified`. The agent may recommend a clean baseline evaluation but must
not invent model-specific rules.

The default migration method is incremental:

1. Run representative tasks on the new model with optional user customization
   and third-party skills disabled.
2. Establish the base behavior.
3. Enable the current skill and rerun the same tasks.
4. Remove or change one instruction group at a time.
5. Retain only measured improvements and true invariants.

## 14. Usage telemetry

Usage telemetry is advisory because host logs differ.

Evidence levels:

- `explicit`: host emitted a skill invocation event;
- `strong`: a session read the exact skill path or invoked its command name;
- `weak`: task text likely matched the description but activation is not proven;
- `manual`: user marked the skill as used or protected;
- `not-observed`: no supported evidence was found.

The tool must disclose which logs it intends to inspect and keep analysis local.
It must not upload session contents. Reports should store aggregate counts and
minimal evidence references, not user prompts or model responses unless the
user explicitly enables evaluation trace retention.

## 15. Token and performance accounting

Three costs are reported separately:

1. Discovery cost: skill name, description, and path exposed at startup.
2. Invocation cost: `SKILL.md` and references actually loaded.
3. Execution cost: input, output, reasoning, cached tokens, tool calls, retries,
   latency, and API cost when those metrics are available.

Static analysis may report exact characters, bytes, words, and model-specific
token estimates. Estimates must be labeled as such. Actual benefit is measured
through controlled A/B traces rather than inferred from file size.

## 16. Evaluation design

Evaluation is optional in the MVP and enabled first for a small set of retained,
high-value, or suspicious skills.

Each skill may have two suites:

### 16.1 Activation suite

- direct positive requests;
- indirect positive requests;
- incomplete requests;
- negative near-neighbor requests;
- ambiguous requests shared with overlapping skills.

Metrics are activation precision, activation recall, false activation rate, and
missed activation rate.

### 16.2 Task-value suite

Compare:

```text
base model without skill
vs current skill
vs proposed revised or replacement skill
```

Runs use the same model, effort, task input, allowed tools, and isolated fresh
context. Objective tests and artifact checks take priority over model judging.
Where judgment is necessary, use a blind rubric or human review.

Record:

- success rate;
- required-output completeness;
- objective test results;
- input, output, reasoning, and cached tokens where exposed;
- wall-clock time;
- tool calls and retries;
- evaluator confidence;
- model, effort, host, and harness version.

Run several repetitions for non-deterministic tasks. Lower token use counts as
an improvement only when the result continues to satisfy the acceptance bar.

## 17. Command and agent workflows

The CLI supports both manual use and agent orchestration.

Core commands:

```text
ai-skills-fixer init
ai-skills-fixer doctor
ai-skills-fixer source add <url>
ai-skills-fixer source refresh [source-id]
ai-skills-fixer catalog [source-id]
ai-skills-fixer inventory
ai-skills-fixer profile
ai-skills-fixer audit [skill-id]
ai-skills-fixer reconcile
ai-skills-fixer reconcile --apply <plan-id>
ai-skills-fixer rollback <apply-id>
ai-skills-fixer eval <skill-id>
```

`reconcile` is a dry run. Applying requires an immutable saved plan ID so the
applier cannot silently use a newly recomputed target set.

Natural-language workflow:

```text
Add repository <URL>. Inspect it, show the discovered skills with short
decision cards, and do not install anything until I choose.
```

The agent then:

1. reads the tool skill;
2. runs source discovery;
3. reviews security and provenance findings;
4. presents relevant skills;
5. records approved profile choices;
6. runs reconciliation;
7. presents the exact plan;
8. applies only after approval;
9. runs post-install validation.

## 18. Change-plan and apply safety

A change plan contains:

- plan ID and creation timestamp;
- input configuration hashes;
- exact source commits and release IDs;
- each source and destination path;
- operation type and installation strategy;
- expected precondition at the destination;
- backup action;
- validation action;
- rollback action;
- risk and approval requirement.

Before applying, the tool verifies that configuration hashes, destination
state, and source commits still match the plan. Drift invalidates the plan and
requires a new dry run.

Default removal behavior is recoverable:

- disable when the host supports it;
- unlink a managed link;
- move a copied artifact into a timestamped quarantine or backup;
- never recursively delete an unresolved broad path.

System-bundled and plugin-managed skills are reported separately. Changes to
them must go through the owning client's configuration or plugin mechanism.

## 19. Failure handling

The tool stops safely when:

- a path cannot be resolved unambiguously;
- a repository layout contains duplicate skill IDs;
- a source checkout is dirty and would be overwritten;
- the resolved commit differs from the approved plan;
- the destination contains an unrecognized local modification;
- a requested installation strategy is unsupported;
- post-install discovery fails;
- a source license is missing for a proposed adaptation;
- model guidance required for a model-specific rewrite is unverified.

Partial application is recorded operation by operation. On failure, already
completed operations are either rolled back automatically when safe or reported
with exact manual recovery steps.

## 20. Security and privacy

- Treat every third-party skill as executable supply-chain content.
- Do not execute bundled scripts during static audit.
- Scan updates before promotion.
- Pin commits and store hashes.
- Prefer offline parsing for inventories and logs.
- Do not print secrets, environment contents, or full session prompts.
- Run skill evaluations in isolated worktrees or fixtures with no production
  credentials.
- Require explicit approval for networked evaluations, API spending, external
  writes, and destructive operations.
- Preserve source licenses and attribution.

## 21. Testing strategy

### Unit tests

- path normalization on Linux, Windows, and macOS;
- environment override precedence;
- YAML and frontmatter parsing;
- source layout discovery;
- content hashing and provenance matching;
- profile overlay resolution;
- plan precondition checks;
- safe strategy selection;
- rollback record generation;
- prompt-debt rule detectors.

### Integration tests

- synthetic single-skill and collection repositories;
- pinned release creation;
- symlink, junction abstraction, and materialized-copy adapters;
- duplicate skill names across discovery roots;
- dirty and modified destinations;
- dry-run stability;
- apply followed by rollback;
- broken links and missing references;
- migration from copied skills to managed releases.

### Agent workflow tests

- source addition with no immediate installation;
- category questionnaire routing;
- concise individual skill decision cards;
- analysis separated from mutation;
- no local adaptation when update, replacement, or disable is sufficient;
- unverified model guidance produces bounded uncertainty;
- user rejection leaves installed state unchanged.

## 22. Delivery phases

### Phase 1: Read-only inventory MVP

Support Codex, Claude Code, Cursor, and Antigravity first. Deliver platform and
host discovery, inventory, provenance matching, duplicate detection, structural
lint, token-size reporting, and human-readable reports.

Completion criterion: running the tool changes no installed skill and produces
a reproducible inventory with evidence and confidence levels.

### Phase 2: Declarative store and reconciliation

Deliver store initialization, source registry, catalog discovery, shared
profile, machine-local configuration, lockfile generation, immutable releases,
and dry-run reconciliation.

Completion criterion: editing YAML produces a stable exact change plan on
Linux, Windows, and macOS fixtures.

### Phase 3: Safe apply and rollback

Deliver installation strategies, backups, quarantine, drift protection,
post-install doctor checks, and rollback.

Completion criterion: a copied skill can be migrated to a managed pinned
release and restored without data loss.

### Phase 4: Agent audit and model guidance

Deliver adaptive profile questions, decision cards, prompt-debt classification,
official guidance refresh, and the strict local-adaptation policy.

Completion criterion: the agent produces useful recommendations while leaving
all semantic changes subject to user selection.

### Phase 5: Evaluation lab

Deliver activation suites, task-value suites, isolated runs, and comparative
token, latency, and quality reports.

Completion criterion: selected high-value skills can demonstrate benefit or
harm relative to a clean baseline.

### Phase 6: Additional hosts and maintenance automation

Add adapters only for clients found in real use. Add source-update monitoring
that reports candidates without activating them.

Completion criterion: adding a host adapter does not change the portable
registry or shared profile format.

## 23. MVP acceptance criteria

The MVP is complete when all of the following are true:

1. It runs from the repository on Linux and passes Windows/macOS path fixtures.
2. It resolves the default sibling `skill-repositories` path without a hardcoded
   absolute path.
3. It inventories Codex, Claude Code, Cursor, and Antigravity locations with
   evidence and confidence.
4. It distinguishes copies, managed links, plugin skills, system skills, and
   unknown artifacts.
5. It identifies exact copies originating from a registered repository.
6. It reports duplicates and likely discovery crowding.
7. It creates and validates repository, profile, machine, inventory, lock, and
   plan YAML/JSON artifacts.
8. It provides concise skill decision cards during profile review.
9. It never equates absent telemetry with confirmed non-use.
10. `reconcile` is read-only and deterministic for unchanged inputs.
11. `reconcile --apply` accepts a saved approved plan and checks for drift.
12. Every mutating operation has a backup or explicit reversible action.
13. Upstream refresh does not change active installed skills.
14. Local adaptations cannot be proposed unless all policy gates are satisfied.
15. Tests cover path handling, planning, apply safety, and rollback.

## 24. Resolved product decisions

- The managed store is a sibling of `ai-knowledge-engine`, not a global folder
  directly under `~/www`.
- The default profile is shared across Linux, Windows, and macOS.
- Machine-local overrides handle paths, hosts, strategies, and exceptions.
- Repositories are cloned into `sources/`; registry YAML stores declarations,
  not repository contents.
- Users may edit YAML or ask the agent to do so.
- The default reconciliation command is a dry run.
- Active skills use pinned immutable releases.
- Individual skill questions always include a short decision card.
- A local refactored skill is a last resort, not a routine normalization step.
- The first implementation targets the four primary clients and expands only
  from observed need.

## 25. References used for the design

- OpenAI skill authoring and Codex discovery documentation:
  <https://learn.chatgpt.com/docs/build-skills>
- OpenAI GPT-5.6 model guidance:
  <https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6>
- Anthropic current prompting best practices:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices>
- Anthropic Claude Opus 5 prompting guidance:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5>
- Anthropic Claude Fable 5 prompting guidance:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5>
- Cursor agent best practices:
  <https://cursor.com/blog/agent-best-practices>
- xAI current model catalog:
  <https://docs.x.ai/developers/models>
- Local prompt-debt research supplied by the user:
  `/home/popovalpe/www/main/boosty/2026-08-14_80-instrukciy-v-musor-kak-teper-pishut/article.md`
