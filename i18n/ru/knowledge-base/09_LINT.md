---
translation_of: knowledge-base/09_LINT.md
source_commit: 1237e839a201180ed4cfa249a370365be0f63c37
source_version: 0.12.0
translated_at: 2026-08-13
translator: ai-assisted
---

# 09 — Lint: периодический health-check базы знаний

> Операция lint проверяет здоровье **существующей** базы. В отличие от review (04), который обрабатывает входящие материалы, lint анализирует то, что уже находится в `knowledge/`.
>
> **Reference implementation:** `knowledge-base/scripts/kb_lint.py`. Агент копирует этот скрипт на этапе развёртывания.

---

## Зачем

База знаний деградирует без обслуживания: факты устаревают, страницы теряют связи, появляются противоречия. Lint выявляет эти проблемы до того, как AI-агент начнёт давать ответы на основе stale data.

---

## Два уровня проверки

### Уровень 1: Автоматический (Python)

Выполняется `scripts/kb_lint.py` — детерминированные проверки без LLM.

| Проверка | Что делает | Severity |
|----------|-----------|----------|
| **Frontmatter integrity** | Все файлы в `knowledge/` имеют обязательные поля: `source`, `extracted_at`, `tags`, `lifecycle` | 🔴 error |
| **Stale pages** | `last_verified` старше 30 дней. **Пропускает** `lifecycle: permanent` | 🟡 warning |
| **Broken wikilinks** | `[[slug]]` ведёт на несуществующий файл | 🔴 error |
| **Orphan pages** | Страницы без единого входящего `[[wikilink]]` из других страниц | 🟡 warning |
| **Source hash mismatch** | `source_hash` не совпадает с hash файла в `assets/`. **Пропускает** `lifecycle: permanent` | 🔴 error |
| **Empty categories** | Подпапки `knowledge/` без единого `.md` файла | 🟡 warning |
| **Superseded chains** | Файл A `supersedes: B`, но B не в `_archive/`. **Не трогает** `lifecycle: permanent` | 🟡 warning |
| **Duplicate slugs** | Два файла с одинаковым slug в разных подпапках | 🔴 error |
| **Citation validity** | Span-level citations ссылаются на существующие файлы/строки | 🟡 warning |
| **Domain overflow** | Подпапка `knowledge/` содержит > 15 `.md` файлов → предложить consolidation | 🟡 warning |
| **Low importance + stale** | `importance < 3` + `lifecycle: temporal` + `last_accessed > 90 дней` → предложить архивировать | ℹ️ info |
| **Annotation overflow** | Файл имеет > 5 `context_annotations` → предложить создать insight | ℹ️ info |
| **Expired temporal** | `valid_until != null` + `valid_until < now` + файл не в `_archive/` | 🟡 warning |

### Уровень 2: AI-ревью (LLM) — mode-aware

> ⚠️ **Стоимость:** 50-100K токенов на полный прогон (все knowledge/ файлы в контексте).

#### `mode: default`
- Запускается **только** по команде `!audit` или еженедельно
- Не чаще раза в неделю

#### `mode: super`
- Запускается **автоматически** при каждой консолидации (раз в 24ч)
- AI также автоматически обрабатывает `review/needs-ai-decision/`

```yaml
# В kb.config.yml — управляется через mode_profiles:
lint:
  # default profile:
  level2_trigger: "manual"       # manual | weekly | daily
  level2_weekly_day: "sunday"
  # super profile:
  # level2_trigger: "daily"      # при каждой консолидации
  review_auto_process: false     # default: false, super: true
```

| Проверка | Что делает |
|----------|-----------|
| **Contradictions** | Найти страницы с конфликтующими утверждениями |
| **Missing cross-refs** | Страницы на похожие темы без ссылок друг на друга |
| **Data gaps** | Области, где знаний недостаточно для уверенных ответов |
| **Consolidation candidates** | Страницы, которые стоит объединить |
| **Freshness recommendations** | Какие страницы стоит перепроверить/обновить |



## Формат lint-report

```markdown
# Lint Report — 2026-05-06

## Summary
- Total pages: 42
- Errors: 3
- Warnings: 7
- Info: 2

## 🔴 Errors

### [FRONTMATTER] knowledge/domain/caching.md
Missing required field: `extracted_at`

### [BROKEN_LINK] knowledge/principles/architecture.md:15
Link [[infrastructure-scaling]] → file not found

### [SOURCE_HASH] knowledge/domain/redis-patterns.md
source_hash mismatch: expected sha256:a1b2c3, actual sha256:d4e5f6
→ Source file was updated, knowledge page may be stale

## 🟡 Warnings

### [STALE] knowledge/projects/highway-clicker.md
last_verified: 2026-03-15 (52 days ago, threshold: 30)

### [ORPHAN] knowledge/domain/nats-evaluation.md
No inbound [[wikilinks]] from any page

### [EMPTY_CATEGORY] knowledge/timelines/
No .md files in this category

## ℹ️ Info

### [SUPERSEDED] knowledge/decisions/2026-01__initial-db-choice.md
Superseded by knowledge/decisions/2026-03__postgres-migration.md
Consider moving to knowledge/_archive/
```

---

## Контракт `scripts/kb_lint.py`

```python
"""
kb_lint.py — Automated health-check for knowledge base.

Usage:
    python3 scripts/kb_lint.py                          # Full lint
    python3 scripts/kb_lint.py --quick                  # Only errors
    python3 scripts/kb_lint.py --fix                    # Auto-fix where possible
    python3 scripts/kb_lint.py --output report          # Write to lint-report.md
    python3 scripts/kb_lint.py --only frontmatter       # Run a subset of checks
    python3 scripts/kb_lint.py --json                   # Machine-readable output

Exit codes:
    0 — no errors
    1 — warnings only
    2 — errors found
"""
```

### Auto-fix capabilities

С флагом `--fix` скрипт может:
- Добавить недостающие frontmatter-поля с дефолтными значениями (lifecycle default: `evolving`)
- Обновить `last_verified` для проверенных страниц
- Переместить superseded файлы в `knowledge/_archive/` (**только** `evolving`/`temporal`, **не** `permanent`)
- Удалить broken wikilinks (заменить на plain text)

Auto-fix **не может** (требует AI или человека):
- Резолвить противоречия
- Создавать cross-references
- Принимать решения об удалении/объединении
- Изменять `lifecycle` без явного запроса пользователя
- Архивировать файлы с `lifecycle: permanent`

---

## Запуск

```bash
# lint.sh — обёртка
#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Running knowledge base lint..."
if [ -f ".venv/bin/python" ]; then
  .venv/bin/python scripts/kb_lint.py "$@"
else
  python3 scripts/kb_lint.py "$@"
fi

# Запись в лог
echo "" >> log.md
echo "## [$(date -Iseconds)] lint | Automated health-check" >> log.md
echo "- Mode: $*" >> log.md
echo "- Report: see lint-report.md" >> log.md
```

```bash
chmod +x lint.sh
```

---

## Рекомендуемая частота

| Режим | Частота | Кто запускает |
|-------|---------|--------------|
| `--quick` | При каждом reindex | Автоматически (в `reindex.sh`) |
| Полный lint | Раз в неделю | Вручную или cron |
| AI-ревью (уровень 2) | Раз в месяц | AI-агент в IDE по запросу |

---

## Интеграция с другими модулями

- **03_PIPELINE:** ingest пишет frontmatter с source_hash → lint проверяет
- **05_INDEX:** lint проверяет wikilinks → index обновляется
- **10_LOG:** каждый lint записывается в `log.md`
- **11_PROVENANCE:** lint проверяет citation validity, source hashes и lifecycle rules
- **13_AUTORUN:** cron/watch запускает `--quick` при изменениях
