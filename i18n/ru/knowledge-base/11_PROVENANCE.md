---
translation_of: knowledge-base/11_PROVENANCE.md
source_commit: 6aa3cf8185ced124e010747a4238fd8f6097a76f
source_version: 0.7.0
translated_at: 2026-05-16
translator: human
---

# 11 — Source Provenance: отслеживание происхождения знаний

> Каждое знание в базе должно быть верифицируемым. Provenance — это цепочка от утверждения в `knowledge/` до конкретного места в оригинальном документе.

---

## Проблема

> *"An LLM Wiki is lossy compression. Summary errors become part of the knowledge base."*

Когда LLM извлекает знания, он может упростить нюансы, потерять оговорки, исказить формулировки. Без provenance нет возможности проверить откуда пришло утверждение.

---

## Расширенный frontmatter

```yaml
---
source: "assets/documents/2026-05-06__q2-strategy.pdf"
source_hash: "sha256:a1b2c3d4e5f6"       # SHA-256 оригинала (16 символов)
extracted_at: 2026-05-06
last_verified: 2026-05-06
confidence: high                           # high | medium | low
verification_method: "ai-review"           # manual-review | ai-review | auto-extract
extraction_model: "claude-opus-4"        # какая модель извлекала
lifecycle: "evolving"                      # permanent | evolving | temporal
importance: 8                              # 1-10, оценка ценности (см. ниже)
valid_from: 2026-05-06                     # когда факт стал верен
valid_until: null                          # null = актуален; дата = устарел с этого момента
last_accessed: 2026-05-06                  # обновляется при каждом чтении AI
access_count: 0                            # счётчик обращений
tags: [стратегия, рост]
supersedes: null
citations:                                 # span-level citations
  - claim: "Redis обрабатывает 100k ops/s на нашем профиле"
    source_span: "assets/documents/2026-05-06__bench.pdf#page=3&para=2"
    confidence: high
  - claim: "DragonflyDB в 25x быстрее Redis"
    source_span: "assets/documents/2026-05-06__dragonfly-bench.md#L15-L28"
    confidence: medium
    note: "Benchmark на синтетической нагрузке"
context_annotations: []                    # эволюция заметки при связи с новым знанием
---
```

---

## Importance scoring — оценка ценности знания

При записи в `knowledge/` каждый факт получает оценку importance (1-10).

### Шкала

| Балл | Значение | Примеры |
|------|----------|---------|
| 1-2 | Рутинная заметка | «Обновил зависимость», «настроил линтер» |
| 3-4 | Полезное знание | «Паттерн обработки ошибок», «конфигурация Nginx» |
| 5-6 | Значимое знание | «Архитектура кеш-слоя», «результаты A/B теста» |
| 7-8 | Ключевое знание | «Архитектурное решение с обоснованием», «стратегия роста» |
| 9-10 | Критически важное | «Фундаментальный принцип», «ключевой урок из провала» |

### Кто ставит

- **При auto-extract:** LLM оценивает при ingest: «Насколько это знание важно для долгосрочной работы? 1 = рутина, 10 = ключевой инсайт»
- **При manual-review:** Пользователь может переопределить
- **При query-writeback:** AI ставит на основе количества синтезированных источников

### Как используется

- **Routing:** AI при dynamic context loading предпочитает страницы с высоким importance
- **Reflection trigger:** когда `sum(importance)` последних N ingest > порога → автоматическая рефлексия (см. `07_INTERACTION_LOOP.md`)
- **Lint:** предлагает архивировать `importance < 3` + `lifecycle: temporal` + `last_accessed > 90 дней`
- **Context budget:** при нехватке контекста — low importance отбрасываются первыми

---

## Access tracking — свежесть обращения

### Recency decay

Каждое обращение AI к knowledge/ странице «освежает» её:

```yaml
last_accessed: 2026-05-06    # дата последнего чтения
access_count: 12             # сколько раз читали
```

### Обновление

- **AI-агент:** при чтении knowledge/ файла через dynamic context loading обновляет `last_accessed` и `access_count += 1`
- **Python-скрипт:** при reindex может вычислять `recency_score` для сортировки

### Recency score

```python
import math
from datetime import datetime

def recency_score(last_accessed: str, decay_factor: float = 0.995) -> float:
    """Экспоненциальный decay: 0.995^(часов с последнего обращения)."""
    last = datetime.fromisoformat(last_accessed)
    hours = (datetime.now() - last).total_seconds() / 3600
    return decay_factor ** hours
```

### Приоритет при routing

При прочих равных AI предпочитает страницы с **более высоким** `importance × recency_score`. Формула ранжирования (как в Generative Agents):

```
priority = importance/10 + recency_score + relevance_to_query
```

Все три компонента нормализованы от 0 до 1. AI не обязан вычислять формулу, но **принцип** такой: важное + свежее + релевантное → читаем первым.

---

## Bi-temporal validity — темпоральные факты

### Концепция (Zep/Graphiti)

Каждый факт хранит два момента:
- `valid_from` — когда факт **стал верен**
- `valid_until` — когда факт **перестал быть верен** (`null` = всё ещё актуален)

### Пример

```yaml
# knowledge/decisions/2026-01__redis-cache.md
valid_from: 2026-01-15
valid_until: 2026-03-20       # заменён на DragonflyDB
superseded_by: "knowledge/decisions/2026-03__dragonfly-migration.md"

# knowledge/decisions/2026-03__dragonfly-migration.md
valid_from: 2026-03-20
valid_until: null               # актуален
```

### Правила

- `valid_from` записывается при ingest (дата оригинала или extracted_at)
- `valid_until` заполняется, когда факт **обновляется или заменяется**
- AI при вопросе «что было в феврале?» фильтрует по `valid_from <= feb AND (valid_until IS NULL OR valid_until > feb)`
- Файлы с `valid_until != null` **не удаляются** — это история
- Lint считает файлы с `valid_until != null` **не stale** (они уже помечены как исторические)

---

## Lifecycle: жизненный цикл знаний

### Типы lifecycle

| Тип | Значение | Lint поведение | Примеры |
|-----|----------|---------------|---------|
| `permanent` | **Неизменяемое** — не устаревает, не деградирует | Lint **никогда** не предлагает обновить/удалить/архивировать | Тексты песен, стиль письма, личные принципы, творческие работы, профиль |
| `evolving` | **Развивающееся** — актуализируется при изменении реальности | Lint предупреждает о stale, предлагает обновить | Технологический стек, архитектурные решения, рыночные данные |
| `temporal` | **Временное** — привязано к конкретному периоду | Lint предлагает архивировать/обновить после истечения | Квартальные стратегии, актуальные метрики, текущие задачи |

**Дефолт:** если `lifecycle` не указан — считается `evolving`.

### Примеры по категориям

```yaml
# knowledge/voice/songwriting-style.md — стиль не «устаревает»
lifecycle: "permanent"

# knowledge/profile/expertise.md — экспертиза — фундамент
lifecycle: "permanent"

# knowledge/domain/tech-stack.md — стек может меняться
lifecycle: "evolving"

# knowledge/decisions/2026-q1__pricing.md — привязано к Q1
lifecycle: "temporal"
```

---

## Гарантии сохранности данных

### Что НИКОГДА не удаляется автоматически

1. **Любые файлы в `knowledge/`** — ни один модуль не удаляет файлы
2. **Файлы с `lifecycle: permanent`** — защищены от всех lint-предупреждений о staleness
3. **Оригиналы в `assets/`** — иммутабельные, не трогаются
4. **Файлы в `raw/`** — перемещаются в assets при ingest, но не удаляются до подтверждения

### Что делает lint для каждого lifecycle

| Действие lint | `permanent` | `evolving` | `temporal` |
|---------------|------------|-----------|-----------|
| Stale warning (last_verified > 30д) | ❌ Пропускает | ✅ Предупреждает | ✅ Предупреждает |
| Confidence degradation (>90д) | ❌ Не деградирует | ✅ high→medium | ✅ high→medium→low |
| Suggest archive | ❌ Никогда | 🟡 Только если superseded | ✅ Если expired |
| Suggest deletion | ❌ Никогда | ❌ Никогда | ❌ Никогда |
| Broken wikilink check | ✅ Проверяет | ✅ Проверяет | ✅ Проверяет |
| Source hash check | ❌ Пропускает | ✅ Проверяет | ✅ Проверяет |

### Правило: только архивирование, никогда удаление

Удаление файла из `knowledge/` — **ТОЛЬКО вручную** пользователем.

AI-агент **может предложить:**
- Архивировать (`knowledge/` → `knowledge/_archive/`) — для temporal/evolving
- Объединить (merge) — для evolving с дублями
- Обновить — для evolving с stale данными

AI-агент **НЕ может:**
- Удалить файл из `knowledge/`
- Изменить lifecycle без явного запроса пользователя
- Понизить lifecycle (`permanent` → `evolving`)
- Архивировать `permanent` файлы

---

## Форматы span-ссылок

| Формат | Когда |
|--------|-------|
| `file.pdf#page=3&para=2` | PDF-документы |
| `file.md#L15-L28` | Markdown/текст (строки) |
| `file.docx#section=3` | DOCX по секциям |
| `transcript.md#T00:15:30-T00:16:45` | Транскрипты по таймкодам |

---

## Source hash

```python
import hashlib

def compute_source_hash(filepath: str) -> str:
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()[:16]}"
```

**Hash mismatch** = оригинал обновлён, знания — нет → `⚠️ STALE SOURCE` в lint-report.
**Исключение:** `lifecycle: permanent` — hash mismatch пропускается.

---

## Regression tests: `knowledge/_tests/assertions.yml`

```yaml
assertions:
  - id: "tech-stack-db"
    claim: "Основная БД — PostgreSQL 16"
    expected_in: "knowledge/domain/database.md"
    pattern: "PostgreSQL 16"
    severity: error

  - id: "cache-layer"
    claim: "Кеш-слой — DragonflyDB"
    expected_in: "knowledge/domain/caching.md"
    pattern: "DragonflyDB"
    severity: error
```

Lint проверяет assertions на каждом прогоне. Если pattern не найден — regression.

---

## Уровни confidence

| Уровень | Когда | Значение |
|---------|-------|----------|
| `high` | Ручная проверка, надёжный первичный источник | Факт |
| `medium` | AI-извлечение без ручной проверки | С оговоркой |
| `low` | Предположение, косвенные данные, устаревший источник | Перепроверить |

**Деградация:** `last_verified` > 90 дней + `confidence: high` → lint понижает до `medium`.
**Исключение:** `lifecycle: permanent` — confidence **НЕ деградирует** со временем.

---

## Интеграция

- **03_PIPELINE:** ingest записывает source_hash, начальный confidence и lifecycle
- **04_REVIEW:** AI-ревью добавляет citations и определяет lifecycle при извлечении
- **09_LINT:** проверяет hash mismatch, citation validity, assertions — с учётом lifecycle
- **10_LOG:** provenance-операции записываются в лог
