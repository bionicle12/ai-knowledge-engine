#!/usr/bin/env bash
# watcher-stop.command — double-click launcher to stop a daemonized watcher (macOS).
# Works from shell/ and from the base root (where finalize.sh promotes it).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/shell/watcher.sh" ]; then
  PROJECT_ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../shell/watcher.sh" ]; then
  PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "❌ Cannot find shell/watcher.sh near this launcher."
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

echo "🛑 Stopping knowledge-base watcher..."
bash shell/watcher.sh --stop
code=$?
echo ""
read -r -p "Press Enter to close..." || true
exit "$code"
