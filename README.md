<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="AI Knowledge Engine turns raw local files into structured knowledge and AI-ready context">
</p>

<p align="center">
  <a href="VERSION"><img src="https://img.shields.io/badge/version-0.10.0-62D8FF?style=flat-square" alt="Version 0.10.0"></a>
  <a href="#requirements"><img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11 or newer"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-7EE787?style=flat-square" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/storage-local%20Markdown-8A9BB5?style=flat-square" alt="Local Markdown storage">
</p>

<p align="center">
  <a href="#choose-your-path">Choose a path</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="i18n/ru/README.md">Русский</a>
</p>

AI assistants are excellent at the current conversation and unreliable at remembering the work around it. **AI Knowledge Engine** is a set of instructions, templates, and reference scripts that gives a Markdown-capable coding agent a durable local memory.

It can start as a compact codebase index or grow into a full knowledge pipeline with document conversion, provenance, NLP enrichment, review queues, health checks, and deliberate AI-assisted reflection. Your files stay in your project; there is no hosted service or database to operate.

## See the system

<p align="center">
  <img src="./assets/readme/workflow.svg" width="100%" alt="Raw files are converted and enriched locally, reviewed into linked knowledge, and packed into focused context for an AI agent">
</p>

The visual above is the actual storage model, not a conceptual cloud architecture:

- `raw/`, `processed/`, `review/`, and `interactions/` stay out of the generated AI index.
- `knowledge/` contains reviewed, reusable Markdown and is safe to index.
- `assets-index/` holds searchable descriptions while original binaries remain private.
- `.repomix/output.xml` is a rebuildable context artifact, not the source of truth.

## Choose your path

| | **Lite — codebase context** | **Full — knowledge engine** |
|---|---|---|
| Start here | [`quick-start/`](quick-start/) | [`knowledge-base/`](knowledge-base/) |
| Best for | Giving an agent a reliable project map | Building a long-lived personal or team knowledge system |
| You get | Stack-aware indexing, secret checks, token controls, optional Git hook | Raw-first ingest, NLP, provenance, review queues, reflection, linting, watchers |
| Typical setup | About 5 minutes | About 30 minutes |
| Runtime | Repomix + Node.js | Python pipeline + an indexer; Repomix is the included default |

If you only need better code context, start with Lite. Choose Full when decisions, source material, recurring work, or cross-session learning should become durable knowledge.

## Quick start

### Full mode

Copy the deployment kit into the project where the knowledge base should live:

```bash
git clone https://github.com/bionicle12/ai-knowledge-engine.git
cp -R ai-knowledge-engine/knowledge-base /path/to/your-project/setup
cd /path/to/your-project
```

Then send this to your coding agent:

```text
Read setup/README.md and setup/00_OVERVIEW.md, then deploy a
knowledge base for [your role] inside ./knowledge-base/.
When kb_doctor passes, run setup/shell/finalize.sh to flatten
the base into the project root.
```

The agent asks about your role, configures the pipeline, creates a role-specific knowledge structure, verifies it with `kb_doctor.py`, and promotes the finished system to the project root.

<details>
<summary><strong>PowerShell copy command</strong></summary>

```powershell
git clone https://github.com/bionicle12/ai-knowledge-engine.git
Copy-Item -Recurse ai-knowledge-engine\knowledge-base C:\path\to\your-project\setup
Set-Location C:\path\to\your-project
```

</details>

> [!IMPORTANT]
> In every new agent session, begin with: **“Read `AGENTS.md` and use it as the primary instruction for everything that follows.”** The knowledge base is local; the agent must be told where its operating instructions live.

### Lite mode

```bash
npm install -g repomix
cp -R ai-knowledge-engine/quick-start /path/to/your-project/docs/ai-init
```

Then tell your agent:

```text
Read docs/ai-init/INIT_GUIDE.md and set up context indexing for this project.
```

The guide has the agent inspect the stack, define safe include/exclude patterns, enable Repomix security checks, and generate the first context snapshot.

## Why it is different

### Instructions decide; scripts execute

The project ships two coordinated layers:

1. **Instruction modules** tell the agent what to ask, which choices matter, and how the system should behave.
2. **Reference implementations** handle deterministic work such as ingest, hashing, linting, scheduling, population, and upgrades.

The agent adapts the deployment to your role and project. It does not improvise core pipeline code from scratch.

### Raw first, knowledge last

Original material is preserved before interpretation. Conversion, NLP metadata, provenance, and review happen before anything becomes trusted knowledge. Complex or sensitive material can be routed to review instead of being silently indexed.

### Local work stays local

The baseline pipeline runs on local files and CPU. It does not require a separate SaaS account, database, or pipeline API key. Optional AI operations use the coding agent you already brought to the project.

### The index is replaceable

Repomix works out of the box, but indexing is an adapter boundary. The durable layer is ordinary Markdown plus explicit metadata, links, and provenance.

## How it works

```text
source material
    ↓
raw/                     immutable originals, never indexed
    ↓  kb_ingest.py
processed/               Markdown + extraction metadata, never indexed
    ↓  routing and review
knowledge/               clean linked notes, indexed
assets-index/            searchable descriptions of binary assets
    ↓  context indexer
.repomix/output.xml      rebuildable AI context
```

The pipeline adds five controls around that path:

- **Provenance** — hashes and source references trace knowledge back to its origin.
- **Review queues** — ambiguity, low-confidence conversion, and sensitive material stop for a decision.
- **Health checks** — linting finds stale pages, broken links, orphans, and structural drift.
- **Reflection** — accumulated facts can be synthesized into higher-level insights on a schedule or by command.
- **Upgrades** — `kb_upgrade.py` refreshes reference files while preserving user customizations when possible.

Read the contributor-level [architecture overview](docs/ARCHITECTURE.md) for the full deployment sequence and invariants.

## What Full mode handles

| Capability | What happens locally |
|---|---|
| Documents | PDF, DOCX, PPTX, spreadsheets, and text are converted to Markdown |
| Audio and video | Optional `faster-whisper` transcription; no system FFmpeg required for the default backend |
| Images and scans | Optional `rapidocr-onnxruntime` OCR; Tesseract remains an alternative |
| Archives | ZIP and TAR inputs are unpacked with a size safety cap and re-ingested |
| NLP | Entities, keywords, and routing hints are extracted before AI review |
| Knowledge graph | Markdown pages use `[[wikilinks]]`, routing tables, lifecycle metadata, and provenance |
| Automation | Cross-platform reindexing, watchers, health checks, and importance-based reflection triggers |
| Portability | The complete system is files and folders that can be copied, synced, versioned, or inspected directly |

## Working with the engine

These commands are messages to your AI agent, not shell commands.

| Command | Purpose | Typical AI cost |
|---|---|---:|
| `!save` | Capture decisions and insights from a productive session | ~2K tokens |
| `!reflect` | Synthesize higher-level patterns from accumulated knowledge | ~15K tokens |
| `!review` | Resolve items waiting in review queues | ~5–30K tokens |
| `!audit` | Deep review for contradictions, gaps, and merge candidates | ~50–100K tokens |
| `!populate` | Regenerate role-specific placement examples | ~50 tokens |
| `!super on/off` | Switch between Python-first and AI-first operation | 0 tokens |

### Operating modes

| Mode | Behavior | Expected active usage |
|---|---|---:|
| `default` | Python-first processing with throttled AI decisions | ~3–4K tokens/day |
| `super` | AI reasoning for surprise detection, annotations, entity resolution, and frequent review | ~50–200K+ tokens/day |

Token figures are planning estimates, not benchmarks. Actual usage depends on document size, activity, model, and agent behavior.

## Role blueprints

Full mode includes 15 starting configurations in [`knowledge-base/examples/`](knowledge-base/examples/):

| Template | Role | Focus |
|---|---|---|
| [`b2b-strategic-product-owner.yml`](knowledge-base/examples/b2b-strategic-product-owner.yml) | B2B Strategic Product Owner | SaaS strategy, roadmaps, risks, sales-ready PRDs |
| [`battle-rap-producer.yml`](knowledge-base/examples/battle-rap-producer.yml) | Battle rap producer & lyricist | Lyric craft, punchlines, vocal stacks, mixing, battle prep |
| [`content-creator.yml`](knowledge-base/examples/content-creator.yml) | Content creator | Voice, audience, formats, publishing, monetization |
| [`creative-hybrid.yml`](knowledge-base/examples/creative-hybrid.yml) | Creative Hybrid | Software, music production, indie game development |
| [`fiction-writer.yml`](knowledge-base/examples/fiction-writer.yml) | Fiction writer | Craft theory, voice studies, story development, draft critique |
| [`founder.yml`](knowledge-base/examples/founder.yml) | Startup founder | Product, investors, hiring, decisions, company building |
| [`marketing-director.yml`](knowledge-base/examples/marketing-director.yml) | Marketing Director | Strategy, brand, campaigns, audience analysis |
| [`music-video-director.yml`](knowledge-base/examples/music-video-director.yml) | Music video writer-director | Treatments, production, shot planning, edit rhythm |
| [`product-manager.yml`](knowledge-base/examples/product-manager.yml) | Product Manager | Prioritization, metrics, research, product requirements |
| [`programmer-senior.yml`](knowledge-base/examples/programmer-senior.yml) | Senior Software Engineer | Architecture, debugging, stack knowledge, engineering principles |
| [`psychologist-gestalt.yml`](knowledge-base/examples/psychologist-gestalt.yml) | Gestalt-oriented psychologist | Ethics, anonymized cases, supervision, interventions |
| [`researcher.yml`](knowledge-base/examples/researcher.yml) | Researcher / Analyst | Literature, hypotheses, evidence, methodology |
| [`russian-software-engineering-student.yml`](knowledge-base/examples/russian-software-engineering-student.yml) | Software engineering student in Russia | Coursework, labs, exams, internships |
| [`startup-opportunity-explorer.yml`](knowledge-base/examples/startup-opportunity-explorer.yml) | Startup Opportunity Explorer | Market gaps, validation, idea scoring, web-app MVPs |
| [`viral-short-form-veo.yml`](knowledge-base/examples/viral-short-form-veo.yml) | Viral short-form video director | Hooks, storyboards, Veo 3 prompt chains, ad learning |

A role file defines useful entities, folder routes, placement examples, recurring queries, and review priorities. If none fits, the deployment agent can derive a custom configuration from your work.

## Project map

```text
ai-knowledge-engine/
├── quick-start/                 Lite mode: codebase indexing guide
├── knowledge-base/
│   ├── 00_…15_*.md             16 ordered instruction modules
│   ├── scripts/                Python reference pipeline and tests
│   ├── shell/                  macOS/Linux wrappers + Windows launchers
│   ├── templates/              config, agent, structure, and dependency templates
│   └── examples/               15 role blueprints
├── scripts/                    upgrades, translation checks, repository maintenance
├── i18n/ru/                    Russian documentation and instruction set
└── docs/                       architecture, troubleshooting, upgrades, roadmap
```

## Requirements

| Component | Minimum | Needed for |
|---|---:|---|
| Python | 3.11+ | Full-mode ingest, NLP, linting, watchers, and health checks |
| Node.js | 20+ | Included Repomix indexer |
| Git | Any recent version | Versioning and optional hooks |
| AI coding agent | Markdown + file and shell access | Guided deployment and AI-assisted commands |

Core Python dependencies are listed in [`requirements.txt`](knowledge-base/templates/requirements.txt). Speech-to-text and OCR are deliberately separated into [`requirements-media.txt`](knowledge-base/templates/requirements-media.txt).

The instructions are designed for Claude, Codex, GPT, Gemini, Cursor, and other Markdown-capable agents that can inspect files and run commands. Exact behavior still depends on the host application's permissions and tool access.

## Limits and trust boundaries

- This repository is a deployment template, not a hosted application or sync service.
- The agent does not remember the knowledge base automatically; each new session must load `AGENTS.md`.
- Local-first storage protects against an external service by default, but repository permissions, backups, and model-provider data policies remain your responsibility.
- Repomix security checks reduce accidental secret inclusion; they are not a replacement for secret management or a security audit.
- AI review and reflection can be expensive in `super` mode and should be enabled deliberately.

## Documentation

| Need | Read |
|---|---|
| Understand the full deployment | [`knowledge-base/README.md`](knowledge-base/README.md) |
| See system architecture | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Fix a failed setup | [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) |
| Upgrade a deployed base | [`docs/UPGRADING.md`](docs/UPGRADING.md) |
| Maintain or contribute | [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) and [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) |
| Translate the project | [`docs/TRANSLATING.md`](docs/TRANSLATING.md) |
| Review planned work | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| Read in Russian | [`i18n/ru/README.md`](i18n/ru/README.md) |

## Development

Install the test dependencies and run the suite locally:

```bash
python -m pip install -r knowledge-base/templates/requirements-dev.txt
python -m pytest
```

On Windows, tests for POSIX launchers require a working WSL environment, and the finalize-script fixtures require permission to create symbolic links. The Python pipeline tests run natively.

Contributions are welcome, especially new role blueprints, clearer instruction modules, cross-platform fixes, translations, and pipeline tests. For substantial changes, open an issue first and follow the [contribution guide](docs/CONTRIBUTING.md).

## License

[MIT](LICENSE) — use it for personal or commercial work.

<p align="center">
  <strong>Build knowledge your agent can find, verify, and carry forward.</strong>
</p>
