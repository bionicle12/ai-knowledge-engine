---
translation_of: knowledge-base/13_AUTORUN.md
source_commit: 6aa3cf8185ced124e010747a4238fd8f6097a76f
source_version: 0.7.0
translated_at: 2026-05-16
translator: human
---

# 13 — Auto-run: автоматический запуск при изменениях

> База знаний должна обновляться **автоматически** при появлении новых данных. Три режима: file watcher (daemon), git hook, cron.
>
> **Reference implementations:** `knowledge-base/scripts/kb_watch.py`, `knowledge-base/scripts/kb_reflect.py`, `knowledge-base/scripts/kb_nlp_batch.py`, `knowledge-base/shell/watcher.sh`, `knowledge-base/shell/reindex.sh`. Агент копирует их на этапе развёртывания.

---

## Зачем

Ручной запуск `./reindex.sh` после каждого изменения — friction, которая приводит к тому, что база устаревает. Автоматизация убирает этот барьер.

---

## Режим 1: File watcher (рекомендуется для активной работы)

### Зависимости

```txt
# В requirements.txt
watchdog>=4.0
```

### Контракт `scripts/kb_watch.py`

```python
"""
kb_watch.py — File system watcher для knowledge base.

Мониторит:
- raw/*/unsorted/  — новые файлы для ingest
- knowledge/       — изменения для reindex

При обнаружении нового файла в raw/:
1. Ждёт 5 секунд (файл может быть в процессе записи)
2. Запускает kb_ingest.py для нового файла
3. Запускает NLP enrichment (если включён)
4. Если complexity < threshold → авто-обработка
5. Если complexity >= threshold → review/needs-ai-decision/
6. Пишет в log.md
7. Перегенерирует Repomix-индекс

При изменении файла в knowledge/:
1. Ждёт 2 секунды (debounce)
2. Перегенерирует Repomix-индекс
3. Запускает quick lint (--quick)
4. Пишет в log.md

Usage:
    ./watcher.sh                               # Foreground
    ./watcher.sh --daemon                      # Background
    ./watcher.sh --stop                        # Остановить
    ./watcher.sh --verbose                     # С подробным логированием

Exit:
    Ctrl+C или SIGTERM для graceful shutdown
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
        # Debounce: ждём пока файл полностью записан
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
        subprocess.run(["./reindex.sh"])
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

### Запуск через `watcher.sh`

В корне базы создаётся `watcher.sh` — обёртка над `kb_watch.py` с автоматической активацией venv:

```bash
#!/bin/bash
# watcher.sh — File watcher для Knowledge Base
# Запускает kb_watch.py с автоматической активацией venv и управлением процессом.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PIDFILE=".watcher.pid"
LOGFILE=".watcher.log"

# Активировать venv если есть
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
fi

# Проверить наличие скрипта
if [ ! -f "scripts/kb_watch.py" ]; then
  echo "❌ scripts/kb_watch.py не найден"
  exit 1
fi

case "${1:-}" in
  --stop)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm -f "$PIDFILE"
        echo "✅ Watcher остановлен (PID $PID)"
      else
        rm -f "$PIDFILE"
        echo "⚠️ Процесс $PID уже не работает, pidfile удалён"
      fi
    else
      echo "⚠️ Watcher не запущен (нет $PIDFILE)"
    fi
    ;;
  --status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "✅ Watcher работает (PID $(cat "$PIDFILE"))"
    else
      echo "⚠️ Watcher не запущен"
    fi
    ;;
  --daemon)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "⚠️ Watcher уже запущен (PID $(cat "$PIDFILE"))"
      exit 1
    fi
    echo "🔄 Запуск watcher в фоне..."
    nohup python3 scripts/kb_watch.py "${@:2}" > "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "✅ Watcher запущен (PID $!, лог: $LOGFILE)"
    ;;
  --verbose)
    echo "👁 Запуск watcher (verbose)..."
    python3 scripts/kb_watch.py --verbose
    ;;
  "")
    echo "👁 Запуск watcher..."
    echo "   Ctrl+C для остановки"
    python3 scripts/kb_watch.py
    ;;
  *)
    echo "Usage: ./watcher.sh [--daemon|--stop|--status|--verbose]"
    echo ""
    echo "  (без флагов)  Foreground mode (Ctrl+C для остановки)"
    echo "  --daemon      Запуск в фоне"
    echo "  --stop        Остановить фоновый watcher"
    echo "  --status      Проверить, работает ли watcher"
    echo "  --verbose     Foreground с подробным логированием"
    ;;
esac
```

```bash
chmod +x watcher.sh
```

### Команды

```bash
# Foreground (для разработки)
./watcher.sh

# Background
./watcher.sh --daemon

# Проверить статус
./watcher.sh --status

# Остановить
./watcher.sh --stop
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

## Режим 2: Git hook

Для баз, которые под git-контролем.

### post-commit hook

```bash
#!/bin/sh
# .git/hooks/post-commit

# Если изменены файлы в knowledge/ или knowledge-base/ → reindex
changed_files=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || echo "")

if echo "$changed_files" | grep -q "^knowledge/"; then
  echo "[hook] Knowledge files changed, reindexing..."
  ./reindex.sh > /dev/null 2>&1 &

  # Quick lint
  if [ -f "scripts/kb_lint.py" ]; then
    python3 scripts/kb_lint.py --quick > /dev/null 2>&1 &
  fi
fi
```

```bash
chmod +x .git/hooks/post-commit
```

### pre-commit hook (опционально)

```bash
#!/bin/sh
# .git/hooks/pre-commit
# Проверяет frontmatter перед коммитом

if [ -f "scripts/kb_lint.py" ]; then
  python3 scripts/kb_lint.py --quick --only frontmatter
  if [ $? -eq 2 ]; then
    echo "❌ Frontmatter errors found. Fix before committing."
    exit 1
  fi
fi
```

---

## Режим 3: Cron (периодические задачи)

```bash
# crontab -e

# Каждый день в 3:00 — полный lint + reindex
0 3 * * * cd /path/to/knowledge-base && ./lint.sh >> log.md 2>&1 && ./reindex.sh >> log.md 2>&1

# Каждые 6 часов — quick lint
0 */6 * * * cd /path/to/knowledge-base && python3 scripts/kb_lint.py --quick >> /dev/null 2>&1

# Каждое воскресенье в 2:00 — NLP re-enrichment всех processed файлов
0 2 * * 0 cd /path/to/knowledge-base && python3 scripts/kb_nlp_batch.py >> log.md 2>&1
```

> **Важно:** ПК может быть выключен — cron не гарантирует выполнение. Поэтому основная консолидация встроена в `reindex.sh` (см. ниже).

---

## Консолидация при reindex (вместо чистого cron)

Проблема: cron-задачи не срабатывают, если ПК выключен. Решение: встроить проверку в `reindex.sh` — если прошло > 24 часов с последней консолидации, выполнить её.

### Механизм

```bash
# В reindex.sh добавить перед финальным repomix:

CONSOLIDATION_MARKER=".last_consolidation"
NOW=$(date +%s)
DAY_SECONDS=86400

if [ -f "$CONSOLIDATION_MARKER" ]; then
  LAST=$(cat "$CONSOLIDATION_MARKER")
  ELAPSED=$((NOW - LAST))
else
  ELAPSED=$((DAY_SECONDS + 1))  # Первый запуск → консолидировать
fi

if [ $ELAPSED -gt $DAY_SECONDS ]; then
  echo "[reindex] Consolidation needed (${ELAPSED}s since last). Running..."

  # 1. Полный lint (Python, 0 токенов)
  if [ -f "scripts/kb_lint.py" ]; then
    python3 scripts/kb_lint.py --output report
  fi

  # 2. Подсчёт изменений с последней консолидации
  #    Считаем записи в log.md после даты последней консолидации
  CHANGES_SINCE=0
  if [ -f "log.md" ]; then
    LAST_DATE=$(date -d "@$LAST" -Iseconds 2>/dev/null || date -r "$LAST" -Iseconds 2>/dev/null || echo "")
    if [ -n "$LAST_DATE" ]; then
      CHANGES_SINCE=$(grep -c "^## \[" log.md 2>/dev/null || echo "0")
      # Более точный подсчёт: скрипт kb_reflect.py --count-changes
    fi
  fi

  # 3. Проверка рефлексии (mode-aware)
  #    mode=default: importance_threshold=25, min_interval=7d, require_changes=true
  #    mode=super:   importance_threshold=5,  min_interval=0,  require_changes=false
  MODE=$(python3 -c "import yaml; print(yaml.safe_load(open('kb.config.yml')).get('mode','default'))" 2>/dev/null || echo "default")

  REFLECT_TRIGGERED_BY_THRESHOLD=false
  if [ -f "scripts/kb_reflect.py" ]; then
    # --check-threshold выводит "THRESHOLD_MET" если sum(importance) > порог (зависит от mode)
    THRESHOLD_RESULT=$(python3 scripts/kb_reflect.py --check-threshold --dry-run 2>&1)
    if echo "$THRESHOLD_RESULT" | grep -q "THRESHOLD_MET"; then
      echo "[reindex] Importance threshold met → auto-triggering reflection (mode=$MODE)"
      python3 scripts/kb_reflect.py --generate
      REFLECT_TRIGGERED_BY_THRESHOLD=true
      echo "$NOW" > ".last_reflection"
    fi
  fi

  # 4. Еженедельная рефлексия (ТОЛЬКО если были изменения И НЕ запущена по threshold)
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
    # super mode: threshold=5 уже покрывает, но если не сработал и есть changes — запустить
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
      # НЕ обновляем маркер — пусть дни копятся дальше (10, 15...)
      # Запустится когда появятся изменения
    fi
  else
    REFLECT_STATUS="skipped (< 7 days)"
  fi

  # 5. NLP re-enrichment (если включён, 0 токенов)
  if [ -f "scripts/kb_nlp_batch.py" ]; then
    python3 scripts/kb_nlp_batch.py --incremental
  fi

  # 6. Super mode: авто-обработка review queue
  REVIEW_STATUS="skipped"
  if [ "$MODE" = "super" ] && [ -d "review/needs-ai-decision" ]; then
    REVIEW_COUNT=$(find review/needs-ai-decision/ -name '*.md' 2>/dev/null | wc -l)
    if [ "$REVIEW_COUNT" -gt 0 ]; then
      echo "[reindex] Super mode: $REVIEW_COUNT items in review queue → AI processing"
      REVIEW_STATUS="auto-processed ($REVIEW_COUNT items)"
      # AI-агент обработает при следующей IDE-сессии или скриптом
    fi
  fi

  # 7. Super mode: lint L2 (AI-ревью) при консолидации
  LINT_L2_STATUS="skipped"
  if [ "$MODE" = "super" ]; then
    echo "[reindex] Super mode: running lint L2 (AI review)"
    LINT_L2_STATUS="triggered (super mode)"
    # AI-агент выполнит lint L2 при следующей IDE-сессии
  fi

  # 8. Обновить маркер консолидации
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

### Что делает консолидация

| Шаг | Действие | Частота |
|-----|---------|--------|
| Full lint (Python) | Все проверки уровня 1 из `09_LINT.md` | Раз в сутки, 0 токенов |
| Change detection | Подсчитать изменения в log.md с последней рефлексии | Раз в сутки, 0 токенов |
| Importance check | Если `sum(importance)` > threshold → авто-`!reflect` | Раз в сутки, ~15K если сработал |
| Weekly reflection | Сгенерировать insights (LLM) | ≥7 дней **И** есть изменения, ~15K токенов |
| NLP batch | Инкрементальный re-enrichment новых processed/ | Раз в сутки, 0 токенов |
| Access decay | Обновить recency scores в routing tables | Раз в сутки, 0 токенов |

### Умное расписание рефлексии

```
Дни без рефлексии:  1  2  3  4  5  6  7  8  9  10  ...
Были изменения?     -  -  -  -  -  -  -  -  ✓  -   ...
                                              ↑
                                     Запуск! (>7 дней + есть изменения)
```

- Если **≤7 дней** → не запускать (ещё рано)
- Если **>7 дней**, но **нет изменений** → не запускать, продолжить считать (10, 15, 20...)
- Если **>7 дней** и **есть изменения** → запустить, обнулить маркер
- Если **importance threshold** достигнут → **запустить немедленно** (вне зависимости от дней)

Последний пункт важен: при активной работе с базой рефлексия запустится раньше 7 дней, предотвращая застой.

### Гарантии

- Консолидация **не чаще раза в сутки** (маркер `.last_consolidation`)
- Срабатывает при **любом** вызове `reindex.sh` — ручном, из watcher, из git hook
- Если ПК был выключен 3 дня — при первом reindex выполнит консолидацию
- Не блокирует основной reindex — lint и reflection запускаются **до** repomix

---

## Таблица триггеров

| Событие | Действие | Кто запускает |
|---------|---------|--------------|
| Новый файл в `raw/*/unsorted/` | Ingest → NLP → Process → Reindex | `./watcher.sh` |
| Файл изменён в `knowledge/` | Reindex + Quick lint | `./watcher.sh` или git hook |
| `!save` в AI-сессии | Session capture (с enrichment) → Reindex | AI-агент |
| `!reflect` | Рефлексия: генерация insights (~15K токенов) | AI-агент |
| `!audit` | Lint уровня 2: AI-ревью (~50-100K токенов) | AI-агент |
| Lint нашёл и исправил issues | Reindex | `kb_lint.py --fix` |
| AI сделал query-writeback | Write page → Reindex | AI-агент |
| Commit в git | Quick lint + Reindex | git hook |
| Ежедневно | Full lint (Python) + Reindex | cron |
| При reindex (>24ч) | Consolidation (lint + NLP batch + reflection indicator) | `reindex.sh` |
| При reindex (>7д) | Weekly reflection (LLM insights) | `reindex.sh` |

---

## Конфигурация в `kb.config.yml`

```yaml
autorun:
  watch_enabled: true
  watch_dirs:
    - "raw/*/unsorted/"
    - "knowledge/"
  debounce_raw_seconds: 5
  debounce_knowledge_seconds: 2
  auto_nlp: true                    # NLP enrichment при ingest
  auto_lint_on_change: true         # Quick lint при изменении knowledge/
  auto_reindex_on_change: true      # Reindex при изменении knowledge/
  complexity_auto_threshold: 0.5    # Ниже → auto-extract, выше → review
  consolidation_interval_hours: 24  # Минимальный интервал между консолидациями
  consolidation_on_reindex: true    # Проверять при каждом reindex
```

---

## Интеграция

- **03_PIPELINE:** watch вызывает ingest при новом файле; surprise filter проверяет дупликаты
- **05_INDEX:** watch вызывает reindex при изменениях
- **07_INTERACTION_LOOP:** консолидация проверяет reflection threshold и запускает insights
- **09_LINT:** watch → quick lint; консолидация → полный lint с compression caps
- **10_LOG:** все авто-операции записываются в log.md, включая consolidation
- **11_PROVENANCE:** консолидация обновляет recency scores и проверяет bi-temporal validity
- **12_NLP:** watch запускает NLP при ingest; консолидация — batch re-enrichment
