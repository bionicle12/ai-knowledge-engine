#!/usr/bin/env bash
# AI Knowledge Engine — import wrapper (merge a bundle from another base).
# Python comes from shell/_kbpy.sh: $KB_PYTHON, the base's .venv, else python3.
KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)" || exit 2
. "$KB_SHELL_DIR/_kbpy.sh" || exit 2

# Exit code 1 means "merged, conflicts waiting in review/needs-merge/" — a
# normal outcome that is passed through unchanged.
kb_run scripts/kb_import.py "$@"
