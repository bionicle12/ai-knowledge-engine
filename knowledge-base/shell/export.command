#!/usr/bin/env bash
# export.command — double-click launcher: pack this base into a bundle (macOS).

set -euo pipefail

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

# `clear` fails when there is no TERM (double-clicked from a non-tty context).
clear 2>/dev/null || true
echo "📦 Export knowledge bundle"
echo "    project: $PROJECT_ROOT"
echo "    --------------------------------------"
echo ""

bash shell/export.sh "$@"

echo ""
echo "Copy the bundle above to the other machine's sync/inbox/, then run its import launcher."
echo ""
# `|| true`: on EOF (non-interactive run) `read` returns non-zero, which must
# not turn a successful export into a failure.
read -r -p "Press Enter to close..." || true
