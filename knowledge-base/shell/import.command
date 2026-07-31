#!/usr/bin/env bash
# import.command — double-click launcher: merge every bundle sitting in
# sync/inbox/ into this base (macOS).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/shell/import.sh" ]; then
  PROJECT_ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../shell/import.sh" ]; then
  PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  echo "❌ Cannot find shell/import.sh near this launcher."
  echo "   Looked at:"
  echo "     $SCRIPT_DIR/shell/import.sh"
  echo "     $SCRIPT_DIR/../shell/import.sh"
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
echo "📥 Import knowledge bundles from sync/inbox/"
echo "    project: $PROJECT_ROOT"
echo "    --------------------------------------"
echo ""

bash shell/import.sh "$@"
code=$?

echo ""
if [ "$code" = "1" ]; then
  echo "Some pages changed on both machines — nothing was overwritten."
  echo "Open the AI chat and send: !merge"
elif [ "$code" = "0" ]; then
  echo "Merged cleanly. Send !merge in the AI chat so the agent cross-links the new knowledge."
fi
echo ""
read -r -p "Press Enter to close..." || true
exit "$code"
