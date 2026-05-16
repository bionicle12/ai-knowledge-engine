#!/usr/bin/env bash
# AI Knowledge Engine — reindex script.
# Runs ingest, quick lint, optional consolidation, and regenerates the index.
# POSIX-friendly: works on Linux and macOS.
#
# Usage:
#   ./reindex.sh              # full pipeline
#   ./reindex.sh --no-watch   # skip the consolidation block
#   ./reindex.sh --quick      # ingest + reindex only

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Resolve Python (prefer venv)
if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif [ -x "venv/bin/python" ]; then
  PYTHON="venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "❌ Python 3 not found"
  exit 2
fi

QUICK=false
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=true ;;
  esac
done

echo "🔄 [reindex] ingest pipeline..."
$PYTHON scripts/kb_ingest.py

echo "🩺 [reindex] quick lint..."
$PYTHON scripts/kb_lint.py --quick || true

# ----- Consolidation (lint + reflection trigger + nlp batch) -----
if [ "$QUICK" = false ]; then
  CONSOLIDATION_MARKER=".last_consolidation"
  NOW=$(date +%s)
  DAY_SECONDS=86400

  if [ -f "$CONSOLIDATION_MARKER" ]; then
    LAST=$(cat "$CONSOLIDATION_MARKER")
    ELAPSED=$((NOW - LAST))
  else
    ELAPSED=$((DAY_SECONDS + 1))
  fi

  if [ "$ELAPSED" -gt "$DAY_SECONDS" ]; then
    echo "🧰 [reindex] consolidation (${ELAPSED}s since last)..."
    $PYTHON scripts/kb_lint.py --output report || true
    if [ -f scripts/kb_nlp_batch.py ]; then
      $PYTHON scripts/kb_nlp_batch.py --incremental || true
    fi
    if [ -f scripts/kb_reflect.py ]; then
      RESULT=$($PYTHON scripts/kb_reflect.py --check-threshold --dry-run || echo SKIP)
      if [ "$RESULT" != "SKIP" ]; then
        echo "🧠 [reindex] reflection due ($RESULT) — recording trigger"
        $PYTHON scripts/kb_reflect.py --generate || true
      fi
    fi
    echo "$NOW" > "$CONSOLIDATION_MARKER"
  fi
fi

# ----- Index generation -----
if command -v repomix >/dev/null 2>&1; then
  echo "📦 [reindex] generating Repomix index..."
  repomix --quiet || repomix
else
  echo "⚠️  [reindex] repomix not installed; skipping index generation"
  echo "    install: npm install -g repomix"
fi

echo "✅ [reindex] done"
