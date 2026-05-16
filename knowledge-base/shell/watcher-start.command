#!/usr/bin/env bash
# watcher-start.command — double-click launcher for the file watcher (macOS).
#
# On macOS this opens a Terminal window automatically thanks to the
# .command extension. On Linux it works the same as a .sh file.
# On Windows, use watcher-start.bat instead.
#
# Behavior:
#   - Starts kb_watch.py in the foreground inside this terminal window
#   - Ctrl+C to stop
#   - Window auto-closes when the watcher exits cleanly

set -euo pipefail

# Resolve the project root.
# This script may live either at the project root (after finalize.sh) or
# inside <root>/shell/. Detect which case applies.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/scripts/kb_watch.py" ]; then
  PROJECT_ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../scripts/kb_watch.py" ]; then
  PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "❌ Cannot find scripts/kb_watch.py anywhere near this launcher."
  echo "   Looked at:"
  echo "     $SCRIPT_DIR/scripts/kb_watch.py"
  echo "     $SCRIPT_DIR/../scripts/kb_watch.py"
  echo "   Did the agent finish the deployment?"
  echo ""
  read -r -p "Press Enter to close..."
  exit 1
fi

cd "$PROJECT_ROOT"

# Activate virtualenv if present
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

clear
echo "👁  Knowledge-base watcher"
echo "    project: $PROJECT_ROOT"
echo "    Ctrl+C  to stop"
echo "    --------------------------------------"
echo ""

if [ -f "shell/watcher.sh" ]; then
  bash shell/watcher.sh
else
  echo "❌ shell/watcher.sh not found in $PROJECT_ROOT"
  echo ""
  read -r -p "Press Enter to close..."
  exit 1
fi
