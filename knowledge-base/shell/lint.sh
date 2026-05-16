#!/usr/bin/env bash
# AI Knowledge Engine — lint wrapper.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "❌ Python 3 not found"
  exit 2
fi

$PYTHON scripts/kb_lint.py "$@"
