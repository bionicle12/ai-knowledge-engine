---
translation_of: knowledge-base/12_NLP_PREPROCESS.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 12 — NLP-предобработка: NER и извлечение ключевых слов до LLM

> Прежде чем агент анализирует материал, приём запускает недорогой NLP-пайплайн. Агент получает уже сопоставленные сущности со ссылками на существующие страницы `knowledge/`.

---

## Зачем

- **Дешевле:** NER и извлечение ключевых слов работают на CPU без API-вызовов
- **Точнее:** разрешение сущностей сводит варианты ("Docker Swarm" / "docker swarm") к одной существующей странице
- **Быстрее:** агент получает структурированный ввод вместо сырого текста
- **Связи:** NLP обнаруживает упоминания существующих страниц `knowledge/`

---

## Место в пайплайне

```text
raw/file → [convert to MD] → processed/ → [NLP enrichment] → processed/nlp-meta/ → [agent: !review]
```

NLP-шаг выполняется внутри `kb_ingest.py` **после** преобразования в Markdown и **до** маршрутизации (шаг 7 в `kb-docs/03_PIPELINE.md`). `kb_nlp_batch.py` повторяет его для файлов, уже находящихся в `processed/`, и записывает новый `nlp_meta_path` в метаданные каждого файла под блокировкой пайплайна, сохраняя результат параллельного `--mark-extracted`.

Шаг пропускается при `kb_ingest.py --no-nlp`, `nlp.enabled: false`, для расширений из `nlp.skip_extensions` (сам файл всё равно принимается и преобразуется) и для архивов.

---

## Зависимости

- **spaCy** и **rake-nltk** входят в `requirements.txt`.
- **KeyBERT** необязателен: без него ключевые слова извлекает RAKE. Он подтягивает PyTorch (сотни MB); файл зависимостей для его установки указан в `01_PREREQUISITES.md`.

Установка модели spaCy:

```bash
# Russian
python3 -m spacy download ru_core_news_md

# English (if needed)
python3 -m spacy download en_core_web_md

# Multilingual (universal but less accurate)
python3 -m spacy download xx_ent_wiki_sm
```

RAKE один раз требует данные NLTK:

```bash
python3 -m nltk.downloader stopwords punkt punkt_tab
```

Всё работает с ограничениями вместо аварийного завершения: без spaCy нет сущностей, без KeyBERT и RAKE — ключевых слов. Отсутствие модели spaCy или данных NLTK вызывает одно предупреждение за запуск с командой для исправления.

---

## Контракт NLP-шага

```python
def nlp_enrich(text: str, cfg: kbc.KbConfig, knowledge_dir: Path) -> dict:
    """Best-effort NLP enrichment of converted text (kb_ingest.py).

    Stages:
    1. NER — spaCy (nlp.spacy_model, else nlp.spacy_model_fallback)
    2. Entity resolution — slug / fuzzy match against knowledge/ file names
    3. Keywords — KeyBERT when installed, else RAKE
    4. Complexity estimation

    Models load once per process. Returns the dict written to
    processed/nlp-meta/<name>.yml (see below).
    """
```

Определения языка нет: `language` равно `language_policy.primary`, которое также выбирает список стоп-слов RAKE (`russian` для `ru`, иначе `english`).

### 1. NER (распознавание именованных сущностей)

spaCy обрабатывает первый 1 000 000 символов. Каждая сущность получает вид:

```yaml
- text: "Docker Swarm"
  type: "PRODUCT"          # spaCy label: PER, ORG, LOC, DATE, PRODUCT, …
  canonical: "docker-swarm"
  existing_page: "knowledge/domain/docker-swarm.md"
```

`ner_engine` в NLP-метаданных равен `spacy`, если NER выполнен, и `null`, если нет (отсутствует spaCy или модель). Без NER оценка сложности не достигает порога разбора (см. 4).

### 2. Разрешение сущностей с учётом режима

#### `mode: default` — сопоставление Python (0 токенов)

Для каждой сущности:

1. Преобразовать текст в slug; если существует `knowledge/**/<slug>.md`, связать с ним.
2. Иначе выбрать ближайший slug имени файла (`difflib.get_close_matches`, порог `nlp.fuzzy_match_threshold`, по умолчанию 0.8).
3. При совпадении записать slug страницы в `canonical`, путь в `existing_page`; без совпадения оставить текст в `canonical` и `existing_page: null` (кандидат на новую страницу).

Сущности с одинаковыми `canonical` и `type` объединяются.

> **Ограничения:** сопоставляются только имена файлов — без словаря псевдонимов, синонимов (`Dragonfly` ↔ `DragonflyDB` ↔ `Redis-compatible cache`) и разноязычных вариантов (`база данных` ↔ `database`).

#### `mode: super` — агент добавляет смысловое сопоставление (~500–1K токенов)

Приём всегда сопоставляет через Python. В режиме super (`mode_profiles.super.entity_resolution.engine: "ai"`) агент дополнительно при разборе выполняет:

1. **Смысловое сопоставление:** понимает, что `"cache layer"` = `"caching layer"` = `"DragonflyDB"` в контексте проекта
2. **Иерархические связи:** связывает сущность с несколькими страницами разных уровней
3. **Межъязыковое разрешение:** `"база данных"` ↔ `"database"` ↔ `"DB"` без словарей
4. **Учёт контекста:** `"Redis"` в контексте кеширования → `[[caching]]`, в контексте pub/sub → `[[messaging]]`

### 3. Извлечение ключевых слов

- **KeyBERT**, если установлен: `keyphrase_ngram_range=(1, 3)`, `top_n = nlp.keyword_top_n` (по умолчанию 20); `source: keybert`.
- **RAKE** в остальных случаях: лучшие `nlp.keyword_top_n` фраз по рангу; `source: rake`.

Каждое ключевое слово — `{phrase, weight, source}`.

### 4. Оценка сложности

`estimate_complexity(text, entity_count=…)` возвращает 0.0–1.0 как сумму:

| Фактор | Баллы |
|---|---|
| больше 2 000 слов | +0.2 |
| больше 5 000 слов | ещё +0.1 |
| больше 15 сущностей после объединения | +0.2 |
| маркеры противопоставления: "however", "but", "однако", "впрочем" | +0.1 |
| таблица (больше 10 символов `\|`) | +0.1 |
| любая цифра | +0.05 |

Максимум — 0.75; без сущностей NER — 0.55. Файл с оценкой не ниже `nlp.complexity_threshold` (по умолчанию 0.7) получает пакет разбора в `review/needs-ai-decision/`: практически это длинные тексты со множеством сущностей и работающим NER. Ниже порога файл всё равно ждёт извлечения (`kb-docs/03_PIPELINE.md` → реестр извлечения), а приём имеет другие триггеры разбора (решения, расшифровки, длинные чаты, новые версии). Отсутствие NER фиксируется в `complexity_basis`.

---

## Файл NLP-метаданных

Для каждого обогащённого файла создаётся `processed/nlp-meta/<name>.yml` (на него указывает `nlp_meta_path` в метаданных):

```yaml
# processed/nlp-meta/2026-05-06__karpathy-llm-wiki.yml
source: "processed/markdown/2026-05-06__karpathy-llm-wiki.md"
processed_at: "2026-05-06T20:30:00+03:00"
language: "en"
ner_engine: "spacy"
entities:
  - text: "Andrej Karpathy"
    type: "PERSON"
    canonical: "Andrej Karpathy"
    existing_page: null
  - text: "RAG"
    type: "ORG"
    canonical: "rag"
    existing_page: "knowledge/domain/rag.md"
keywords:
  - phrase: "persistent wiki"
    weight: 0.92
    source: "keybert"
  - phrase: "knowledge compilation"
    weight: 0.87
    source: "keybert"
unresolved_entities:
  - "Andrej Karpathy"
suggested_targets:
  - path: "knowledge/domain/rag.md"
    reason: "linked entities: RAG"
complexity: 0.65
```

`suggested_targets` перечисляет страницы, с которыми сопоставлены сущности, начиная с наиболее часто упомянутых (не больше 10). Страницы по одним ключевым словам и идеи новых страниц определяет агент.

---

## Как ИИ использует NLP-метаданные

При ИИ-разборе (`kb-docs/04_REVIEW.md`) агент читает NLP-метаданные **до** основного текста:

```markdown
## AI review with NLP context

You receive:
1. NLP meta: `processed/nlp-meta/<name>.yml`
2. Text: `processed/markdown/<name>.md` (or tables/, transcripts/, ocr/)

The NLP meta already contains:
- Extracted entities linked to existing knowledge/ pages
- Key phrases with weights
- The pages those entities point to (suggested_targets)
- The unresolved-entities list (candidates for new pages)

Use this to extract knowledge more precisely.
```

---

## Настройки в `kb.config.yml`

```yaml
nlp:
  enabled: true
  spacy_model: "ru_core_news_md"
  spacy_model_fallback: "xx_ent_wiki_sm"
  keyword_top_n: 20
  fuzzy_match_threshold: 0.8
  complexity_threshold: 0.7     # >= → review package in review/needs-ai-decision/
  skip_extensions: [".csv", ".xlsx"]  # skip NLP enrichment only — files are still ingested
```

---

## Интеграция

- **03_PIPELINE:** NLP — шаг 7 обработки файла между преобразованием и маршрутизацией
- **04_REVIEW:** агент получает NLP-метаданные как контекст разбора
- **10_LOG:** запись `ingest` указывает файл NLP-метаданных (`NLP meta:`); `kb_nlp_batch.py` записывает `nlp-batch`
- **13_AUTORUN:** наблюдатель принимает новые файлы вместе с NLP, кроме `autorun.auto_nlp: false`
