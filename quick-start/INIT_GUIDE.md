# Repomix — Universal initialization guide for AI agents

> **Purpose:** This document is an instruction set for an AI agent. Read it and follow the steps to integrate Repomix into any user project quickly.
>
> **What Repomix does:** packs a codebase into a single XML/Markdown file optimized for LLMs. The agent gets a full project map in one `view_file` instead of scanning hundreds of files individually — saving tokens and time.

---

## Phase 0: pre-analysis

Before initialization, **ask the user clarifying questions** (skip what's obvious from the project structure):

### Mandatory questions
1. **Project type?** (frontend / backend / fullstack / monorepo / non-code knowledge base)
2. **Stack?** (languages, frameworks — drives include patterns)
3. **Is there Git?** (drives git hook vs standalone script)
4. **Any legacy / archive folders** to exclude from the main index?
5. **Priority: token economy or completeness?**
   - Maximum economy → `compress: true`, `removeComments: true`, `removeEmptyLines: true`
   - Completeness (need comments for context) → `compress: false`, `removeComments: false`

### Automated analysis (do it yourself)
```bash
# Project structure
find . -maxdepth 3 -type d ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/target/*' ! -path '*/dist/*' ! -path '*/__pycache__/*' ! -path '*/venv/*' | sort

# File counts by type
find . -type f ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/target/*' ! -path '*/dist/*' | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -20

# Is this a Git repo
git rev-parse --is-inside-work-tree 2>/dev/null && echo "GIT: YES" || echo "GIT: NO"

# Husky / git hooks
ls -la .husky/ 2>/dev/null || ls -la .git/hooks/ 2>/dev/null

# AGENTS.md presence
test -f AGENTS.md && echo "AGENTS.md: EXISTS" || echo "AGENTS.md: MISSING"

# Source size (excluding binaries)
find . -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' -o -name '*.py' -o -name '*.rs' -o -name '*.go' -o -name '*.java' -o -name '*.kt' -o -name '*.swift' -o -name '*.css' -o -name '*.html' -o -name '*.md' -o -name '*.sql' -o -name '*.sh' -o -name '*.yml' -o -name '*.yaml' -o -name '*.toml' -o -name '*.json' \) ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/target/*' ! -path '*/dist/*' | wc -l
```

---

## Phase 1: install

### Check presence
```bash
command -v repomix && repomix --version
```

### Install globally (if missing)
```bash
npm install -g repomix
```

> Alternative without global install: `npx repomix` (downloads each time).

---

## Phase 2: configure

Create `repomix.config.json` at the project root using the template below. Adapt `include` and `ignore.customPatterns` to the stack.

### Base template
```json
{
  "$schema": "https://repomix.com/schemas/latest/schema.json",
  "output": {
    "filePath": ".repomix/output.xml",
    "style": "xml",
    "compress": true,
    "removeComments": true,
    "removeEmptyLines": true,
    "showLineNumbers": false,
    "fileSummary": true,
    "directoryStructure": true,
    "topFilesLength": 10,
    "headerText": "<PROJECT_NAME> — <SHORT_DESCRIPTION>. See AGENTS.md for architecture.",
    "git": {
      "sortByChanges": true,
      "sortByChangesMaxCommits": 50
    }
  },
  "include": [],
  "ignore": {
    "useGitignore": true,
    "useDefaultPatterns": true,
    "customPatterns": []
  },
  "security": {
    "enableSecurityCheck": true
  },
  "tokenCount": {
    "encoding": "o200k_base"
  }
}
```

### Include patterns by stack

#### Frontend (React / Vue / Angular / Svelte)
```json
"include": [
  "src/**/*.ts", "src/**/*.tsx", "src/**/*.js", "src/**/*.jsx",
  "src/**/*.vue", "src/**/*.svelte",
  "src/**/*.css", "src/**/*.scss", "src/**/*.less",
  "*.json", "*.html", "*.md",
  "vite.config.*", "next.config.*", "nuxt.config.*",
  "tsconfig*.json", "tailwind.config.*"
]
```

#### Backend Node.js / Bun / Deno
```json
"include": [
  "src/**/*.ts", "src/**/*.js", "src/**/*.mts",
  "*.json", "*.md", "*.yml", "*.yaml",
  "Dockerfile", "docker-compose*.yml",
  "prisma/**/*.prisma", "drizzle/**/*.ts"
]
```

#### Backend Rust
```json
"include": [
  "**/*.rs", "**/*.toml", "**/*.sql",
  "*.md", "Dockerfile",
  "migrations/**/*.sql"
]
```

#### Backend Python (Django / FastAPI / Flask)
```json
"include": [
  "**/*.py", "**/*.pyi",
  "*.md", "*.yml", "*.yaml", "*.toml", "*.cfg", "*.ini",
  "requirements*.txt", "pyproject.toml", "Pipfile",
  "Dockerfile", "docker-compose*.yml",
  "alembic/**/*.py", "migrations/**/*.py"
]
```

#### Backend Go
```json
"include": [
  "**/*.go", "go.mod", "go.sum",
  "**/*.sql", "*.md", "*.yml", "*.yaml",
  "Dockerfile", "Makefile"
]
```

#### Fullstack / Monorepo
Combine patterns from several stacks. Recommend that the user exclude legacy / archive folders.

#### Non-code knowledge base (marketing, strategy, documentation)
```json
"include": [
  "**/*.md", "**/*.txt", "**/*.csv", "**/*.json", "**/*.yml", "**/*.yaml"
]
```
> Repomix does NOT parse binary formats (docx, pdf, pptx, images, video). Convert them to Markdown before indexing — see "Knowledge Base projects" below.

### Universal ignore patterns (always add)
```json
"customPatterns": [
  "**/node_modules/**", "**/target/**", "**/dist/**",
  "**/__pycache__/**", "**/venv/**", "**/.venv/**",
  "**/coverage/**", "**/test-results/**",
  "**/.git/**", "**/.idea/**", "**/.vscode/**",
  "**/.proxyai/**", "**/.qoder/**", "**/.kiro/**",

  "pnpm-lock.yaml", "package-lock.json", "yarn.lock",
  "Cargo.lock", "bun.lockb", "poetry.lock", "Pipfile.lock",

  "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp",
  "**/*.gif", "**/*.svg", "**/*.ico",
  "**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.eot",
  "**/*.mp3", "**/*.wav", "**/*.mp4", "**/*.webm",
  "**/*.zip", "**/*.tar.gz", "**/*.rar",
  "**/*.pdf", "**/*.docx", "**/*.pptx", "**/*.xlsx",

  ".repomix/**"
]
```

---

## Phase 3: infrastructure

### Create the output folder
```bash
mkdir -p .repomix
```

### Add to .gitignore (if Git is in use)
```
# Repomix (AI context index, regenerated locally)
.repomix/
```

---

## Phase 4: first generation and assessment

```bash
repomix
```

Inspect the output:
- **Total Files** — how many files entered the index
- **Total Tokens** — token budget (benchmarks below)
- **Security** — if secrets are detected, warn the user

### Size benchmarks
| Tokens | Verdict | Action |
|--------|---------|--------|
| < 100K | Excellent | No changes |
| 100K–500K | Normal | Optimization optional |
| 500K–1M | Heavy | Recommend `compress`, drop docs/tests |
| > 1M | Too heavy | Split into per-subsystem profiles |

### If the index is too big — strategies for shrinking
1. **Enable `compress`** (Tree-sitter): cuts 50–70%
2. **`removeComments`**: another -10–20%
3. **`removeEmptyLines`**: another -5–10%
4. **Exclude tests:** `"**/*.test.*"`, `"**/*.spec.*"`, `"**/tests/**"`, `"**/__tests__/**"`
5. **Exclude docs:** `"docs/**"` if documentation is large
6. **Profiles** (see Phase 6)

---

## Phase 5: auto-update

### Option A: Git project with Husky

Create `.husky/post-commit`:
```bash
#!/bin/sh

# Regenerate Repomix context index (background, non-blocking)
if command -v repomix > /dev/null 2>&1; then
  echo "📦 Repomix: updating context index..."
  repomix --quiet 2>/dev/null &
fi
```

```bash
chmod +x .husky/post-commit
```

> If `.husky/post-commit` already exists — append the repomix block; do not replace existing hooks.

### Option B: Git project without Husky

Create `.git/hooks/post-commit`:
```bash
#!/bin/sh
if command -v repomix > /dev/null 2>&1; then
  repomix --quiet 2>/dev/null &
fi
```

```bash
chmod +x .git/hooks/post-commit
```

### Option C: project without Git

Create a reindex script at the project root:

**Linux/macOS** — `reindex.sh`:
```bash
#!/bin/bash
echo "📦 Regenerating Repomix index..."
cd "$(dirname "$0")"
if command -v repomix > /dev/null 2>&1; then
  repomix
  echo "✅ Index updated: .repomix/output.xml"
else
  echo "❌ Repomix not found. Install: npm install -g repomix"
  exit 1
fi
```

**Windows** — `reindex.bat`:
```batch
@echo off
echo 📦 Regenerating Repomix index...
cd /d "%~dp0"
where repomix >nul 2>nul
if %errorlevel% equ 0 (
    repomix
    echo ✅ Index updated: .repomix\output.xml
) else (
    echo ❌ Repomix not found. Install: npm install -g repomix
    exit /b 1
)
```

```bash
chmod +x reindex.sh  # Linux/macOS only
```

---

## Phase 6: profiles (optional)

For large projects — separate configs per subsystem:

```bash
# Backend only
repomix --include "server/**" -o .repomix/backend.xml

# Frontend only
repomix --include "frontend/**" -o .repomix/frontend.xml

# Infra only
repomix --include "start/**" --include "configs/**" --include "Dockerfile" --include "docker-compose*" -o .repomix/infra.xml
```

The agent picks the right profile per task.

---

## Phase 7: update AGENTS.md

Add this section to the project's `AGENTS.md` (adapt to the project):

```markdown
## Context Engineering: Repomix

### Project Context Index
- **File:** `.repomix/output.xml` — compressed, token-optimized snapshot of the codebase (~XXXK tokens)
- **Config:** `repomix.config.json` — include/exclude patterns, compression settings
- **Auto-update:** Regenerated on every `git commit` via post-commit hook
- **Manual update:** Run `repomix` in project root

### When to Use the Index
- **DO read `.repomix/output.xml`** before large tasks, architecture decisions, or when you need a full project overview
- **DO NOT** rely on it for precise line-level editing — always read specific files directly before modifying them
- The index is compressed (Tree-sitter structural extraction), so it preserves code semantics but not formatting

### What's Included
- <list included directories/patterns>

### What's Excluded
- <list excluded directories and why>
```

---

## Initialization checklist (quick reference)

```
[ ] repomix installed globally (npm install -g repomix)
[ ] repomix.config.json created at root with adapted include/ignore
[ ] .repomix/ added to .gitignore
[ ] First generation done; size assessed
[ ] Auto-update set up (git hook / script)
[ ] AGENTS.md updated with the Context Engineering section
```

---

## Knowledge Base projects (non-code)

Repomix only handles **text** formats. For projects with binary documents (docx, pdf, pptx, images, video) use the **"Markdown-First Knowledge Base"** strategy:

### Layout
```
project/
├── AGENTS.md                  # Main AI context
├── repomix.config.json
├── .repomix/output.xml        # Index
│
├── strategy/                  # Strategy and plans
│   ├── vision.md
│   ├── okrs-q2-2026.md
│   └── competitive-analysis.md
│
├── marketing/                 # Marketing
│   ├── brand-guidelines.md
│   ├── campaigns/
│   │   ├── launch-campaign.md
│   │   └── retention-plan.md
│   └── metrics/
│       └── kpi-dashboard.md
│
├── research/                  # Research
│   ├── user-interviews.md
│   ├── market-sizing.md
│   └── competitor-matrix.md
│
├── assets/                    # Binary originals (excluded from index)
│   ├── presentations/         # .pptx
│   ├── documents/             # .docx, .pdf
│   └── media/                 # Images, video
│
└── assets-index/              # Descriptions of binary files (included in index)
    ├── presentations.md       # Brief content of each presentation
    ├── documents.md           # Brief content of each document
    └── media.md               # Descriptions of images and videos
```

### Rules
1. The main content always lives in `.md` files
2. Binary originals live in `assets/` and are excluded from repomix
3. For each binary file write a description in `assets-index/*.md`
4. The AI converts docx/pdf → md at intake (manual or automatic)

### Converting binaries to Markdown
```bash
# DOCX → Markdown (pandoc)
pandoc document.docx -t markdown -o document.md

# PDF → Markdown (marker — AI-based, high quality)
pip install marker-pdf
marker_single input.pdf output/

# PDF → text (simple fallback)
pdftotext input.pdf output.txt
```

### Include for knowledge bases
```json
"include": ["**/*.md", "**/*.txt", "**/*.csv", "**/*.json", "**/*.yml"]
```

### Size guidance
KB projects are usually more compact than code. For them, `compress: false` is often preferable — it preserves full text structure, which matters more for strategy documents than for code.
