# 05 — Indexing and Repomix

> Configure the Repomix index: what is indexed, what is excluded, how it auto-updates.
>
> **Reference template:** `knowledge-base/templates/repomix.config.json.template`. The agent copies it to the deployed base root as `repomix.config.json` and parameterizes if needed.
> **Reference shell script:** `knowledge-base/shell/reindex.sh` is copied as `reindex.sh` to the base root.

---

## Principle: clean data only

The Repomix index contains **only**:
- `knowledge/**/*.md` — extracted knowledge
- `assets-index/**/*.md` — descriptions of binary files
- Meta files: `AGENTS.md`, `README.md`, `KNOWLEDGE_STRUCTURE.md`, `kb.config.yml`

**Not indexed:** `raw/`, `processed/`, `assets/`, `review/`, `interactions/`, `setup/`, `scripts/`.

---

## repomix.config.json

```json
{
  "$schema": "https://repomix.com/schemas/latest/schema.json",
  "output": {
    "filePath": ".repomix/output.xml",
    "style": "xml",
    "compress": false,
    "removeComments": false,
    "removeEmptyLines": false,
    "showLineNumbers": false,
    "fileSummary": true,
    "directoryStructure": true,
    "topFilesLength": 20,
    "headerText": "Local non-code knowledge base. Read AGENTS.md before use."
  },
  "include": [
    "AGENTS.md",
    "README.md",
    "KNOWLEDGE_STRUCTURE.md",
    "DATA_PLACEMENT_EXAMPLES.md",
    "kb.config.yml",
    "knowledge/**/*.md",
    "assets-index/**/*.md"
  ],
  "ignore": {
    "useGitignore": true,
    "useDefaultPatterns": true,
    "customPatterns": [
      "raw/**",
      "processed/**",
      "assets/**",
      "review/**",
      "interactions/**",
      "setup/**",
      "scripts/**",
      ".repomix/**",
      ".venv/**",
      "__pycache__/**",
      "log.md",
      "log-archive/**",
      "lint-report.md",
      "**/*.pdf", "**/*.docx", "**/*.pptx", "**/*.xlsx",
      "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp", "**/*.gif",
      "**/*.mp3", "**/*.wav", "**/*.mp4", "**/*.mov",
      "**/*.zip", "**/*.tar.gz", "**/*.rar"
    ]
  },
  "security": {
    "enableSecurityCheck": true
  },
  "tokenCount": {
    "encoding": "o200k_base"
  }
}
```

`compress: false` — for textual knowledge, exact wording and nuance matter.

---

## reindex.sh

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

PYTHON="python3"
if [ -f ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
fi

echo "Running ingest pipeline..."
$PYTHON scripts/kb_ingest.py

echo "Quick lint..."
$PYTHON scripts/kb_lint.py --quick || true

echo "Generating Repomix index..."
repomix

# Append to log
echo "" >> log.md
echo "## [$(date -Iseconds)] reindex | Auto reindex" >> log.md
echo "- Output: .repomix/output.xml" >> log.md

echo "Done: .repomix/output.xml"
```

```bash
chmod +x reindex.sh
```

---

## Git hooks and auto-run

See `13_AUTORUN.md` for the full automation setup:
- File watcher (watchdog daemon)
- Git hooks (post-commit, pre-commit)
- Cron (periodic lint + reindex)

---

## Cross-references: the `[[wikilinks]]` convention

Files in `knowledge/` cross-reference each other via wikilinks:

```markdown
# Example in knowledge/domain/caching.md
We use [[DragonflyDB]] as a Redis-compatible cache (see [[infrastructure-decisions]]).
We dropped [[NATS]] in favor of Redis pub/sub (see [[decisions/2026-03__no-nats]]).
```

### Link formats

| Format | Resolves to |
|--------|-------------|
| `[[slug]]` | Search for `slug.md` in any `knowledge/` subfolder |
| `[[domain/caching]]` | Exact path: `knowledge/domain/caching.md` |
| `[[decisions/2026-03__no-nats]]` | Exact path: `knowledge/decisions/2026-03__no-nats.md` |

### Rules

1. Slug = filename without `.md`
2. On slug conflict (same filename in multiple folders) — use the full path
3. `kb_lint.py` validates every wikilink
4. Broken links → lint error
5. The AI agent **must** add wikilinks to related pages when creating/updating `knowledge/` files

### Optional automation

A Python helper can suggest wikilinks:
```python
def suggest_wikilinks(text: str, knowledge_slugs: dict) -> list:
    """Find mentions of entity names from knowledge/ and suggest [[wrapping]]."""
```

---

## Routing tables: navigation for scaled bases

When `knowledge/` holds > 50 files, a flat index becomes a context dump. Routing tables provide two-level navigation.

### `knowledge/routing-table.md` (top level)

```markdown
# Routing Table

## Domains
- [[rt/infrastructure]] — Docker, Traefik, DB, caching, networking
- [[rt/game-logic]] — clicks, settlements, economy, events, corps
- [[rt/frontend]] — React, PixiJS, HUD, biomes, scenes, i18n
- [[rt/auth]] — providers, sessions, JWT, brute-force, audit
- [[rt/devops]] — CI/CD, monitoring, deployment, backups

## Meta
- [[rt/profile]] — author, expertise, preferences
- [[rt/principles]] — working principles, quality bars
- [[rt/decisions-log]] — chronology of key decisions
```

### `knowledge/routing/rt-infrastructure.md` (second level)

```markdown
# Infrastructure

## Key pages
- [[domain/docker-swarm]] — why Swarm, not K8s
- [[domain/caching]] — DragonflyDB, caching patterns
- [[domain/database]] — PostgreSQL 16, migrations, indexes

## Adjacent areas
- → [[rt/devops]] for CI/CD and monitoring
- → [[rt/auth]] for authentication infrastructure
```

### Agent navigation

1. Reads `routing-table.md` (~20 lines)
2. Picks the right topic → jumps to a routing page
3. Finds concrete pages → reads them
4. **3 hops** instead of reading the entire index

The routing table is created and maintained by the AI agent. Lint verifies that all routing-table links are valid.
