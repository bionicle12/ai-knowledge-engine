---
translation_of: knowledge-base/05_INDEX.md
source_commit: e497375d391668b75c4fefdddae3dde4d3e200c5
source_version: 0.15.0
translated_at: 2026-08-23
translator: ai-assisted
---

# 05 — Индексация и Repomix

> Настройка Repomix-индекса: что индексируется, что исключается, автообновление.
>
> **Reference template:** `knowledge-base/templates/repomix.config.json.template`. Агент копирует его в корень развёрнутой базы как `repomix.config.json` и при необходимости параметризует.
> **Reference shell-скрипт:** `knowledge-base/shell/reindex.sh` копируется в `shell/reindex.sh` в развернутой базе.

---

## Принцип: только чистые данные

В Repomix-индекс попадают **только**:
- `knowledge/**/*.md` — извлечённые знания
- `assets-index/**/*.md` — описания бинарных файлов
- Мета-файлы: `README.md`, `KNOWLEDGE_STRUCTURE.md`, `kb.config.yml`

**НЕ индексируются:** `raw/`, `processed/`, `assets/`, `review/`, `interactions/`, `setup/`, `scripts/`, **и `AGENTS.md`** — он и так загружен в системный промпт каждой сессии; его индексация тарифицирует те же токены дважды.

---

## Принцип: пакеты, а не монолит

Один `.repomix/output.xml` перестаёт работать, как только база вырастает:
база с библиотекой учебных книг легко переваливает за 150–250K токенов,
которые уже не влезают в 256K-окно контекста *ещё до начала сессии*, а
инструкция «прочитай индекс для широкого контекста» превращается в отравление
контекста. Длинные чаты деградируют — модель заметно «теряет нить».

Поэтому индекс собирается **семантическими пакетами**, каждый под потолком
токенов:

| Профиль окна | Потолок пакета |
|--------------|---------------|
| `400k` (Codex) | 120K |
| `256k` (Cursor / консервативный дефолт) | 80K |
| `200k` | 60K |
| `1m` (Claude Code 1M) | 150K |

- `core.xml` — профиль автора, принципы, голос, таблицы маршрутизации,
  мета-файлы. Маленький по замыслу; грузить безопасно всегда.
- По пакету на каждую секцию `knowledge/` (`domain.xml`, `insights.xml`, …).
- Секция **сверх потолка автоматически режется по подпапкам**:
  `knowledge/library/craft/` → `library-craft.xml` и т.д. Библиотека
  справочных книг никогда не делит пакет с рабочими знаниями — книжные
  пакеты грузятся только когда задача о них.
- Секции меньше ~15K склеиваются в общий `aux.xml` (маршрутизация между
  двадцатью микрофайлами так же вредна, как один гигантский файл).
- `.repomix/PACKS_STATUS.md` — автогенерируемая таблица пакетов со свежими
  оценками токенов; агенты читают её вместо захардкоженных чисел.
- `.repomix/audit/<pack>__request.md` — бриф `!audit` на пакет (новая сессия,
  нужны `file:line` + цитата) и `CROSS_PACK__request.md` (только заголовки).

Правило загрузки для агента (уже в шаблоне AGENTS.md): маршрутизируйся через
`knowledge/routing-table.md`, затем грузи `core` плюс **максимум один**
доменный пакет на задачу.

Конфигурация живёт в секции `index:` файла `kb.config.yml`
(см. `templates/kb.config.yml.template`): `window_profile`, опциональные
переопределения `pack_token_ceiling` / `merge_below_tokens` и `packs: auto`
(рекомендуется) либо явный список пакетов. `kb_reindex.py` планирует пакеты,
генерирует `.repomix/configs/<pack>.json` из базового `repomix.config.json`,
пересобирает только устаревшие пакеты (skip по mtime) и **предупреждает,
когда пакет превышает потолок** — это сигнал резать дальше (глубже по
подпапкам или явным списком `packs:`).

Базы, развёрнутые до пакетного режима, продолжают работать: без секции
`index:` `kb_reindex.py` собирает старый монолитный `output.xml` и громко
предупреждает, когда тот переваливает ~150K токенов, советуя включить пакеты.

---

## Почему `compress: false` здесь не обсуждается

Для **кода** Tree-sitter-сжатие — честная сделка: структура выживает, тела
методов уходят — агент дочитает детали в реальных исходниках.

Для **базы знаний текст И ЕСТЬ полезная нагрузка**: формулировки, нюансы,
целые абзацы извлечённых знаний. Сжатие ампутировало бы ровно то, ради чего
база существует. Поэтому каждый KB-пакет сохраняет
`compress: false, removeComments: false` — а проблема размера решается
**более жёсткой нарезкой** (пакеты, разбивка по подпапкам), но никогда
сжатием.

---

## repomix.config.json (базовый конфиг)

В пакетном режиме этот файл — **базовый конфиг**: `kb_reindex.py` наследует
его `ignore` / `security` / `tokenCount` и output-опции в каждый
сгенерированный `.repomix/configs/<pack>.json`, переопределяя только
per-pack `include`, `filePath` и заголовок. Его собственные
`include`/`filePath` используются напрямую только в legacy-режиме (без секции
`index:`).

Полная эталонная копия — `templates/repomix.config.json.template`. Ключевые
моменты в любом режиме:

- `compress: false`, `removeComments: false` — см. секцию выше.
- `ignore.customPatterns` исключает `raw/`, `processed/`, `assets/`,
  `review/`, `interactions/`, `eval/`, `.kb-backups/`, `setup/`, `scripts/`,
  `.repomix/`, логи
  и все бинарные форматы.
- `tokenCount.encoding: o200k_base`.
- Legacy `include` исторически содержит `AGENTS.md`; пакетный режим его
  выбрасывает (уже в системном промпте).

---

## shell/reindex.sh

Эталонный скрипт `knowledge-base/shell/reindex.sh` (копируется в развёрнутую
базу) выполняет: ingest → routing → quick lint → троттлированная
консолидация → **`kb_reindex.py --index-only`**, который собирает пакеты
(или legacy-монолит, если пакеты не настроены). На Windows —
`shell/reindex.bat`, он делегирует в тот же `kb_reindex.py` — идентичное
поведение, Git Bash не нужен.

Ручная пересборка только индекса:

```bash
python3 scripts/kb_reindex.py --index-only            # только устаревшие пакеты
python3 scripts/kb_reindex.py --index-only --force    # всё
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
