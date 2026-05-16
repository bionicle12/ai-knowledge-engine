#!/usr/bin/env bash
# reindex.command — double-click launcher to run a manual reindex (macOS).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/shell/reindex.sh" ]; then
  PROJECT_ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../shell/reindex.sh" ]; then
  PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "❌ Cannot find shell/reindex.sh near this launcher."
  echo "   Looked at:"
  echo "     $SCRIPT_DIR/shell/reindex.sh"
  echo "     $SCRIPT_DIR/../shell/reindex.sh"
  read -r -p "Press Enter to close..."
  exit 1
fi

cd "$PROJECT_ROOT"

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

clear
echo "🔄 Manual reindex"
echo "    project: $PROJECT_ROOT"
echo "    --------------------------------------"
echo ""

bash shell/reindex.sh

echo ""
read -r -p "Press Enter to close..."
