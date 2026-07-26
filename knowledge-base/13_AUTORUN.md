# 13 — Auto-run: automatic processing on changes

> The knowledge base should refresh **automatically** when new data arrives. Three mechanisms: file watcher (daemon), git hook, cron.
>
> **Reference implementations:** `knowledge-base/scripts/kb_watch.py`, `knowledge-base/scripts/kb_reflect.py`, `knowledge-base/scripts/kb_nlp_batch.py`, `knowledge-base/shell/watcher.sh`, `knowledge-base/shell/reindex.sh`. The agent copies them at deployment time.

---

## Why

Manual `./shell/reindex.sh` after every change is friction — and friction means the base goes stale. Automation removes that barrier.

---

## Mode 1: file watcher (recommended for active work)

### Dependencies

```txt
# In requirements.txt
watchdog>=4.0
```

### `scripts/kb_watch.py` contract

```python
"""
kb_watch.py — File-system watcher for the knowledge base.

Watches:
- raw/*/unsorted/  — new files for ingest
- knowledge/       — edits that should trigger reindex

When a new file appears in raw/:
1. Wait 5 seconds (the file may still be being written)
2. Run kb_ingest.py for the new file
3. Run NLP enrichment (if enabled)
4. If complexity < threshold → auto-process
5. If complexity >= threshold → review/needs-ai-decision/
6. Append to log.md
7. Regenerate the Repomix index

When a knowledge/ file changes:
1. Wait 2 seconds (debounce)
2. Regenerate the Repomix index
3. Run quick lint (--quick)
4. Append to log.md

Usage:
    ./shell/watcher.sh                         # Foreground
    ./shell/watcher.sh --daemon                # Background
    ./shell/watcher.sh --stop                  # Stop
    ./shell/watcher.sh --verbose               # Verbose logging

Exit:
    Ctrl+C or SIGTERM for graceful shutdown
"""

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import subprocess
import os

class RawFileHandler(FileSystemEventHandler):
    def __init__(self, debounce_seconds=5):
        self.debounce = debounce_seconds
        self._pending = {}

    def on_created(self, event):
        if event.is_directory:
            return
        # Debounce: wait until the file is fully written
        self._pending[event.src_path] = time.time()

    def process_pending(self):
        now = time.time()
        ready = [p for p, t in self._pending.items() if now - t > self.debounce]
        for path in ready:
            del self._pending[path]
            self.process_file(path)

    def process_file(self, filepath):
        print(f"[watch] New file detected: {filepath}")
        # 1. Ingest
        subprocess.run(["python3", "scripts/kb_ingest.py", filepath])
        # 2. Reindex
        subprocess.run(["./shell/reindex.sh"])
        print(f"[watch] Processed and reindexed: {filepath}")


class KnowledgeChangeHandler(FileSystemEventHandler):
    def __init__(self, debounce_seconds=2):
        self.debounce = debounce_seconds
        self._last_change = 0

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('.md'):
            return
        self._last_change = time.time()

    def should_reindex(self):
        if self._last_change == 0:
            return False
        if time.time() - self._last_change > self.debounce:
            self._last_change = 0
            return True
        return False
```

### Running via `shell/watcher.sh`

The deployed base includes `shell/watcher.sh` — a wrapper around `kb_watch.py` with auto-venv activation:

```bash
#!/bin/bash
# watcher.sh — File watcher for the Knowledge Base.
# Runs kb_watch.py with auto-venv activation and process management.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE=".watcher.pid"
LOGFILE=".watcher.log"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi

# Verify the script
if [ ! -f "scripts/kb_watch.py" ]; then
  echo "❌ scripts/kb_watch.py not found"
  exit 1
fi

case "${1:-}" in
  --stop)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm -f "$PIDFILE"
        echo "✅ Watcher stopped (PID $PID)"
      else
        rm -f "$PIDFILE"
        echo "⚠️  Process $PID was not running; pidfile removed"
      fi
    else
      echo "⚠️  Watcher is not running (no $PIDFILE)"
    fi
    ;;
  --status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "✅ Watcher running (PID $(cat "$PIDFILE"))"
    else
      echo "⚠️  Watcher not running"
    fi
    ;;
  --daemon)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "⚠️  Watcher already running (PID $(cat "$PIDFILE"))"
      exit 1
    fi
    echo "🔄 Starting watcher in the background..."
    nohup python3 scripts/kb_watch.py "${@:2}" > "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "✅ Watcher started (PID $!, log: $LOGFILE)"
    ;;
  --verbose)
    echo "👁  Starting watcher (verbose)..."
    python3 scripts/kb_watch.py --verbose
    ;;
  "")
    echo "👁  Starting watcher..."
    echo "   Ctrl+C to stop"
    python3 scripts/kb_watch.py
    ;;
  *)
    echo "Usage: ./shell/watcher.sh [--daemon|--stop|--status|--verbose]"
    echo ""
    echo "  (no flag)     Foreground mode (Ctrl+C to stop)"
    echo "  --daemon      Run in background"
    echo "  --stop        Stop background watcher"
    echo "  --status      Check whether the watcher is running"
    echo "  --verbose     Foreground with verbose logging"
    ;;
esac
```

```bash
chmod +x shell/watcher.sh
```

### Commands

```bash
# Foreground (for development)
./shell/watcher.sh

# Background
./shell/watcher.sh --daemon

# Status
./shell/watcher.sh --status

# Stop
./shell/watcher.sh --stop
```

### Systemd unit (Linux)

```ini
# /etc/systemd/user/kb-watch.service
[Unit]
Description=Knowledge Base File Watcher
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/knowledge-base
ExecStart=/path/to/knowledge-base/.venv/bin/python scripts/kb_watch.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable kb-watch
systemctl --user start kb-watch
systemctl --user status kb-watch
```

---

## Mode 2: git hook

For bases under git control.

### post-commit hook

```bash
#!/bin/sh
# .git/hooks/post-commit

# If knowledge/ files changed → reindex
changed_files=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || echo "")

if echo "$changed_files" | grep -q "^knowledge/"; then
  echo "[hook] Knowledge files changed, reindexing..."
  ./shell/reindex.sh > /dev/null 2>&1 &

  # Quick lint
  if [ -f "scripts/kb_lint.py" ]; then
    python3 scripts/kb_lint.py --quick > /dev/null 2>&1 &
  fi
fi
```

```bash
chmod +x .git/hooks/post-commit
```

### pre-commit hook (optional)

```bash
#!/bin/sh
# .git/hooks/pre-commit
# Validates frontmatter before committing

if [ -f "scripts/kb_lint.py" ]; then
  python3 scripts/kb_lint.py --quick --only frontmatter
  if [ $? -eq 2 ]; then
    echo "❌ Frontmatter errors found. Fix before committing."
    exit 1
  fi
fi
```

---

## Mode 3: cron (periodic tasks)

```bash
# crontab -e

# Every day at 03:00 — full lint + reindex
0 3 * * * cd /path/to/knowledge-base && ./shell/lint.sh >> log.md 2>&1 && ./shell/reindex.sh >> log.md 2>&1

# Every 6 hours — quick lint
0 */6 * * * cd /path/to/knowledge-base && python3 scripts/kb_lint.py --quick >> /dev/null 2>&1

# Every Sunday at 02:00 — NLP re-enrichment of all processed files
0 2 * * 0 cd /path/to/knowledge-base && python3 scripts/kb_nlp_batch.py >> log.md 2>&1
```

> **Important:** the machine may be off — cron does not guarantee execution. The main consolidation block lives inside `reindex.sh` (see below).

---

## Consolidation in reindex (instead of pure cron)

Problem: cron tasks do not fire if the machine is off. Solution: bake a check into `reindex.sh` — if more than 24 hours have passed since the last consolidation, run it now.

### Mechanism

```bash
# Add to reindex.sh before the final repomix call:

CONSOLIDATION_MARKER=".last_consolidation"
NOW=$(date +%s)
DAY_SECONDS=86400

if [ -f "$CONSOLIDATION_MARKER" ]; then
  LAST=$(cat "$CONSOLIDATION_MARKER")
  ELAPSED=$((NOW - LAST))
else
  ELAPSED=$((DAY_SECONDS + 1))  # First run → consolidate
fi

if [ $ELAPSED -gt $DAY_SECONDS ]; then
  echo "[reindex] Consolidation needed (${ELAPSED}s since last). Running..."

  # 1. Full lint (Python, 0 tokens)
  if [ -f "scripts/kb_lint.py" ]; then
    python3 scripts/kb_lint.py --output report
  fi

  # 2. Count changes since last consolidation
  CHANGES_SINCE=0
  if [ -f "log.md" ]; then
    LAST_DATE=$(date -d "@$LAST" -Iseconds 2>/dev/null || date -r "$LAST" -Iseconds 2>/dev/null || echo "")
    if [ -n "$LAST_DATE" ]; then
      CHANGES_SINCE=$(grep -c "^## \[" log.md 2>/dev/null || echo "0")
      # Better count: scripts/kb_reflect.py --count-changes
    fi
  fi

  # 3. Reflection check (mode-aware)
  #    mode=default: importance_threshold=25, min_interval=7d, require_changes=true
  #    mode=super:   importance_threshold=5,  min_interval=0,  require_changes=false
  MODE=$(python3 -c "import yaml; print(yaml.safe_load(open('kb.config.yml')).get('mode','default'))" 2>/dev/null || echo "default")

  REFLECT_TRIGGERED_BY_THRESHOLD=false
  if [ -f "scripts/kb_reflect.py" ]; then
    # --check-threshold prints "THRESHOLD_MET" if sum(importance) > threshold (mode-dependent)
    THRESHOLD_RESULT=$(python3 scripts/kb_reflect.py --check-threshold --dry-run 2>&1)
    if echo "$THRESHOLD_RESULT" | grep -q "THRESHOLD_MET"; then
      echo "[reindex] Importance threshold met → auto-triggering reflection (mode=$MODE)"
      python3 scripts/kb_reflect.py --generate
      REFLECT_TRIGGERED_BY_THRESHOLD=true
      echo "$NOW" > ".last_reflection"
    fi
  fi

  # 4. Weekly reflection (ONLY if there were changes AND not already triggered by threshold)
  REFLECTION_MARKER=".last_reflection"
  WEEK_SECONDS=604800
  if [ -f "$REFLECTION_MARKER" ]; then
    LAST_REFLECT=$(cat "$REFLECTION_MARKER")
    REFLECT_ELAPSED=$((NOW - LAST_REFLECT))
  else
    REFLECT_ELAPSED=$((WEEK_SECONDS + 1))
  fi

  REFLECT_STATUS="skipped"
  if [ "$REFLECT_TRIGGERED_BY_THRESHOLD" = true ]; then
    REFLECT_STATUS="triggered (importance threshold, mode=$MODE)"
  elif [ "$MODE" = "super" ]; then
    # super mode: threshold=5 covers most, but if it didn't trigger and changes exist — run
    if [ "$CHANGES_SINCE" -gt 0 ] 2>/dev/null; then
      echo "[reindex] Super mode reflection: $CHANGES_SINCE changes found → running"
      if [ -f "scripts/kb_reflect.py" ]; then
        python3 scripts/kb_reflect.py --generate
      fi
      echo "$NOW" > "$REFLECTION_MARKER"
      REFLECT_STATUS="triggered (super mode, $CHANGES_SINCE changes)"
    else
      REFLECT_STATUS="skipped (super, no changes)"
    fi
  elif [ $REFLECT_ELAPSED -gt $WEEK_SECONDS ]; then
    if [ "$CHANGES_SINCE" -gt 0 ] 2>/dev/null; then
      echo "[reindex] Weekly reflection: $CHANGES_SINCE changes found → running"
      if [ -f "scripts/kb_reflect.py" ]; then
        python3 scripts/kb_reflect.py --generate
      fi
      echo "$NOW" > "$REFLECTION_MARKER"
      REFLECT_STATUS="triggered (weekly, $CHANGES_SINCE changes)"
    else
      echo "[reindex] Weekly reflection: no changes since last → skipping"
      REFLECT_STATUS="skipped (no changes, ${REFLECT_ELAPSED}s elapsed)"
      # Do NOT update the marker — let days accumulate (10, 15...).
      # Will fire when changes appear.
    fi
  else
    REFLECT_STATUS="skipped (< 7 days)"
  fi

  # 5. NLP re-enrichment (if enabled, 0 tokens)
  if [ -f "scripts/kb_nlp_batch.py" ]; then
    python3 scripts/kb_nlp_batch.py --incremental
  fi

  # 6. Super mode: auto-process review queue
  REVIEW_STATUS="skipped"
  if [ "$MODE" = "super" ] && [ -d "review/needs-ai-decision" ]; then
    REVIEW_COUNT=$(find review/needs-ai-decision/ -name '*.md' 2>/dev/null | wc -l)
    if [ "$REVIEW_COUNT" -gt 0 ]; then
      echo "[reindex] Super mode: $REVIEW_COUNT items in review queue → AI processing"
      REVIEW_STATUS="auto-processed ($REVIEW_COUNT items)"
      # The AI agent processes them on the next IDE session, or via a script
    fi
  fi

  # 7. Super mode: lint L2 (AI review) on consolidation
  LINT_L2_STATUS="skipped"
  if [ "$MODE" = "super" ]; then
    echo "[reindex] Super mode: running lint L2 (AI review)"
    LINT_L2_STATUS="triggered (super mode)"
    # The AI agent runs lint L2 on the next IDE session
  fi

  # 8. Update consolidation marker
  echo "$NOW" > "$CONSOLIDATION_MARKER"
  echo "" >> log.md
  echo "## [$(date -Iseconds)] consolidation | Daily consolidation (via reindex)" >> log.md
  echo "- Mode: $MODE" >> log.md
  echo "- Elapsed since last: ${ELAPSED}s" >> log.md
  echo "- Lint: completed" >> log.md
  echo "- Changes detected: $CHANGES_SINCE" >> log.md
  echo "- Reflection: $REFLECT_STATUS" >> log.md
  echo "- Review queue: $REVIEW_STATUS" >> log.md
  echo "- Lint L2: $LINT_L2_STATUS" >> log.md
else
  echo "[reindex] Consolidation not needed (${ELAPSED}s < ${DAY_SECONDS}s)"
fi
```

### What consolidation does

| Step | Action | Frequency |
|------|--------|-----------|
| Full lint (Python) | All level-1 checks from `09_LINT.md` | Once per day, 0 tokens |
| Change detection | Count entries in log.md since last reflection | Once per day, 0 tokens |
| Importance check | If `sum(importance)` > threshold → auto-`!reflect` | Once per day, ~15K if fired |
| Weekly reflection | Generate insights (LLM) | ≥7 days **AND** changes, ~15K tokens |
| NLP batch | Incremental re-enrichment of new processed/ | Once per day, 0 tokens |
| Access decay | Update recency scores in routing tables | Once per day, 0 tokens |

### Smart reflection schedule

```
Days without reflection:  1  2  3  4  5  6  7  8  9  10  ...
Were there changes?       -  -  -  -  -  -  -  -  ✓  -   ...
                                                    ↑
                                          Run! (>7 days + changes)
```

- **≤7 days** → don't run (still early)
- **>7 days** but **no changes** → don't run, keep counting (10, 15, 20...)
- **>7 days** and **changes present** → run, reset marker
- **importance threshold** reached → **run immediately** (regardless of days)

The last point matters: in active sessions reflection fires before 7 days, preventing stagnation.

### Guarantees

- Consolidation runs **at most once per day** (`.last_consolidation` marker)
- Fires on **any** `reindex.sh` call — manual, watcher, git hook
- If the machine was off for 3 days — first reindex performs consolidation
- Does not block the main reindex — lint and reflection run **before** repomix

---

## Trigger table

| Event | Action | Source |
|-------|--------|--------|
| `!view` | Start or reopen the local read-only graph viewer | `python3 scripts/kb_view.py --background` |
| New file in `raw/*/unsorted/` | Ingest → NLP → Process → Reindex | `./shell/watcher.sh` |
| Edit in `knowledge/` | Reindex + quick lint | `./shell/watcher.sh` or git hook |
| `!save` in AI session | Session capture (with enrichment) → Reindex | AI agent |
| `!reflect` | Reflection: insight generation (~15K tokens) | AI agent |
| `!audit` | Lint level 2: AI review (~50–100K tokens) | AI agent |
| Lint found and fixed issues | Reindex | `kb_lint.py --fix` |
| AI did query-writeback | Write page → Reindex | AI agent |
| Git commit | Quick lint + Reindex | git hook |
| Daily | Full lint (Python) + Reindex | cron |
| reindex (>24h) | Consolidation (lint + NLP batch + reflection) | `reindex.sh` |
| reindex (>7d) | Weekly reflection (LLM insights) | `reindex.sh` |

---

## Configuration in `kb.config.yml`

```yaml
autorun:
  watch_enabled: true
  watch_dirs:
    - "raw/*/unsorted/"
    - "knowledge/"
  debounce_raw_seconds: 5
  debounce_knowledge_seconds: 2
  auto_nlp: true                    # NLP enrichment on ingest
  auto_lint_on_change: true         # Quick lint on knowledge/ edits
  auto_reindex_on_change: true      # Reindex on knowledge/ edits
  complexity_auto_threshold: 0.5    # below → auto-extract; above → review
  consolidation_interval_hours: 24  # Min interval between consolidations
  consolidation_on_reindex: true    # Check on every reindex
```

---

## Integration

- **03_PIPELINE:** watch invokes ingest on a new file; surprise filter checks duplicates
- **05_INDEX:** watch triggers reindex on changes
- **07_INTERACTION_LOOP:** consolidation checks reflection threshold and triggers insights
- **09_LINT:** watch → quick lint; consolidation → full lint
- **10_LOG:** all auto operations are appended to log.md, including consolidation
- **11_PROVENANCE:** consolidation refreshes recency scores and checks bi-temporal validity
- **12_NLP:** watch runs NLP on ingest; consolidation runs batch re-enrichment
