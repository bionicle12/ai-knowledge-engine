#!/usr/bin/env bash
# watcher-stop.command — double-click launcher to stop a daemonized watcher (macOS).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/shell/watcher.sh" ]; then
  PROJECT_ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../shell/watcher.sh" ]; then
  PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
elif [ -f "$SCRIPT_DIR/watcher.sh" ]; then
  PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "❌ Cannot find shell/watcher.sh near this launcher."
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

echo "🛑 Stopping knowledge-base watcher..."
bash shell/watcher.sh --stop
echo ""
read -r -p "Press Enter to close..."
