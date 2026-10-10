# 12 — NLP preprocessing: NER and keyword extraction before LLM

> Before the agent analyses a material, ingest runs a cheap NLP pipeline. The agent receives pre-resolved entities linked to existing `knowledge/` pages.

---

## Why

- **Cheaper:** NER + keyword extraction run on CPU, no API calls
- **More accurate:** entity resolution collapses variants ("Docker Swarm" / "docker swarm") to one existing page
- **Faster:** the agent gets structured input instead of raw text
- **Linkage:** NLP discovers references to existing `knowledge/` pages

---

## Place in the pipeline

```text
raw/file → [convert to MD] → processed/ → [NLP enrichment] → processed/nlp-meta/ → [agent: !review]
```

The NLP step runs inside `kb_ingest.py`, **after** Markdown conversion and **before** routing (step 7 of `kb-docs/03_PIPELINE.md`). `kb_nlp_batch.py` re-runs it for files that are already in `processed/` and records the new `nlp_meta_path` in each file's metadata under the pipeline lock, so a `--mark-extracted` that runs meanwhile is kept.

It is skipped with `kb_ingest.py --no-nlp`, with `nlp.enabled: false`, for extensions listed in `nlp.skip_extensions` (the file itself is still ingested and converted), and for archives.

---

## Dependencies

- **spaCy** and **rake-nltk** come with `requirements.txt`.
- **KeyBERT** is optional: without it, keywords come from RAKE. It pulls in PyTorch (hundreds of MB); `01_PREREQUISITES.md` says which requirements file installs it.

Install a spaCy model:

```bash
# Russian
python3 -m spacy download ru_core_news_md

# English (if needed)
python3 -m spacy download en_core_web_md

# Multilingual (universal but less accurate)
python3 -m spacy download xx_ent_wiki_sm
```

RAKE needs NLTK data once:

```bash
python3 -m nltk.downloader stopwords punkt punkt_tab
```

Everything degrades instead of failing: without spaCy there are no entities, without KeyBERT and RAKE there are no keywords. A missing spaCy model or missing NLTK data prints one warning per run with the command that fixes it.

---

## NLP-step contract

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

There is no language detection: `language` is `language_policy.primary`, which also picks RAKE's stop-word list (`russian` for `ru`, else `english`).

### 1. NER (Named Entity Recognition)

spaCy runs on the first 1,000,000 characters. Each entity becomes:

```yaml
- text: "Docker Swarm"
  type: "PRODUCT"          # spaCy label: PER, ORG, LOC, DATE, PRODUCT, …
  canonical: "docker-swarm"
  existing_page: "knowledge/domain/docker-swarm.md"
```

`ner_engine` in the NLP metadata is `spacy` when NER ran, `null` when it did not (spaCy or its model missing). Without NER the complexity score cannot reach the review threshold (see 4).

### 2. Entity resolution (mode-aware)

#### `mode: default` — Python match (0 tokens)

For each entity:

1. Slugify its text; if a `knowledge/**/<slug>.md` exists, link it.
2. Otherwise take the closest file-name slug (`difflib.get_close_matches`, cutoff `nlp.fuzzy_match_threshold`, default 0.8).
3. A match sets `canonical` to the page slug and `existing_page` to its path; no match keeps the text as `canonical` and `existing_page: null` (a candidate for a new page).

Entities with the same `canonical` and `type` are merged.

> **Limits:** matches file names only — no alias dictionary, no synonyms (`Dragonfly` ↔ `DragonflyDB` ↔ `Redis-compatible cache`), no multilingual variants (`база данных` ↔ `database`).

#### `mode: super` — the agent adds semantic matching (~500-1K tokens)

Ingest always matches in Python. In super mode (`mode_profiles.super.entity_resolution.engine: "ai"`) the agent additionally, during review:

1. **Semantic match:** understands that `"cache layer"` = `"caching layer"` = `"DragonflyDB"` in this project's context
2. **Hierarchical linkage:** links an entity to several pages at different levels
3. **Cross-language resolution:** `"база данных"` ↔ `"database"` ↔ `"DB"` without dictionaries
4. **Context-aware:** `"Redis"` in a caching context → `[[caching]]`, in a pub/sub context → `[[messaging]]`

### 3. Keyword extraction

- **KeyBERT** (when installed): `keyphrase_ngram_range=(1, 3)`, `top_n = nlp.keyword_top_n` (default 20); `source: keybert`.
- **RAKE** otherwise: the `nlp.keyword_top_n` best-ranked phrases; `source: rake`.

Each keyword is `{phrase, weight, source}`.

### 4. Complexity estimation

`estimate_complexity(text, entity_count=…)` returns 0.0–1.0 as the sum of:

| Factor | Score |
|---|---|
| more than 2,000 words | +0.2 |
| more than 5,000 words | +0.1 more |
| more than 15 entities (after merging) | +0.2 |
| contrast markers: "however", "but", "однако", "впрочем" | +0.1 |
| a table (more than 10 `\|` characters) | +0.1 |
| any digit | +0.05 |

The maximum is 0.75; without NER entities it is 0.55. A file scoring at least `nlp.complexity_threshold` (default 0.7) gets a review package in `review/needs-ai-decision/` — so in practice only long, entity-rich texts with NER do. Below the threshold the file still waits for extraction (`kb-docs/03_PIPELINE.md` → Extraction registry), and ingest has other review triggers (decisions, transcripts, long chats, new versions). Without NER the metadata says so in `complexity_basis`.

---

## NLP metadata file

For each enriched file, `processed/nlp-meta/<name>.yml` is created (the metadata's `nlp_meta_path` points to it):

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

`suggested_targets` lists the pages that resolved entities link to, the most-linked first (at most 10). Pages suggested by keywords alone, and new-page ideas, are the agent's call.

---

## How the AI uses NLP metadata

During AI review (`kb-docs/04_REVIEW.md`) the agent reads the NLP metadata **before** the main text:

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

## Configuration in `kb.config.yml`

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

## Integration

- **03_PIPELINE:** NLP is step 7 of per-file processing, between conversion and routing
- **04_REVIEW:** the agent receives the NLP metadata as review context
- **10_LOG:** the `ingest` entry names the NLP metadata file (`NLP meta:`); `kb_nlp_batch.py` logs `nlp-batch`
- **13_AUTORUN:** the watcher runs ingest on new files, NLP included unless `autorun.auto_nlp: false`
