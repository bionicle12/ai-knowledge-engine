#!/usr/bin/env bash
# install.sh — flatten the knowledge-base/ payload into the project root.
#
# Usage:
#   1. cd <your-project-root>
#   2. cp -r path/to/ai-knowledge-engine/knowledge-base ./setup
#   3. bash setup/shell/install.sh
#
# What it does (idempotent):
#   - Moves setup/scripts/, setup/shell/, setup/templates/, setup/examples/
#     and setup/*.md modules into the current directory
#   - Removes the now-empty setup/ folder
#   - Creates the directory layout via kb_ingest.py --init-dirs
#   - Reminds the user about the next step (parameterize kb.config.yml etc.)
#
# Safe to re-run: skips files that already exist at the destination.

set -euo pipefail

# Resolve where this script was launched from.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETUP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$SETUP_DIR/.." && pwd)"

echo "🛠  install.sh"
echo "   setup dir:    $SETUP_DIR"
echo "   project root: $PROJECT_ROOT"

if [ "$SETUP_DIR" = "$PROJECT_ROOT" ]; then
  echo "❌ Refusing to install: setup dir == project root."
  echo "   This script is meant to flatten setup/ into its parent."
  exit 1
fi

# Move payload (one entry at a time so we can skip conflicts safely)
moved=0
skipped=0

# Top-level directories
for dir in scripts shell templates examples; do
  if [ -d "$SETUP_DIR/$dir" ]; then
    if [ -e "$PROJECT_ROOT/$dir" ]; then
      echo "⏭  skip $dir (already exists at project root)"
      skipped=$((skipped + 1))
    else
      mv "$SETUP_DIR/$dir" "$PROJECT_ROOT/$dir"
      echo "✅ moved $dir/"
      moved=$((moved + 1))
    fi
  fi
done

# Top-level markdown modules + README + INIT_GUIDE-style files
for f in "$SETUP_DIR"/*.md; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  if [ -e "$PROJECT_ROOT/$base" ]; then
    echo "⏭  skip $base (already exists)"
    skipped=$((skipped + 1))
  else
    mv "$f" "$PROJECT_ROOT/$base"
    echo "✅ moved $base"
    moved=$((moved + 1))
  fi
done

# Clean up setup/ if it's now empty (or only contains hidden files we created)
if [ -d "$SETUP_DIR" ]; then
  remaining=$(find "$SETUP_DIR" -mindepth 1 -not -name '.*' | wc -l | tr -d ' ')
  if [ "$remaining" = "0" ]; then
    rm -rf "$SETUP_DIR"
    echo "🧹 removed empty setup/"
  else
    echo "⚠️  setup/ has $remaining leftover entries — review and remove manually:"
    find "$SETUP_DIR" -mindepth 1 -maxdepth 2 | sed 's/^/     /'
  fi
fi

echo ""
echo "Summary: moved $moved, skipped $skipped"
echo ""

# Bootstrap directory layout via kb_ingest --init-dirs
if [ -f "$PROJECT_ROOT/scripts/kb_ingest.py" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
  elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON="$PROJECT_ROOT/.venv/bin/python"
  else
    PYTHON=""
  fi
  if [ -n "$PYTHON" ]; then
    echo "📁 Creating directory layout (kb_ingest.py --init-dirs)..."
    cd "$PROJECT_ROOT" && "$PYTHON" scripts/kb_ingest.py --init-dirs
  else
    echo "ℹ️  Run later: python3 scripts/kb_ingest.py --init-dirs"
  fi
fi

# Make shell scripts executable
chmod +x "$PROJECT_ROOT"/*.sh 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/*.command 2>/dev/null || true
chmod +x "$PROJECT_ROOT"/shell/*.sh 2>/dev/null || true

cat <<'EONOTE'

✅ Installation complete.

Next steps for the AI agent:
  1. Read 00_OVERVIEW.md — the deployment map
  2. Walk through 01_PREREQUISITES.md → ... → 14_INITIAL_POPULATION.md
  3. Parameterize kb.config.yml from templates/kb.config.yml.template
  4. Generate AGENTS.md, KNOWLEDGE_STRUCTURE.md, DATA_PLACEMENT_EXAMPLES.md
  5. Run scripts/kb_doctor.py to verify

Next steps for the user (after the agent finishes):
  1. Read START_HERE.md (auto-generated at the end of deployment)
  2. Drop a file or two into raw/<sub>/unsorted/
  3. Double-click watcher-start.command (macOS) or run ./watcher.sh

EONOTE
