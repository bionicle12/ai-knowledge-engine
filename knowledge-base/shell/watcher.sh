#!/usr/bin/env bash
# AI Knowledge Engine — file watcher wrapper around scripts/kb_watch.py.
#
# Usage:
#   ./shell/watcher.sh [options]            # foreground (Ctrl+C to stop);
#                                           # options go to kb_watch.py, e.g. --verbose
#   ./shell/watcher.sh --daemon [options]   # background; logs to .watcher.log
#   ./shell/watcher.sh --stop               # stop the background watcher and wait for it
#   ./shell/watcher.sh --status

set -e

# Resolve the project root (parent of shell/ where this script lives).
SHELL_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
PROJECT_ROOT="$(cd "$SHELL_DIR/.." && pwd -P)"
cd "$PROJECT_ROOT"

PIDFILE=".watcher.pid"
LOGFILE=".watcher.log"
STOP_WAIT_SECONDS=30

if [ -f "$SHELL_DIR/_kbpy.sh" ]; then
  KB_SHELL_DIR="$SHELL_DIR"
  . "$SHELL_DIR/_kbpy.sh" || exit 2
  PYTHON="$(kb_python)" || exit 2
elif [ -x ".venv/bin/python" ]; then  # a shell/ folder that predates _kbpy.sh
  PYTHON="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "❌ Python 3 not found"
  exit 2
fi

if [ ! -f "scripts/kb_watch.py" ]; then
  echo "❌ scripts/kb_watch.py not found"
  echo "   Looked in: $PROJECT_ROOT/scripts/"
  echo "   Did the agent finish deployment? Try: ls $PROJECT_ROOT"
  exit 2
fi

# True while the process exists and is not a zombie.
alive() {
  kill -0 "$1" 2>/dev/null || return 1
  case "$(ps -p "$1" -o stat= 2>/dev/null)" in
    Z*) return 1 ;;
  esac
  return 0
}

# Print the PID from the pidfile if that process is still our watcher. After
# a reboot the PID may belong to another program: check its command line
# where ps can show it (Git Bash's ps cannot; trust kill -0 there).
watcher_pid() {
  local pid args
  [ -f "$PIDFILE" ] || return 1
  pid="$(cat "$PIDFILE" 2>/dev/null)" || return 1
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  alive "$pid" || return 1
  args="$(ps -p "$pid" -o args= 2>/dev/null)" || args=""
  case "$args" in
    ''|*kb_watch*) ;;
    *) return 1 ;;
  esac
  echo "$pid"
}

case "${1:-}" in
  --stop)
    if PID="$(watcher_pid)"; then
      kill "$PID"
      # The watcher finishes its current step (ingest, reindex) before it
      # exits; report success only once it is really gone.
      waited=0
      while alive "$PID"; do
        if [ "$waited" -ge $((STOP_WAIT_SECONDS * 5)) ]; then
          echo "⚠️  watcher (PID $PID) is still finishing its current step after ${STOP_WAIT_SECONDS}s"
          echo "   Run ./shell/watcher.sh --stop again later."
          exit 1
        fi
        sleep 0.2
        waited=$((waited + 1))
      done
      rm -f "$PIDFILE"
      echo "✅ watcher stopped (PID $PID)"
    elif [ -f "$PIDFILE" ]; then
      rm -f "$PIDFILE"
      echo "⚠️  watcher was not running; stale pidfile removed"
    else
      echo "⚠️  watcher not running"
    fi
    ;;
  --status)
    if PID="$(watcher_pid)"; then
      echo "✅ watcher running (PID $PID)"
    else
      echo "⚠️  watcher not running"
    fi
    ;;
  --daemon)
    if PID="$(watcher_pid)"; then
      echo "⚠️  watcher already running (PID $PID)"
      exit 1
    fi
    shift
    echo "🔄 starting watcher in background..."
    # Unbuffered: the watcher's own lines (and those of the scripts it runs)
    # reach the log as they happen, not when the process exits.
    PYTHONUNBUFFERED=1 nohup "$PYTHON" scripts/kb_watch.py --root "$PROJECT_ROOT" "$@" > "$LOGFILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PIDFILE"
    sleep 1
    if ! alive "$PID"; then
      rm -f "$PIDFILE"
      echo "❌ watcher exited right away — see $LOGFILE:"
      tail -n 5 "$LOGFILE" 2>/dev/null || true
      exit 1
    fi
    echo "✅ watcher started (PID $PID, log: $LOGFILE)"
    ;;
  -h|--help)
    echo "Usage: $0 [--daemon|--stop|--status] [kb_watch.py options]"
    echo "  (no flag)  foreground watcher (Ctrl+C to stop)"
    echo "  --daemon   run in the background, log to $LOGFILE"
    echo "  --stop     stop the background watcher (waits up to ${STOP_WAIT_SECONDS}s)"
    echo "  --status   is the background watcher running?"
    echo "kb_watch.py options: --verbose, --no-reindex, --debounce-raw N, --debounce-knowledge N"
    ;;
  *)
    echo "👁  watcher (foreground; Ctrl+C to stop)"
    "$PYTHON" scripts/kb_watch.py --root "$PROJECT_ROOT" "$@"
    ;;
esac
