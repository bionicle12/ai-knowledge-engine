# 12 — NLP preprocessing: NER and keyword extraction before LLM

> Before sending material to an LLM for analysis we run a cheap NLP pipeline. The LLM receives pre-resolved entities linked to existing `knowledge/` pages.

---

## Why

- **Cheaper:** NER + keyword extraction run on CPU, no API calls
- **More accurate:** entity resolution collapses variants ("Docker Swarm" / "docker swarm" / "Swarm") to a canonical name
- **Faster:** the LLM gets structured input instead of raw text
- **Linkage:** NLP automatically discovers references to existing `knowledge/` pages

---

## Place in the pipeline

```text
raw/file → [Convert to MD] → processed/ → [NLP enrichment] → nlp-meta/ → [AI review / auto-extract]
```

The NLP step sits **after** Markdown conversion and **before** AI review.

---

## Dependencies

Add to `requirements.txt`:

```txt
# NLP pre-processing
spacy>=3.7
rake-nltk>=1.0
keybert>=0.8
```

Install a spaCy model:

```bash
# Russian
python3 -m spacy download ru_core_news_md

# English (if needed)
python3 -m spacy download en_core_web_md

# Multilingual (universal but less accurate)
python3 -m spacy download xx_ent_wiki_sm
```

---

## NLP-step contract

```python
def nlp_enrich(text: str, knowledge_dir: str, lang: str = "auto") -> dict:
    """
    NLP enrichment of text before sending to an LLM.
    
    Stages:
    1. Language detection (if lang="auto")
    2. NER — Named Entity Recognition (spaCy)
    3. Keyword extraction — RAKE + KeyBERT
    4. Entity resolution — fuzzy match against existing knowledge/ pages
    5. Complexity estimation
    
    Returns:
        dict with entities, keywords, canonical_matches, complexity
    """
```

### 1. NER (Named Entity Recognition)

```python
import spacy

nlp = spacy.load("ru_core_news_md")  # or en_core_web_md
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

### 2. Keyword extraction

```python
from rake_nltk import Rake
from keybert import KeyBERT

# RAKE — fast, rule-based
rake = Rake(language="russian")
rake.extract_keywords_from_text(text)
rake_keywords = rake.get_ranked_phrases_with_scores()[:20]

# KeyBERT — embedding-based, more accurate
kw_model = KeyBERT()
keybert_keywords = kw_model.extract_keywords(
    text, keyphrase_ngram_range=(1, 3), top_n=20
)
```

### 3. Entity resolution (mode-aware)

#### `mode: default` — Python fuzzy match (0 tokens)

```python
from difflib import SequenceMatcher

def resolve_entities(entities: list, knowledge_dir: str) -> list:
    """
    For each entity — find a match against existing knowledge/ pages.
    
    Uses:
    - Exact match by slug
    - Fuzzy match (SequenceMatcher ratio > 0.8)
    - Alias dictionary (if any)
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
                entity["existing_page"] = None  # candidate for a new page
    
    return entities
```

> **Limits:** does not understand synonyms (`Dragonfly` ↔ `DragonflyDB` ↔ `Redis-compatible cache`), does not handle multilingual variants (`база данных` ↔ `database`).

#### `mode: super` — AI semantic (~500-1K tokens)

The AI agent additionally:
1. **Semantic match:** understands that `"cache layer"` = `"caching layer"` = `"DragonflyDB"` in this project's context
2. **Hierarchical linkage:** an entity can be linked to several pages at different levels
3. **Cross-language resolution:** `"база данных"` ↔ `"database"` ↔ `"DB"` without dictionaries
4. **Context-aware:** understands that `"Redis"` in caching context → `[[caching]]`, in pub/sub context → `[[messaging]]`

```yaml
# In kb.config.yml — driven via mode_profiles:
entity_resolution:
  # default: engine: "python"
  # super:   engine: "ai"     # AI primary + Python verification
```

### 4. Complexity estimation

```python
def estimate_complexity(text: str, entities: list, keywords: list) -> float:
    """
    Score the material's complexity (0.0 — 1.0).
    
    Factors:
    - Length (>2000 words → +0.2)
    - Unique entities (>15 → +0.2)
    - Unresolved entities (>5 → +0.2)
    - Numerical data / tables (→ +0.1)
    - Contradiction markers ("however", "but", "in contrast") (→ +0.1)
    """
    score = 0.0
    # ... computation ...
    return min(score, 1.0)
```

---

## NLP metadata file

For each processed file `processed/nlp-meta/<slug>.yml` is created:

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

## How the AI uses NLP metadata

During AI review (04_REVIEW.md) the agent reads the NLP metadata **before** the main text:

```markdown
## AI review with NLP context

You receive:
1. NLP meta: `processed/nlp-meta/<slug>.yml`
2. Text: `processed/markdown/<slug>.md`

The NLP meta already contains:
- Extracted entities linked to existing knowledge/ pages
- Key phrases with weights
- Suggestions for which knowledge/ pages to update
- The unresolved-entities list (candidates for new pages)

Use this to extract knowledge more precisely.
```

---

## Configuration in `kb.config.yml`

```yaml
nlp:
  enabled: true
  spacy_model: "ru_core_news_md"
  spacy_model_fallback: "xx_ent_wiki_sm"
  keyword_top_n: 20
  fuzzy_match_threshold: 0.8
  complexity_threshold: 0.7     # higher → review/needs-ai-decision/
  skip_extensions: [".csv", ".xlsx"]  # tables don't need NER
```

---

## Integration

- **03_PIPELINE:** NLP is step 4.5 between conversion and review
- **04_REVIEW:** the AI receives NLP meta as review context
- **09_LINT:** lint verifies that NLP meta exists for every processed file
- **10_LOG:** `nlp-enrich` is recorded in the log
- **13_AUTORUN:** watch mode runs NLP automatically
