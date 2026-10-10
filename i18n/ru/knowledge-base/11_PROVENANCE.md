---
translation_of: knowledge-base/11_PROVENANCE.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 11 — Происхождение источников: откуда берутся знания

> Каждый факт в базе должен быть проверяемым. Происхождение — это цепочка от утверждения в `knowledge/` до конкретного места в исходном документе.

---

## Проблема

> *«LLM Wiki — это сжатие с потерями. Ошибки резюмирования становятся частью базы знаний».*

При извлечении знаний LLM может упрощать нюансы, опускать оговорки или искажать формулировки. Без сведений о происхождении невозможно проверить, откуда взялось утверждение.

---

## Расширенный frontmatter

```yaml
---
source: "assets/documents/2026-05-06__q2-strategy.pdf"
source_hash: "sha256:a1b2c3d4e5f60718"   # sha256: + first 16 hex chars of the original
extracted_at: 2026-05-06
last_verified: 2026-05-06
confidence: high                         # high | medium | low
verification_method: "ai-review"         # manual-review | ai-review
extraction_model: "claude-opus-4"        # which model extracted
lifecycle: "evolving"                    # permanent | evolving | temporal
importance: 8                            # 1-10, value score (see below)
valid_from: 2026-05-06                   # when the fact became true
valid_until: null                        # null = current; a date = true until then
last_accessed: 2026-05-06                # last time the page influenced an answer
access_count: 0                          # how many answers it influenced
tags: [strategy, growth]
supersedes: null
citations:                               # span-level citations
  - claim: "Redis handles 100k ops/s on our profile"
    source_span: "assets/documents/2026-05-06__bench.pdf#page=3&para=2"
    confidence: high
  - claim: "DragonflyDB is 25x faster than Redis"
    source_span: "assets/documents/2026-05-06__dragonfly-bench.md#L15-L28"
    confidence: medium
    note: "Synthetic-load benchmark"
context_annotations: []                  # note evolution from related new knowledge
---
```

Обязательные поля каждой страницы `knowledge/` (lint `frontmatter`): `source`, `extracted_at`, `tags`, `lifecycle`. Всё остальное необязательно. Метаданные ingest (`processed/extracted-metadata/<name>.yml`) уже содержат `source_hash`, `extracted_at`, `valid_from`, значения `lifecycle` и `confidence` по умолчанию — скопируйте их в создаваемую страницу.

---

## Оценка importance — насколько ценно знание

Каждый факт в `knowledge/` получает оценку важности (1-10).

### Шкала

| Балл | Значение | Примеры |
|------|----------|---------|
| 1-2 | Рутинная заметка | «Обновили зависимость», «настроили линтер» |
| 3-4 | Полезное знание | «Паттерн обработки ошибок», «конфигурация Nginx» |
| 5-6 | Значимое знание | «Архитектура слоя кеширования», «результаты A/B-теста» |
| 7-8 | Ключевое знание | «Архитектурное решение с обоснованием», «стратегия роста» |
| 9-10 | Критически важное | «Основополагающий принцип», «ключевой урок из неудачи» |

### Кто выставляет оценку

- **При извлечении** (`!review`, рефлексия): агент оценивает создаваемую страницу — «Насколько это важно для долгосрочной работы? 1 = рутина, 10 = ключевой вывод». Ingest ничего не оценивает.
- **При query-writeback:** агент оценивает по числу синтезированных источников
- **Владелец** может изменить любую оценку

### Как используется

- **Маршрутизация:** при динамической загрузке контекста AI предпочитает страницы с высокой importance
- **Триггер рефлексии:** `kb_reflect.py` учитывает каждую изменённую страницу с весом её `importance` (3, если не задана), а каждый ingest — с весом `importance` из метаданных (1, если не задана); когда сумма с последней рефлексии достигает порога профиля, пора проводить рефлексию (см. `kb-docs/07_INTERACTION_LOOP.md`)
- **Lint `low-importance`** (info): `importance` < 3 + эффективный lifecycle `temporal` + `last_accessed` более 90 дней назад (без `last_accessed`: более поздняя из `last_verified` / `extracted_at`) → предлагает перенести страницу в `_archive/`
- **Бюджет контекста:** при нехватке контекста элементы с низкой importance отбрасываются первыми

---

## Учёт обращений — давность использования

### Убывание актуальности обращения

Когда страница `knowledge/` действительно повлияла на ответ, агент «освежает» её:

```yaml
last_accessed: 2026-05-06    # last time the page influenced an answer
access_count: 12             # how many answers it influenced
```

### Обновление

- **AI-агент:** обновляет `last_accessed` и `access_count += 1`, только если страница действительно повлияла на ответ — не при каждом просмотре или загрузке пака
- Эти два поля изменчивы: `!merge` не считает их изменением содержимого

### Оценка давности

Скрипты её не вычисляют; это принцип ранжирования для агента. Экспоненциальное убывание: `recency_score = 0.995 ^ (hours since last_accessed)`.

### Приоритет маршрутизации

При прочих равных AI предпочитает страницы с **большей** `importance × recency_score`. Формула ранжирования (в духе Generative Agents):

```
priority = importance/10 + recency_score + relevance_to_query
```

Все три компонента нормализованы до 0..1. AI не обязан вычислять формулу, но **принцип** таков: важное + свежее + релевантное → читать первым.

---

## Битемпоральная валидность — факты во времени

### Концепция (Zep/Graphiti)

Каждый факт хранит два момента:
- `valid_from` — когда факт **стал истинным**
- `valid_until` — когда факт **перестал быть истинным** (`null` = всё ещё актуален)

### Пример

```yaml
# knowledge/decisions/2026-01__redis-cache.md
valid_from: 2026-01-15
valid_until: 2026-03-20       # superseded by DragonflyDB
superseded_by: "knowledge/decisions/2026-03__dragonfly-migration.md"

# knowledge/decisions/2026-03__dragonfly-migration.md
valid_from: 2026-03-20
valid_until: null               # current
```

### Правила

- `valid_from` задаётся при извлечении (дата оригинала или `extracted_at`)
- `valid_until` заполняется, когда факт **обновляется или заменяется**
- На вопрос «что было верно в феврале?» AI фильтрует по `valid_from <= feb AND (valid_until IS NULL OR valid_until > feb)`
- Файлы с `valid_until != null` **не удаляются** — это история
- **Lint:** страница с `valid_until` сегодня или позже никогда не считается `stale` (известно, что факт верен до этой даты). Прошедшая `valid_until` не отключает lint: страница `temporal` получает `expired-temporal` до переноса в `_archive/`; для остальных действует обычное правило возраста — архивируйте заменённую историю или оставляйте её там, где она `permanent` (по умолчанию это `decisions/`)

---

## Lifecycle: срок жизни знания

### Типы

| Тип | Значение | Поведение lint | Примеры |
|-----|----------|----------------|---------|
| `permanent` | **Неизменяемое** — не стареет, не деградирует | Никогда не `stale`, без проверки `source-hash`, никогда не предлагается архивирование | Тексты песен, авторский стиль, личные принципы, творческие работы, профиль, решения |
| `evolving` | **Развивающееся** — обновляется по мере изменения реальности | `stale` через `lifecycle.stale_warning_days` (30) без проверки | Технологический стек, рыночные данные |
| `temporal` | **Временное** — привязано к конкретному периоду | `stale` по тому же правилу; `expired-temporal` после `valid_until`; предложение архивирования `low-importance` | Квартальные стратегии, текущие метрики, незавершённые задачи |

**Эффективный lifecycle.** Собственное значение `lifecycle` страницы приоритетно, если отличается от `lifecycle.default` (`evolving`). Отсутствующее значение или значение по умолчанию уступает политике папки `lifecycle.by_folder` в `kb.config.yml` — по умолчанию `decisions/`, `profile/` и `principles/` имеют `permanent` — а иначе используется `lifecycle.default`. Lint и просмотрщик графа применяют одно правило (`kb_common.stale_status`).

### Примеры по категориям

```yaml
# knowledge/voice/songwriting-style.md — voice does not "age"
lifecycle: "permanent"

# knowledge/profile/expertise.md — permanent by folder policy,
# even with the template default:
lifecycle: "evolving"

# knowledge/domain/tech-stack.md — stack can change
lifecycle: "evolving"

# knowledge/decisions/2026-q1__pricing.md — bound to Q1; an explicit
# non-default value beats the folder policy
lifecycle: "temporal"
```

---

## Гарантии сохранности данных

### Никогда не удаляются автоматически

1. **Страницы в `knowledge/`** — ни один скрипт не удаляет страницу, написанную владельцем или агентом. Единственное исключение — сгенерированные страницы: `kb_route.py` удаляет собственную `knowledge/routing/<section>.md` (`generated_by: kb_route.py`), когда раздел перестаёт существовать. `kb_import.py` может переписать страницу при слиянии после резервного копирования (см. `kb-docs/16_MERGE.md`)
2. **Файлы с эффективным lifecycle `permanent`** — защищены от всех предупреждений lint об устаревании
3. **Оригиналы в `assets/`** — неизменяемые, не затрагиваются
4. **Файлы в `raw/`** — ingest удаляет файл из `unsorted/` только после записи его копии в `assets/` и всех производных файлов (при сбое файл остаётся); точный дубликат перемещается в `ingest.duplicates_dir` (`raw/_duplicates/`); игнорируемые, пустые и слишком большие файлы остаются на месте

### Что делает lint для каждого lifecycle

| Проверка lint (`kb-docs/09_LINT.md`) | `permanent` | `evolving` | `temporal` |
|-------------|------------|-----------|-----------|
| `stale` (старше `stale_warning_days`, по умолчанию 30) | ❌ пропускается | ✅ предупреждение | ✅ предупреждение |
| `expired-temporal` (`valid_until` < сегодня, не в `_archive/`) | — | — | ✅ предупреждение |
| `low-importance` (предложение архивирования) | — | — | ✅ info |
| `superseded` (A `supersedes` B, B не в `_archive/`) | ❌ пропускается | ✅ предупреждение | ✅ предупреждение |
| `broken-link` | ✅ проверяется | ✅ проверяется | ✅ проверяется |
| `source-hash` | ❌ пропускается | ✅ проверяется | ✅ проверяется |
| `citation` (файл фрагмента существует; конец `#Lx-Ly` внутри него) | ✅ проверяется | ✅ проверяется | ✅ проверяется |

Lint никогда не меняет `confidence`, не перемещает и не удаляет страницы. `--fix` только добавляет недостающие поля frontmatter.

### Правило: только архивирование, никогда удаление

Удаление файла из `knowledge/` — **только вручную**.

AI-агент **может предложить:**
- Архивировать (`knowledge/` → `knowledge/_archive/`) — для temporal/evolving
- Объединить — для evolving с дубликатами
- Обновить — для evolving с устаревшими данными

AI-агент **не может:**
- Удалять файл из `knowledge/`
- Менять `lifecycle` без явного запроса пользователя
- Понижать lifecycle (`permanent` → `evolving`)
- Архивировать файлы `permanent`

---

## Форматы ссылок на фрагменты

| Формат | Когда |
|--------|-------|
| `file.pdf#page=3&para=2` | PDF-документы |
| `file.md#L15-L28` | Markdown/текст (строки) |
| `file.docx#section=3` | DOCX по разделам |
| `transcript.md#T00:15:30-T00:16:45` | Расшифровки по таймкодам |

Lint `citation` проверяет, что файл каждого `source_span` существует внутри базы; для `#Lx-Ly` также проверяется, что конец фрагмента находится внутри файла. Другие форматы не разбираются.

---

## Хеш источника

`kb_common.compute_source_hash()`: SHA-256 байтов файла, записанный как `sha256:` + первые 16 шестнадцатеричных символов. Ingest записывает его в метаданные; скопируйте в `source_hash` страницы.

**Несовпадение хеша** = оригинал обновился, знание — нет → ошибка lint `source-hash` (отсутствующий файл источника даёт предупреждение). Хеши кешируются в `.kb-state/lint-hash-cache.json` и пересчитываются только при изменении размера или времени модификации файла.
**Исключение:** эффективный lifecycle `permanent` — не проверяется.

Новая версия уже обработанного документа (то же исходное имя, тот же `raw_path` — категория и подпапка — но другое содержимое) проходит ingest как новый ресурс с `previous_version` в метаданных; пакет проверки перечисляет страницы, ссылающиеся на старую версию, чтобы агент мог обновить их `source` / `source_hash`.

---

## Регрессионная проверка: `eval/QUESTIONS.md`

Автоматического файла утверждений нет. Регрессию оценивают вручную: `eval/QUESTIONS.md` содержит три типичных вопроса владельца со страницами, на которые каждый ответ должен ссылаться. На них отвечают в чистой сессии до и после изменения инструкций — см. `kb-docs/17_REFACTOR.md`.

---

## Уровни confidence

| Уровень | Когда | Значение |
|---------|-------|----------|
| `high` | Ручная проверка, надёжный первичный источник | Факт |
| `medium` | AI-извлечение без ручной проверки | Использовать с оговорками |
| `low` | Предположение, косвенные данные, устаревший источник | Перепроверить |

**Убывание (правило для агента):** когда `last_verified` старше `lifecycle.confidence_decay_days` (по умолчанию 90), в ответах трактуйте `confidence: high` как `medium`; после повторной проверки обновляйте `last_verified` (и `confidence`, если он изменился). Скрипты не переписывают `confidence`.
**Исключение:** `lifecycle: permanent` — confidence **не** убывает со временем.

---

## Интеграция

- **03_PIPELINE:** метаданные ingest содержат `source_hash`, `valid_from`, значения `lifecycle` и `confidence` по умолчанию
- **04_REVIEW:** агент пишет страницу — цитирования, `importance`, решение о lifecycle
- **09_LINT:** `source-hash`, `citation`, `stale`, `expired-temporal`, `superseded`, `low-importance` — с учётом lifecycle
- **10_LOG:** операции происхождения (`review`, `query-writeback`, `archive`) записываются в журнал
