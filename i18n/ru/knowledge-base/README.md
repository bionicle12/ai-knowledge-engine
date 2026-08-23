---
translation_of: knowledge-base/README.md
source_commit: d82f0395afa7e65a0d84b4ba78f99701048f2bfe
source_version: 0.12.0
translated_at: 2026-08-13
translator: ai-assisted
---

# Non-Code Knowledge Base — Модульные инструкции

> **Для кого:** AI-агент (Codex, Claude, GPT, Cursor), которому нужно развернуть и поддерживать локальную базу знаний специалиста.

## Что это

Набор инструкций для построения **Raw-First Knowledge Pipeline** — системы, в которой:

1. Пользователь складывает сырые материалы в `raw/`
2. Python-скрипт конвертирует их, запускает NLP-обогащение и записывает метаданные
3. Сложные материалы попадают в AI review queue
4. Чистые знания с provenance индексируются через Repomix
5. AI-агент учится на каждой рабочей сессии через feedback loop
6. Lint следит за здоровьем базы, а autorun обновляет её по изменениям

## Порядок чтения

AI-агент должен читать модули **строго в этом порядке**:

| # | Файл | Что покрывает |
|---|------|---------------|
| 0 | `00_OVERVIEW.md` | Карта развёртывания: что читать, что копировать, в каком порядке (read first) |
| 1 | `01_PREREQUISITES.md` | Проверка окружения: Node.js, Python, Git, Repomix |
| 2 | `02_INIT.md` | Уточнение роли, выбор сущностей, создание структуры |
| 3 | `03_PIPELINE.md` | Контракт Python pipeline: ingest + NLP enrichment + source hash |
| 4 | `04_REVIEW.md` | AI review workflow для сложных материалов |
| 5 | `05_INDEX.md` | Repomix, `[[wikilinks]]`, routing tables |
| 6 | `06_AGENTS_TEMPLATE.md` | Шаблон `AGENTS.md` для развернутой базы |
| 7 | `07_INTERACTION_LOOP.md` | Self-learning + Query → Wiki Writeback |
| 8 | `08_PORTABLE.md` | Портабельность + Dynamic Context Enrichment |
| 9 | `09_LINT.md` | Health check: stale pages, сироты, битые ссылки, contradictions |
| 10 | `10_LOG.md` | Append-only хронология операций (`log.md`) |
| 11 | `11_PROVENANCE.md` | Source hash, span-level citations, regression tests |
| 12 | `12_NLP_PREPROCESS.md` | NER + keyword extraction + entity resolution перед LLM |
| 13 | `13_AUTORUN.md` | File watcher, git hooks, cron — автоматическая обработка |
| 14 | `14_INITIAL_POPULATION.md` | Генерация role-specific `DATA_PLACEMENT_EXAMPLES.md` |
| 15 | `15_MEDIA_PROCESSING.md` | Транскрибация (STT), OCR, архивы — из коробки, на всех платформах |
| 16 | `16_MERGE.md` | Импорт/экспорт между базами: слияние двух развёртываний без потери знаний |

Конфигурации ролей: `examples/`.
Готовые шаблоны для копирования и параметризации: `templates/`.
Reference Python и shell scripts: `scripts/` и `shell/`.

> 🌍 **Английский оригинал:** [`knowledge-base/README.md`](../../../knowledge-base/README.md). Полный набор русских переводов лежит в `i18n/ru/`.
> Дрейф между языками отслеживается в `i18n/TRANSLATION_STATUS.md`.

## Основные принципы

- **Raw-first:** сначала ingest сырья, потом извлечение знаний
- **Markdown-first:** LLM читает `.md`, а не бинарные оригиналы
- **Local-first:** обработка идёт локально через Python + NLP
- **Clean index only:** Repomix индексирует только `knowledge/` и `assets-index/`
- **Provenance:** каждый факт привязан к источнику (source hash, span citations)
- **Self-learning:** база улучшается через feedback loop и query writeback
- **Cross-linked:** `[[wikilinks]]` связывают знания, routing tables масштабируют навигацию
- **Auto-maintained:** watcher + lint + autorun держат базу свежей
- **Privacy-by-default:** raw data и review queues никогда не индексируются

## Быстрый старт для пользователя

```text
1. Создайте пустую папку проекта
2. Скопируйте эту папку (knowledge-base/) в корень проекта
3. Откройте проект в IDE с AI-агентом (Codex, Cursor и т. п.)
4. Скажите агенту: "Read knowledge-base/README.md and deploy a knowledge base for [my role]"
5. Агент проверит окружение, задаст вопросы и создаст структуру
6. Начинайте работу: складывайте файлы в raw/
7. Запустите watcher: ./shell/watcher.sh
   (или вручную: ./shell/reindex.sh)
```

## Команды пользователя

То, что можно говорить AI-агенту в IDE:

| Команда | Что делает | Стоимость | Когда использовать |
|---------|------------|-----------|--------------------|
| `!view` | Запускает или повторно открывает локальный read-only граф знаний | 0 токенов | Чтобы без AI просматривать страницы, связи, метаданные, полнотекстовый поиск и панель здоровья (сироты, битые ссылки, устаревшие, неоднозначные) |
| `!save` | Сохраняет session summary с выводами и обработанными материалами | ~2K токенов | В конце продуктивной сессии или когда накопились полезные выводы |
| `!reflect` | Запускает рефлексию: синтез higher-level insights из накопленных фактов | ~15K токенов | Когда в базе появилось много нового материала |
| `!audit` | AI review базы: contradictions, gaps, merge candidates | ~50–100K токенов | Раз в 2–4 недели |
| `!review` | Разбирает очереди `review/`, извлекает durable knowledge, редактирует чувствительные материалы и спрашивает только точечные вопросы, если они нужны | ~5–30K токенов | Когда накапливается `review/needs-ai-decision/` |
| `!populate` | Перегенерирует `DATA_PLACEMENT_EXAMPLES.md` из role YAML | ~50 токенов | После редактирования `examples/<role>.yml` |
| `!super` | Переключает режим: default ↔ super | 0 токенов | Когда нужна максимальная скорость обучения |
| `!super on/off` | Явно включает или выключает super mode | 0 токенов | См. ниже |
| `!super status` | Показывает текущий режим | 0 токенов | Быстрая проверка |

### Когда это уместно

- **`!view`** — когда нужно посмотреть, что уже находится в `knowledge/`, или разобрать здоровье базы: чипы здоровья + очередь исправлений показывают каждую сироту, битую ссылку, устаревшую или неоднозначную страницу со строкой-источником и кнопкой «открыть файл»; встроены полнотекстовый поиск, фокус на 1–3 хопа, кратчайший путь между двумя страницами и состояние UI в URL. `!view status` показывает URL, а `!view stop` останавливает локальный сервер
- **`!save`** — после любой продуктивной сессии от 45+ минут, где обсуждались документы, принимались решения или анализировались данные
- **`!reflect`** — после серии добавлений в базу (5+ новых страниц), перед важным стратегическим решением, или когда система сама говорит "пора"
- **`!audit`** — когда базу давно не проверяли (2+ недели) или перед большим блоком работы

### Когда это не имеет смысла

- **`!save`** — если сессия была тривиальной и без новых данных
- **`!reflect`** — если с прошлой рефлексии ничего не изменилось; система это проверит и пропустит
- **`!audit`** — если база совсем маленькая (<20 страниц) или только что создана

## Режимы работы

Система поддерживает два режима, переключаемых через `!super`:

| Режим | Парадигма | Токены/день | Лучше для |
|------|-----------|------------:|-----------|
| `default` | Python-first, throttled | ~3-4K | Ограниченный бюджет, повседневная работа |
| `super` | AI-first, on-demand | ~50-200K+ | Безлимитный план, интенсивное накопление знаний |

**default** использует Python (NLP, эвристики) для surprise filter, annotations и entity resolution. Reflection и audit идут по расписанию.

**super** заменяет Python-эвристики AI-анализом: semantic surprise, substantive annotations, on-demand reflection и auto-processed review queue. Это максимальная скорость и качество обучения.

> ⚠️ **Super mode** может израсходовать дневной лимит токенов за одну активную сессию. Используйте только с безлимитными AI-планами.

### Автоматические триггеры

| Что | default | super |
|------|---------|-------|
| Surprise filter | Python NLP (0 tok) | AI semantic (~2-5K tok) |
| Annotations | Python templates (0 tok) | AI substantive (~1-3K tok) |
| Entity resolution | Python fuzzy (0 tok) | AI semantic (~500-1K tok) |
| Importance scoring | LLM score (~500 tok) | LLM score + reasoning (~1-2K tok) |
| Reflection | ≥7 дней + изменения (~15K) | После каждого importance≥5 (~15K) |
| Lint L2 | Только на `!audit` | Авто при консолидации (24h) |
| Review queue | Ручной запуск | Автообработка |
| Lint L1 (Python) | При reindex >24ч (0 tok) | При reindex >24ч (0 tok) |
| NLP enrichment | На каждом ingest (0 tok) | На каждом ingest (0 tok) |
