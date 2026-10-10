#!/usr/bin/env bash
# export.command — double-click launcher: pack this base into a bundle (macOS).
# Works from shell/ and from the base root (where finalize.sh promotes it).
# The Python interpreter is chosen by shell/export.sh (shell/_kbpy.sh).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/shell/export.sh" ]; then
  PROJECT_ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../shell/export.sh" ]; then
  PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "❌ Cannot find shell/export.sh near this launcher."
  echo "   Looked at:"
  echo "     $SCRIPT_DIR/shell/export.sh"
  echo "     $SCRIPT_DIR/../shell/export.sh"
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
echo "📦 Export knowledge bundle"
echo "    project: $PROJECT_ROOT"
echo "    --------------------------------------"
echo ""

bash shell/export.sh "$@"
code=$?

echo ""
if [ "$code" = "0" ]; then
  echo "Copy the bundle above to the other machine's sync/inbox/, then run its import launcher."
else
  echo "Export failed (exit $code) — see the messages above."
fi
echo ""
# `|| true`: on EOF (non-interactive run) `read` returns non-zero, which must
# not replace the export's own exit code.
read -r -p "Press Enter to close..." || true
exit "$code"
