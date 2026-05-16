#!/usr/bin/env bash
# AI Knowledge Engine — post-deploy smoke-test wrapper.
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

if [ ! -f "scripts/kb_doctor.py" ]; then
  echo "❌ scripts/kb_doctor.py not found"
  echo "   Looked in: $PROJECT_ROOT/scripts/"
  exit 2
fi

$PYTHON scripts/kb_doctor.py "$@"
