#!/usr/bin/env bash
# watcher-stop.command — double-click launcher to stop a daemonized watcher (macOS).
#
# This is meant for users who started the watcher with --daemon mode.
# If you launched watcher-start.command instead, just press Ctrl+C in that
# window — this stop launcher is not needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
elif [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

echo "🛑 Stopping knowledge-base watcher..."

if [ -f "shell/watcher.sh" ]; then
  bash shell/watcher.sh --stop
elif [ -f "watcher.sh" ]; then
  bash watcher.sh --stop
else
  echo "❌ watcher.sh not found"
fi

echo ""
read -r -p "Press Enter to close..."
