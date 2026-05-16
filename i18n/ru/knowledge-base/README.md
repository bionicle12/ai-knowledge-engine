---
translation_of: knowledge-base/README.md
source_commit: 1237e839a201180ed4cfa249a370365be0f63c37
source_version: 0.8.1
translated_at: 2026-05-16
translator: human
---

# Non-Code Knowledge Base — Модульная инструкция

> **Для кого:** AI-агент (Codex, Claude, GPT, Cursor), который должен развернуть и поддерживать локальную базу знаний специалиста.

## Что это

Набор инструкций для создания **Raw-First Knowledge Pipeline** — системы, где:

1. Пользователь складывает сырые материалы в `raw/`
2. Python-скрипт конвертирует, прогоняет NLP-обогащение и записывает метаданные
3. Сложные материалы попадают в очередь AI-ревью
4. Чистые знания с provenance индексируются через Repomix
5. AI-агент учится на процессе работы через feedback loop
6. Lint следит за здоровьем базы, autorun обновляет по изменениям

## Порядок чтения

AI-агент должен читать файлы **строго в этом порядке**:

| # | Файл | Что делает |
|---|------|------------|
| 0 | `00_OVERVIEW.md` | Карта развёртывания: что копировать, в каком порядке (read first) |
| 1 | `01_PREREQUISITES.md` | Проверка окружения: Node.js, Python, Git, Repomix |
| 2 | `02_INIT.md` | Уточнение роли, выбор сущностей, создание структуры |
| 3 | `03_PIPELINE.md` | Контракт Python-скрипта: ingest + NLP enrichment + source hash |
| 4 | `04_REVIEW.md` | Workflow AI-ревью сложных материалов |
| 5 | `05_INDEX.md` | Repomix, `[[wikilinks]]`, routing tables |
| 6 | `06_AGENTS_TEMPLATE.md` | Шаблон `AGENTS.md` для готовой базы |
| 7 | `07_INTERACTION_LOOP.md` | Self-learning + Query → Wiki Writeback |
| 8 | `08_PORTABLE.md` | Портабельность + Dynamic Context Enrichment |
| 9 | `09_LINT.md` | Health-check: stale pages, orphans, broken links, contradictions |
| 10 | `10_LOG.md` | Append-only хронология всех операций (`log.md`) |
| 11 | `11_PROVENANCE.md` | Source hash, span-level citations, regression tests |
| 12 | `12_NLP_PREPROCESS.md` | NER + keyword extraction + entity resolution перед LLM |
| 13 | `13_AUTORUN.md` | File watcher, git hooks, cron — авто-обработка |
| 14 | `14_INITIAL_POPULATION.md` | Генерация role-specific `DATA_PLACEMENT_EXAMPLES.md` |

Примеры конфигов под разные роли — в `examples/`.
Готовые шаблоны для копирования — в `templates/`.
Эталонные Python/shell-скрипты — в `scripts/` и `shell/`.

> 🌍 **English version (canonical):** [`knowledge-base/README.md`](../../../knowledge-base/README.md). Английская версия — основной источник; русский — перевод. Дрейф между языками отслеживается в `i18n/TRANSLATION_STATUS.md`.

## Главные принципы

- **Raw-first:** сначала принимаем сырые материалы, затем извлекаем знания
- **Markdown-first:** LLM читает `.md`, а не бинарные оригиналы
- **Local-first:** обработка выполняется локально через Python + NLP
- **Clean index only:** Repomix индексирует только `knowledge/` и `assets-index/`
- **Provenance:** каждое знание прослеживается до оригинала (source hash, span citations)
- **Self-learning:** база улучшается через feedback loop + query writeback
- **Cross-linked:** `[[wikilinks]]` связывают знания, routing tables масштабируют навигацию
- **Auto-maintained:** watchdog + lint + autorun держат базу актуальной
- **Privacy-by-default:** сырые данные и ревью не индексируются

## Быстрый старт для пользователя

```text
1. Создать пустую папку проекта
2. Скопировать эту папку (knowledge-base/) в корень проекта
3. Открыть проект в IDE с AI-агентом (Codex, Cursor, etc.)
4. Сказать агенту: "Прочитай knowledge-base/README.md и разверни базу знаний для [моя роль]"
5. Агент проверит окружение, задаст вопросы, создаст структуру
6. Начать работу: кидать файлы в raw/
7. Запустить watch mode: ./watcher.sh
   (или вручную: ./reindex.sh)
```

## Команды пользователя

Команды, которые можно сказать AI-агенту в IDE:

| Команда | Что делает | Стоимость | Когда использовать |
|---------|-----------|-----------|-------------------|
| `!save` | Сохранить session summary с выводами и обработанными материалами | ~2K токенов | В конце рабочей сессии или при накоплении полезных выводов |
| `!reflect` | Рефлексия: синтезировать higher-level insights из накопленных фактов | ~15K токенов | Когда много нового в базе |
| `!audit` | AI-ревью базы: противоречия, пробелы, кандидаты на объединение | ~50-100K токенов | Раз в 2-4 недели |
| `!super` | Переключить режим: default ↔ super | 0 токенов | Когда нужна максимальная скорость обучения |
| `!super on/off` | Явно включить/выключить super mode | 0 токенов | См. ниже |
| `!super status` | Показать текущий режим | 0 токенов | Проверка |

### Когда есть смысл

- **`!save`** — после любой продуктивной сессии (45+ мин), где обсуждали документы, принимали решения, анализировали данные
- **`!reflect`** — после серии добавлений в базу (5+ новых страниц), перед важным стратегическим решением, или когда система сама говорит «пора»
- **`!audit`** — когда давно не проверяли базу (2+ недели), или перед масштабной работой, чтобы убедиться что контекст чистый

### Когда НЕТ смысла

- **`!save`** — если сессия была тривиальной (простые вопросы, без новых данных)
- **`!reflect`** — если с последней рефлексии ничего не изменилось. Система это проверяет автоматически и пропустит
- **`!audit`** — если база маленькая (<20 страниц) или только что создана — ещё не накопилось противоречий

## Операционные режимы (Operating Modes)

Система поддерживает два режима работы, переключаемых командой `!super`:

| Mode | Парадигма | Токены/день | Лучше для |
|------|-----------|------------|----------|
| `default` | Python-first, throttled | ~3-4K | Ограниченный бюджет, ежедневная работа |
| `super` | AI-first, on-demand | ~50-200K+ | Безлимитный план, интенсивное накопление знаний |

**default** использует Python (NLP, эвристики) для surprise filter, аннотаций и entity resolution. Рефлексия и audit — по расписанию.

**super** заменяет Python-эвристики на AI-анализ: семантический surprise, содержательные аннотации, on-demand рефлексия, авто-обработка review queue. Максимальная скорость и качество обучения.

> ⚠️ **Super mode** может исчерпать дневной лимит токенов за одну активную сессию. Используйте только с безлимитными планами AI.

### Автоматические триггеры (не нужно запускать вручную)

| Что | default | super |
|-----|---------|-------|
| Surprise filter | Python NLP (0 tok) | AI семантический (~2-5K tok) |
| Annotations | Python шаблоны (0 tok) | AI содержательные (~1-3K tok) |
| Entity resolution | Python fuzzy (0 tok) | AI семантический (~500-1K tok) |
| Importance scoring | LLM score (~500 tok) | LLM score + reasoning (~1-2K tok) |
| Рефлексия | ≥7 дней + changes (~15K) | После каждого importance≥5 (~15K) |
| Lint L2 | Только `!audit` | Авто при консолидации (24h) |
| Review queue | Ручной запуск | Авто-обработка |
| Lint L1 (Python) | При reindex >24ч (0 tok) | При reindex >24ч (0 tok) |
| NLP enrichment | При каждом ingest (0 tok) | При каждом ingest (0 tok) |
