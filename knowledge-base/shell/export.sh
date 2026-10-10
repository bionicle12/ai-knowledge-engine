#!/usr/bin/env bash
# AI Knowledge Engine — export wrapper (pack this base into a bundle).
# Python comes from shell/_kbpy.sh: $KB_PYTHON, the base's .venv, else python3.
KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)" || exit 2
. "$KB_SHELL_DIR/_kbpy.sh" || exit 2

kb_run scripts/kb_export.py "$@"
