---
translation_of: knowledge-base/05_INDEX.md
source_commit: aaccaf31fb920a2191b427fb629ad6ac3ac70330
source_version: 0.9.1
translated_at: 2026-05-17
translator: human
---

# 05 — Индексация и Repomix

> Настройка Repomix-индекса: что индексируется, что исключается, автообновление.
>
> **Reference template:** `knowledge-base/templates/repomix.config.json.template`. Агент копирует его в корень развёрнутой базы как `repomix.config.json` и при необходимости параметризует.
> **Reference shell-скрипт:** `knowledge-base/shell/reindex.sh` копируется как `reindex.sh` в корень базы.

---

## Принцип: только чистые данные

В Repomix-индекс попадают **только**:
- `knowledge/**/*.md` — извлечённые знания
- `assets-index/**/*.md` — описания бинарных файлов
- Мета-файлы: `AGENTS.md`, `README.md`, `KNOWLEDGE_STRUCTURE.md`, `kb.config.yml`

**НЕ индексируются:** `raw/`, `processed/`, `assets/`, `review/`, `interactions/`, `setup/`, `scripts/`.

---

## repomix.config.json

```json
{
  "$schema": "https://repomix.com/schemas/latest/schema.json",
  "output": {
    "filePath": ".repomix/output.xml",
    "style": "xml",
    "compress": false,
    "removeComments": false,
    "removeEmptyLines": false,
    "showLineNumbers": false,
    "fileSummary": true,
    "directoryStructure": true,
    "topFilesLength": 20,
    "headerText": "Локальная non-code knowledge base. Прочитай AGENTS.md перед использованием."
  },
  "include": [
    "AGENTS.md",
    "README.md",
    "KNOWLEDGE_STRUCTURE.md",
    "DATA_PLACEMENT_EXAMPLES.md",
    "kb.config.yml",
    "knowledge/**/*.md",
    "assets-index/**/*.md"
  ],
  "ignore": {
    "useGitignore": true,
    "useDefaultPatterns": true,
    "customPatterns": [
      "raw/**",
      "processed/**",
      "assets/**",
      "review/**",
      "interactions/**",
      "setup/**",
      "scripts/**",
      ".repomix/**",
      ".venv/**",
      "__pycache__/**",
      "log.md",
      "log-archive/**",
      "lint-report.md",
      "**/*.pdf", "**/*.docx", "**/*.pptx", "**/*.xlsx",
      "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp", "**/*.gif",
      "**/*.mp3", "**/*.wav", "**/*.mp4", "**/*.mov",
      "**/*.zip", "**/*.tar.gz", "**/*.rar"
    ]
  },
  "security": {
    "enableSecurityCheck": true
  },
  "tokenCount": {
    "encoding": "o200k_base"
  }
}
```

`compress: false` — для текстовых знаний важны формулировки и нюансы.

---

## reindex.sh

```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

PYTHON="python3"
if [ -f ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
fi

echo "Запуск ingest-пайплайна..."
$PYTHON scripts/kb_ingest.py

echo "Quick lint..."
$PYTHON scripts/kb_lint.py --quick || true

echo "Генерация Repomix-индекса..."
repomix

# Запись в лог
echo "" >> log.md
echo "## [$(date -Iseconds)] reindex | Auto reindex" >> log.md
echo "- Output: .repomix/output.xml" >> log.md

echo "Готово: .repomix/output.xml"
```

```bash
chmod +x reindex.sh
```

---

## Git hooks и автозапуск

См. `13_AUTORUN.md` — подробные инструкции по автоматическому запуску:
- File watcher (watchdog daemon)
- Git hooks (post-commit, pre-commit)
- Cron (периодический lint + reindex)

---

## Cross-references: конвенция `[[wikilinks]]`

Все файлы в `knowledge/` могут ссылаться друг на друга через wikilinks:

```markdown
# Пример в knowledge/domain/caching.md
Мы используем [[DragonflyDB]] как Redis-совместимый кеш (см. [[infrastructure-decisions]]).
Отказались от [[NATS]] в пользу Redis pub/sub (см. [[decisions/2026-03__no-nats]]).
```

### Формат ссылок

| Формат | Резолвится в |
|--------|-------------|
| `[[slug]]` | Поиск `slug.md` по всем подпапкам `knowledge/` |
| `[[domain/caching]]` | Точный путь: `knowledge/domain/caching.md` |
| `[[decisions/2026-03__no-nats]]` | Точный путь: `knowledge/decisions/2026-03__no-nats.md` |

### Правила

1. Slug — это имя файла без `.md`
2. При конфликте slug (файлы с одинаковым именем в разных папках) — использовать полный путь
3. `kb_lint.py` проверяет валидность всех wikilinks
4. Несуществующие ссылки — lint error
5. AI-агент при создании/обновлении knowledge/ страниц **обязан** добавлять wikilinks на связанные страницы

### Автоматическая инъекция (опционально)

Python-скрипт может предлагать wikilinks:
```python
def suggest_wikilinks(text: str, knowledge_slugs: dict) -> list:
    """Находит упоминания entity names из knowledge/ и предлагает обернуть в [[]]."""
```

---

## Routing tables: навигация для масштабированных баз

Когда `knowledge/` содержит > 50 файлов, плоский индекс становится context dump. Routing tables — двухуровневая навигация.

### `knowledge/routing-table.md` (верхний уровень)

```markdown
# Routing Table

## Domains
- [[rt/infrastructure]] — Docker, Traefik, DB, caching, networking
- [[rt/game-logic]] — clicks, settlements, economy, events, corps
- [[rt/frontend]] — React, PixiJS, HUD, biomes, scenes, i18n
- [[rt/auth]] — providers, sessions, JWT, brute-force, audit
- [[rt/devops]] — CI/CD, monitoring, deployment, backups

## Meta
- [[rt/profile]] — кто автор, экспертиза, предпочтения
- [[rt/principles]] — рабочие принципы, критерии качества
- [[rt/decisions-log]] — хронология ключевых решений
```

### `knowledge/routing/rt-infrastructure.md` (второй уровень)

```markdown
# Infrastructure

## Ключевые страницы
- [[domain/docker-swarm]] — почему Swarm, а не K8s
- [[domain/caching]] — DragonflyDB, паттерны кеширования
- [[domain/database]] — PostgreSQL 16, миграции, индексы

## Смежные области
- → [[rt/devops]] для CI/CD и мониторинга
- → [[rt/auth]] для инфраструктуры аутентификации
```

### Навигация AI-агента

1. Читает `routing-table.md` (~20 строк)
2. Определяет нужную тему → переходит к routing page
3. Находит конкретные страницы → читает их
4. **3 хопа** вместо чтения всего индекса

Routing table создаётся и поддерживается AI-агентом. Lint проверяет, что все ссылки в routing table валидны.
