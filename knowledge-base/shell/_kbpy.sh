# shellcheck shell=sh
# _kbpy.sh — shared helper sourced by the shell wrappers in shell/.
# POSIX sh: works when sourced from bash, dash or zsh. Not meant to be run.
#
# A wrapper uses it like this (the first line must not depend on $0 being
# absolute or on the current directory, so it resolves its own folder once):
#
#   KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)" || exit 2
#   . "$KB_SHELL_DIR/_kbpy.sh" || exit 2
#   kb_run scripts/kb_lint.py "$@"
#
# After sourcing:
#   KB_SHELL_DIR  absolute folder of the wrapper (derived from BASH_SOURCE
#                 when the wrapper did not set it and the shell is bash)
#   KB_ROOT       absolute base root = parent of KB_SHELL_DIR (overwritten)
#   kb_root               print KB_ROOT
#   kb_python             print the interpreter to use (status 2 if none):
#                           1. $KB_PYTHON (path or command name) when set
#                           2. <base>/.venv/bin/python
#                           3. <base>/../.venv/bin/python while the base is in
#                              the deploy layout (a sibling setup/ holding the
#                              engine, i.e. before finalize.sh; the venv is at
#                              the project root)
#                           4. python3
#   kb_require <relpath>  status 0 if <base>/<relpath> is a file, else an
#                         error on stderr and status 2
#   kb_run <relpath> [args...]
#                         run <base>/<relpath> with kb_python from KB_ROOT;
#                         returns the script's exit status (2 if it cannot
#                         start)

if [ -z "${KB_SHELL_DIR:-}" ]; then
  if [ -n "${BASH_SOURCE:-}" ]; then
    # shellcheck disable=SC2128,SC3028,SC3054
    KB_SHELL_DIR=$(CDPATH='' cd -- "$(dirname -- "$BASH_SOURCE")" && pwd -P) || return 2
  else
    echo "❌ _kbpy.sh: set KB_SHELL_DIR to the wrapper's folder before sourcing it" >&2
    return 2
  fi
fi

KB_ROOT=$(CDPATH='' cd -- "$KB_SHELL_DIR/.." && pwd -P) || return 2

kb_root() {
  printf '%s\n' "$KB_ROOT"
}

_kb_venv_python() {
  if [ -f "$1/bin/python" ] && [ -x "$1/bin/python" ]; then
    printf '%s\n' "$1/bin/python"
    return 0
  fi
  return 1
}

# The deploy-time layout: <project>/knowledge-base/ (or the --kb-dir folder)
# next to <project>/setup/ (the engine copy finalize.sh removes), with the
# venv at <project>/.venv (see kb-docs/01_PREREQUISITES.md). The folder name
# proves nothing: a finalized base may itself be called knowledge-base, and
# it never looks above its own root.
_kb_before_finalize() {
  [ -f "$(dirname -- "$KB_ROOT")/setup/scripts/kb_common.py" ]
}

kb_python() {
  if [ -n "${KB_PYTHON:-}" ]; then
    if command -v "$KB_PYTHON" >/dev/null 2>&1; then
      case $KB_PYTHON in
        /*|[A-Za-z]:*) printf '%s\n' "$KB_PYTHON" ;;
        */*) printf '%s/%s\n' "$(pwd -P)" "$KB_PYTHON" ;;  # kb_run cds to KB_ROOT
        *) printf '%s\n' "$KB_PYTHON" ;;
      esac
      return 0
    fi
    echo "❌ KB_PYTHON=$KB_PYTHON is not an executable Python" >&2
    return 2
  fi
  _kb_venv_python "$KB_ROOT/.venv" && return 0
  if _kb_before_finalize; then
    _kb_venv_python "$(dirname -- "$KB_ROOT")/.venv" && return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  echo "❌ Python 3 not found. Create the venv (see kb-docs/01_PREREQUISITES.md) or set KB_PYTHON." >&2
  return 2
}

kb_require() {
  if [ -f "$KB_ROOT/$1" ]; then
    return 0
  fi
  echo "❌ $1 not found" >&2
  echo "   Looked in: $KB_ROOT/$(dirname -- "$1")/" >&2
  return 2
}

kb_run() {
  _kb_script=$1
  shift
  kb_require "$_kb_script" || return 2
  _kb_python=$(kb_python) || return 2
  (cd "$KB_ROOT" && "$_kb_python" "$_kb_script" "$@")
}
