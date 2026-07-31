#!/usr/bin/env bash
# AI Knowledge Engine — import wrapper (merge a bundle from another base).
set -e

SHELL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROJECT_ROOT="$(cd "$SHELL_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -x ".venv/bin/python" ]; then
  PYTHON="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "❌ Python 3 not found"
  exit 2
fi

if [ ! -f "scripts/kb_import.py" ]; then
  echo "❌ scripts/kb_import.py not found"
  echo "   Looked in: $PROJECT_ROOT/scripts/"
  exit 2
fi

# Exit code 1 means "merged, conflicts waiting in review/needs-merge/" — that is
# a normal outcome, not a wrapper failure, so it must not trip `set -e`.
set +e
$PYTHON scripts/kb_import.py "$@"
code=$?
set -e
exit $code
