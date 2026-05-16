---
translation_of: knowledge-base/03_PIPELINE.md
source_commit: 1237e839a201180ed4cfa249a370365be0f63c37
source_version: 0.8.1
translated_at: 2026-05-16
translator: human
---

# 03 — Контракт Python-пайплайна

> Спецификация `scripts/kb_ingest.py` — скрипта, который обрабатывает сырые материалы.
>
> **Reference implementation:** `knowledge-base/scripts/kb_ingest.py` (+ общие утилиты в `kb_common.py`).
> Агент при развёртывании **копирует эти файлы**, а не пишет с нуля.
> Контракт ниже описывает, что должен делать скрипт; реализация уже соответствует.

---

## Назначение

`kb_ingest.py` — не обязан быть умным. Его задача — **безопасная механика**: найти файлы, определить тип, конвертировать в текст, переместить оригиналы, и отправить сложное в ревью.

## Вход

Сканирует все директории `raw/**/unsorted/`.

## Обработка каждого файла

1. Определить тип файла (расширение + magic bytes)
2. Переименовать в стабильный формат: `YYYY-MM-DD__short-slug.ext`
   - Если дата неизвестна: `unknown-date__short-slug.ext`
3. Переместить оригинал в `assets/<тип>/`
4. Вычислить `source_hash` оригинала (SHA-256, см. `11_PROVENANCE.md`)
5. Конвертировать в текст/markdown, если возможно
6. **NLP enrichment** (см. `12_NLP_PREPROCESS.md`):
   - NER (spaCy) → entities
   - Keyword extraction (RAKE + KeyBERT) → keywords
   - Entity resolution → привязка к существующим knowledge/ страницам
   - Complexity estimation → score 0.0–1.0
   - Результат → `processed/nlp-meta/<slug>.yml`
7. **Surprise filter** (mode-aware, см. `07_INTERACTION_LOOP.md`):
   - `mode: default` → Python NLP entity overlap ≥80% → «не сюрприз» (0 токенов)
   - `mode: super` → AI семантический анализ **каждого** ingest (~2-5K токенов): «предсказуем ли этот факт из базы?» + обнаружение противоречий
8. **Importance scoring** (mode-aware):
   - `mode: default` → LLM оценивает ценность 1-10 (~500 токенов)
   - `mode: super` → LLM оценивает 1-10 **с развёрнутым обоснованием** + suggested routing (~1-2K токенов)
9. Создать metadata-файл (YAML) — включая source_hash, NLP-данные, importance, valid_from
10. **Routing по complexity:**
   - `complexity < threshold` → `processed/<формат>/` (авто-обработка)
   - `complexity >= threshold` → `review/needs-ai-decision/` (с review-пакетом + NLP-мета)
11. Чувствительные материалы → `review/needs-redaction/`
12. Обновить `assets-index/<тип>.md`
13. **Записать в `log.md`** (см. `10_LOG.md`) — включая importance для reflection-trigger

## Матрица конвертации

| Тип | Обработка | Выход |
|---|---|---|
| `.md`, `.txt` | чтение напрямую | `processed/markdown/` |
| `.docx` | `python-docx` или `pandoc` | `processed/markdown/` |
| `.pdf` | `pypdf`, `pdftotext`, OCR fallback | `processed/markdown/` или `processed/ocr/` |
| `.pptx` | `python-pptx` | `processed/markdown/` |
| `.xlsx`, `.csv` | `pandas`, `openpyxl` | `processed/tables/` |
| `.mp3`, `.wav`, `.mp4` | `ffmpeg` + STT (если есть) | `processed/transcripts/` |
| `.png`, `.jpg`, сканы | OCR (если `tesseract` доступен) | `processed/ocr/` |
| экспорты чатов | custom parsers | `processed/markdown/` + возможно `review/needs-redaction/` |
| `.zip`, `.tar.gz` | распаковка | `review/needs-classification/` |

Если STT или OCR недоступны — отправить в `review/needs-ai-decision/` с пометкой.

## Формат metadata

Для каждого обработанного файла создаётся `processed/extracted-metadata/YYYY-MM-DD__slug.yml`:

```yaml
original_filename: "Q2 Strategy Draft v3.docx"
stable_filename: "2026-05-06__q2-strategy-draft.docx"
asset_path: "assets/documents/2026-05-06__q2-strategy-draft.docx"
processed_path: "processed/markdown/2026-05-06__q2-strategy-draft.md"
source_hash: "sha256:a1b2c3d4e5f6"
file_type: "docx"
detected_content_type: "strategy"
processing_date: "2026-05-06T10:30:00"
confidence: "medium"
importance: 7                      # 1-10, LLM-assigned
valid_from: "2026-05-06"           # когда факт стал верен
lifecycle: "evolving"              # permanent | evolving | temporal
complexity: 0.72
is_surprise: true                  # false = предсказуем из базы, предложить context_annotations
surprise_engine: "python"          # python | ai (определяется mode в kb.config.yml)
importance_reasoning: null          # null в default, строка обоснования в super
nlp_meta_path: "processed/nlp-meta/2026-05-06__q2-strategy-draft.yml"
needs_ai_review: true
review_reason: "complexity >= threshold (0.72 >= 0.7)"
```

## Формат записи в assets-index

При обработке — обновить `assets-index/<тип>.md`:

```markdown
## 2026-05-06__q2-strategy-draft.docx

- Тип: document
- Оригинал: assets/documents/2026-05-06__q2-strategy-draft.docx
- Конвертация: processed/markdown/2026-05-06__q2-strategy-draft.md
- Краткое описание: Черновик стратегии роста Q2, каналы, гипотезы, бюджет
- Извлечённые знания:
  - knowledge/domain/growth-channels.md
  - knowledge/decisions/2026-05-06__q2-budget-shift.md
```

## Коды выхода

| Код | Значение |
|-----|----------|
| `0` | Все файлы обработаны |
| `1` | Часть файлов не обработана (список в stderr) |
| `2` | Ошибка окружения (нет зависимости) |

## Идемпотентность

Повторный запуск на уже обработанных файлах должен быть безопасным — пропускать или обновлять metadata, но не дублировать файлы в `assets/`.

## Триггеры AI-ревью

Файл отправляется в `review/needs-ai-decision/` если:

- Содержит стратегические решения или гипотезы
- Длинный экспорт чата (> 500 строк)
- Транскрипт встречи/созвона
- Презентация с высокой ценностью
- Конфликтующие утверждения
- Тип не определён с уверенностью
