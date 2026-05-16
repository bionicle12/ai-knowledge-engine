#!/usr/bin/env bash
# AI Knowledge Engine — file watcher wrapper.
# Manages a daemonized kb_watch.py process.
#
# Usage:
#   ./watcher.sh                # foreground (Ctrl+C to stop)
#   ./watcher.sh --daemon       # background; logs to .watcher.log
#   ./watcher.sh --stop
#   ./watcher.sh --status
#   ./watcher.sh --verbose

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE=".watcher.pid"
LOGFILE=".watcher.log"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "❌ Python 3 not found"
  exit 2
fi

if [ ! -f "scripts/kb_watch.py" ]; then
  echo "❌ scripts/kb_watch.py not found"
  exit 2
fi

case "${1:-}" in
  --stop)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm -f "$PIDFILE"
        echo "✅ watcher stopped (PID $PID)"
      else
        rm -f "$PIDFILE"
        echo "⚠️  process $PID was not running; pidfile removed"
      fi
    else
      echo "⚠️  watcher not running"
    fi
    ;;
  --status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "✅ watcher running (PID $(cat "$PIDFILE"))"
    else
      echo "⚠️  watcher not running"
    fi
    ;;
  --daemon)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "⚠️  watcher already running (PID $(cat "$PIDFILE"))"
      exit 1
    fi
    echo "🔄 starting watcher in background..."
    nohup "$PYTHON" scripts/kb_watch.py "${@:2}" > "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "✅ watcher started (PID $!, log: $LOGFILE)"
    ;;
  --verbose)
    echo "👁  watcher (verbose)..."
    "$PYTHON" scripts/kb_watch.py --verbose
    ;;
  "")
    echo "👁  watcher (foreground; Ctrl+C to stop)"
    "$PYTHON" scripts/kb_watch.py
    ;;
  *)
    echo "Usage: $0 [--daemon|--stop|--status|--verbose]"
    exit 1
    ;;
esac
