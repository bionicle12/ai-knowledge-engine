#!/usr/bin/env bash
# reindex.command — double-click launcher to run a manual reindex (macOS).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

clear
echo "🔄 Manual reindex"
echo "    project: $SCRIPT_DIR"
echo "    --------------------------------------"
echo ""

if [ -f "shell/reindex.sh" ]; then
  bash shell/reindex.sh
elif [ -f "reindex.sh" ]; then
  bash reindex.sh
else
  echo "❌ reindex.sh not found"
fi

echo ""
read -r -p "Press Enter to close..."
