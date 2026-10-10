#!/usr/bin/env bash
# AI Knowledge Engine — lint wrapper: runs scripts/kb_lint.py from the base
# root with every argument passed through; the exit status is kb_lint's.
# Python comes from shell/_kbpy.sh: $KB_PYTHON, the base's .venv, else python3.
KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)" || exit 2
. "$KB_SHELL_DIR/_kbpy.sh" || exit 2
kb_run scripts/kb_lint.py "$@"
