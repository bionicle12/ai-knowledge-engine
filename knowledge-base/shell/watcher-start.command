#!/usr/bin/env bash
# watcher-start.command — double-click launcher for the file watcher (macOS).
#
# On macOS this opens a Terminal window automatically thanks to the
# .command extension. On Linux it works the same as a .sh file.
# On Windows, use watcher-start.bat instead.
#
# Behavior:
#   - Starts kb_watch.py (via shell/watcher.sh) in the foreground inside
#     this terminal window; shell/watcher.sh picks the Python interpreter
#   - Ctrl+C to stop
#   - Window auto-closes when the watcher exits cleanly

set -uo pipefail

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
  read -r -p "Press Enter to close..." || true
  exit 1
fi

cd "$PROJECT_ROOT" || exit 1

# Older bases keep their venv in venv/, which these launchers used to
# activate. shell/_kbpy.sh does not look there: use it where _kbpy.sh would
# otherwise fall back to python3 (no .venv here, and no project .venv next
# to setup/ while the base is still being deployed).
if [ -z "${KB_PYTHON:-}" ] && [ -x venv/bin/python ] && [ ! -x .venv/bin/python ] \
    && ! { [ -f ../setup/scripts/kb_common.py ] && [ -x ../.venv/bin/python ]; }; then
  export KB_PYTHON="$PROJECT_ROOT/venv/bin/python"
fi

# `clear` fails when there is no TERM (double-clicked from a non-tty context).
clear 2>/dev/null || true
echo "👁  Knowledge-base watcher"
echo "    project: $PROJECT_ROOT"
echo "    Ctrl+C  to stop"
echo "    --------------------------------------"
echo ""

if [ ! -f "shell/watcher.sh" ]; then
  echo "❌ shell/watcher.sh not found in $PROJECT_ROOT"
  echo ""
  read -r -p "Press Enter to close..." || true
  exit 1
fi

bash shell/watcher.sh "$@"
code=$?
if [ "$code" != "0" ] && [ "$code" != "130" ]; then
  echo ""
  echo "Watcher stopped with exit $code — see the messages above."
  read -r -p "Press Enter to close..." || true
fi
exit "$code"
