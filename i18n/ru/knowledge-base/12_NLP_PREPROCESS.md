---
translation_of: knowledge-base/12_NLP_PREPROCESS.md
source_commit: 63ec5652913793e80cf7a899c691d34d88285f8a
source_version: 0.9.3
translated_at: 2026-05-17
translator: human
---

# 12 — NLP-предобработка: NER и keyword extraction перед LLM

> Перед отправкой материала в LLM для анализа — прогоняем дешёвый NLP-пайплайн. LLM получает pre-resolved entities, связанные с существующими knowledge/ страницами.

---

## Зачем

- **Дешевле:** NER + keyword extraction на CPU, без API-вызовов
- **Точнее:** Entity resolution сводит вариации («Docker Swarm» / «docker swarm» / «Swarm») к каноническому имени
- **Быстрее:** LLM получает структурированный input вместо raw text
- **Связность:** NLP автоматически находит ссылки на существующие knowledge/ страницы

---

## Место в pipeline

```text
raw/file → [Конвертация в MD] → processed/ → [NLP enrichment] → nlp-meta/ → [AI review / auto-extract]
```

NLP-шаг добавляется **после** конвертации в markdown и **до** AI-ревью.

---

## Зависимости

Добавить в `requirements.txt`:

```txt
# NLP pre-processing
spacy>=3.7
rake-nltk>=1.0
keybert>=0.8
```

Установка модели spaCy:

```bash
# Русский
python3 -m spacy download ru_core_news_md

# Английский (если нужен)
python3 -m spacy download en_core_web_md

# Мультиязычный (универсальный, но менее точный)
python3 -m spacy download xx_ent_wiki_sm
```

---

## Контракт NLP-этапа

```python
def nlp_enrich(text: str, knowledge_dir: str, lang: str = "auto") -> dict:
    """
    NLP-обогащение текста перед отправкой в LLM.
    
    Этапы:
    1. Language detection (если lang="auto")
    2. NER — Named Entity Recognition (spaCy)
    3. Keyword extraction — RAKE + KeyBERT
    4. Entity resolution — fuzzy match с существующими knowledge/ pages
    5. Complexity estimation
    
    Returns:
        dict с entities, keywords, canonical_matches, complexity
    """
```

### 1. NER (Named Entity Recognition)

```python
import spacy

nlp = spacy.load("ru_core_news_md")  # или en_core_web_md
doc = nlp(text)

entities = []
for ent in doc.ents:
    entities.append({
        "text": ent.text,
        "type": ent.label_,   # PER, ORG, LOC, DATE, PRODUCT, etc.
        "start": ent.start_char,
        "end": ent.end_char,
    })
```

### 2. Keyword Extraction

```python
from rake_nltk import Rake
from keybert import KeyBERT

# RAKE — быстрый, rule-based
rake = Rake(language="russian")
rake.extract_keywords_from_text(text)
rake_keywords = rake.get_ranked_phrases_with_scores()[:20]

# KeyBERT — embedding-based, точнее
kw_model = KeyBERT()
keybert_keywords = kw_model.extract_keywords(
    text, keyphrase_ngram_range=(1, 3), top_n=20
)
```

### 3. Entity Resolution (mode-aware)

#### `mode: default` — Python fuzzy match (0 токенов)

```python
from difflib import SequenceMatcher

def resolve_entities(entities: list, knowledge_dir: str) -> list:
    """
    Для каждой найденной entity — ищем совпадение
    с существующими knowledge/ страницами.
    
    Используем:
    - Exact match по slug
    - Fuzzy match (SequenceMatcher ratio > 0.8)
    - Словарь алиасов (если есть)
    """
    knowledge_slugs = scan_knowledge_slugs(knowledge_dir)
    
    for entity in entities:
        slug = slugify(entity["text"])
        # Exact match
        if slug in knowledge_slugs:
            entity["canonical"] = slug
            entity["existing_page"] = knowledge_slugs[slug]
        # Fuzzy match
        else:
            best_match = find_best_fuzzy_match(slug, knowledge_slugs)
            if best_match and best_match[1] > 0.8:
                entity["canonical"] = best_match[0]
                entity["existing_page"] = knowledge_slugs[best_match[0]]
            else:
                entity["canonical"] = entity["text"]
                entity["existing_page"] = None  # кандидат на новую страницу
    
    return entities
```

> **Ограничения:** не понимает синонимы (`Dragonfly` ↔ `DragonflyDB` ↔ `Redis-совместимый кеш`), не обрабатывает мультиязычные варианты (`база данных` ↔ `database`).

#### `mode: super` — AI семантический (~500-1K токенов)

AI-агент дополнительно:
1. **Семантическое совпадение:** понимает, что `«кеш-слой»` = `«caching layer»` = `«DragonflyDB»` в контексте проекта
2. **Иерархическая привязка:** entity может быть привязана к нескольким страницам на разных уровнях
3. **Cross-language resolution:** `«база данных»` ↔ `«database»` ↔ `«БД»` без словарей
4. **Context-aware:** понимает, что `«Redis»` в контексте кеширования → `[[caching]]`, а в контексте pub/sub → `[[messaging]]`

```yaml
# В kb.config.yml — управляется через mode_profiles:
entity_resolution:
  # default: engine: "python"
  # super:   engine: "ai"     # AI primary + Python verification
```

### 4. Complexity Estimation

```python
def estimate_complexity(text: str, entities: list, keywords: list) -> float:
    """
    Оценка сложности материала (0.0 — 1.0).
    
    Факторы:
    - Длина текста (>2000 слов → +0.2)
    - Количество unique entities (>15 → +0.2)
    - Количество unresolved entities (>5 → +0.2)
    - Наличие числовых данных / таблиц (→ +0.1)
    - Наличие противоречивых маркеров ("однако", "но", "в отличие") (→ +0.1)
    """
    score = 0.0
    # ... computation ...
    return min(score, 1.0)
```

---

## Файл NLP-метаданных

Для каждого обработанного файла создаётся `processed/nlp-meta/<slug>.yml`:

```yaml
# processed/nlp-meta/2026-05-06__karpathy-llm-wiki.yml
source: "processed/markdown/2026-05-06__karpathy-llm-wiki.md"
processed_at: "2026-05-06T20:30:00+03:00"
language: "en"
complexity: 0.65

entities:
  - text: "Andrej Karpathy"
    type: "PER"
    canonical: "Andrej Karpathy"
    existing_page: null
  - text: "Obsidian"
    type: "PRODUCT"
    canonical: "Obsidian"
    existing_page: null
  - text: "RAG"
    type: "TECHNOLOGY"
    canonical: "RAG"
    existing_page: "knowledge/domain/retrieval-patterns.md"

keywords:
  - phrase: "persistent wiki"
    weight: 0.92
    source: "keybert"
  - phrase: "knowledge compilation"
    weight: 0.87
    source: "rake"
  - phrase: "cross-references"
    weight: 0.81
    source: "keybert"

suggested_targets:
  - path: "knowledge/domain/knowledge-management.md"
    reason: "3 keyword matches + entity 'RAG' linked"
  - path: "knowledge/principles/knowledge-compilation.md"
    reason: "New concept, high keyword weight"

unresolved_entities:
  - "Andrej Karpathy"
  - "Obsidian"
  - "Marp"
```

---

## Как AI использует NLP-метаданные

При AI-ревью (04_REVIEW.md) агент читает NLP-метаданные **перед** основным текстом:

```markdown
## AI Review с NLP-контекстом

Ты получаешь:
1. NLP-мету: `processed/nlp-meta/<slug>.yml`
2. Текст: `processed/markdown/<slug>.md`

NLP-мета уже содержит:
- Извлечённые entities с привязкой к существующим knowledge/ страницам
- Ключевые фразы с весами
- Рекомендации, какие knowledge/ страницы обновить
- Список неразрешённых entities (кандидаты на новые страницы)

Используй эту информацию для более точного извлечения знаний.
```

---

## Конфигурация в `kb.config.yml`

```yaml
nlp:
  enabled: true
  spacy_model: "ru_core_news_md"
  spacy_model_fallback: "xx_ent_wiki_sm"
  keyword_top_n: 20
  fuzzy_match_threshold: 0.8
  complexity_threshold: 0.7     # выше → review/needs-ai-decision/
  skip_extensions: [".csv", ".xlsx"]  # таблицы не нуждаются в NER
```

---

## Интеграция

- **03_PIPELINE:** NLP — шаг 4.5 между конвертацией и review
- **04_REVIEW:** AI получает NLP-мету как контекст для ревью
- **09_LINT:** lint проверяет, что NLP-мета существует для каждого processed файла
- **10_LOG:** `nlp-enrich` записывается в лог
- **13_AUTORUN:** watch mode автоматически запускает NLP
