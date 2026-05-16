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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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
echo "    project: $SCRIPT_DIR"
echo "    Ctrl+C  to stop"
echo "    --------------------------------------"
echo ""

if [ -f "shell/watcher.sh" ]; then
  bash shell/watcher.sh
elif [ -f "watcher.sh" ]; then
  bash watcher.sh
else
  echo "❌ watcher.sh not found in $SCRIPT_DIR"
  echo ""
  read -r -p "Press Enter to close..."
  exit 1
fi
