#!/usr/bin/env bash
# AI Knowledge Engine — post-deploy smoke-test wrapper: runs
# scripts/kb_doctor.py from the base root with every argument passed through.
# Exit 0 = doctor passes (warnings allowed), 2 = at least one error.
# Python comes from shell/_kbpy.sh: $KB_PYTHON, the base's .venv, else python3.
KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)" || exit 2
. "$KB_SHELL_DIR/_kbpy.sh" || exit 2
kb_run scripts/kb_doctor.py "$@"
