#!/usr/bin/env bash
# AI Knowledge Engine — reindex wrapper.
# A thin wrapper over scripts/kb_reindex.py (the same pipeline the watcher,
# the git hook and reindex.bat run): ingest → routing → quick lint →
# throttled consolidation → index → STATUS.md.
# POSIX-friendly: works on Linux and macOS.
#
# Usage (every flag is passed to kb_reindex.py; see --help):
#   ./shell/reindex.sh               # full pipeline
#   ./shell/reindex.sh --quick       # skip the consolidation block
#   ./shell/reindex.sh --index-only  # index + STATUS.md only
#   ./shell/reindex.sh --force       # rebuild every pack
#
# Exit status is kb_reindex.py's: non-zero when ingest failed or the index
# could not be built (for example, repomix is not installed).

KB_SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)" || exit 2
. "$KB_SHELL_DIR/_kbpy.sh" || exit 2
kb_run scripts/kb_reindex.py "$@"
