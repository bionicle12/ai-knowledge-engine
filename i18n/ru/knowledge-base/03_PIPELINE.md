---
translation_of: knowledge-base/03_PIPELINE.md
source_commit: ba0445d4e2f47c138df7354020807616d38a0739
source_version: 0.12.0
translated_at: 2026-08-13
translator: ai-assisted
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

Файлы, приложенные/загруженные в чате, не являются входом pipeline, пока пользователь не подтвердит добавление в основную базу знаний, а AI-агент не разместит их в подходящей папке `raw/<category>/unsorted/`.

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
| `.rtf` | `striprtf` | `processed/markdown/` |
| `.docx` | `python-docx` или `pandoc` | `processed/markdown/` |
| `.pdf` | `pypdf`, `pdftotext`, OCR fallback | `processed/markdown/` или `processed/ocr/` |
| `.pptx` | `python-pptx` | `processed/markdown/` |
| `.xlsx`, `.csv` | `pandas`, `openpyxl` | `processed/tables/` |
| audio: `.mp3` `.wav` `.m4a` `.flac` `.ogg` `.aac` `.opus` … | STT через `kb_stt.py` (faster-whisper, **без системного ffmpeg**) | `processed/transcripts/` |
| video: `.mp4` `.mov` `.webm` `.mkv` `.avi` `.m4v` … | STT через `kb_stt.py` (audio stream декодируется PyAV) | `processed/transcripts/` |
| изображения/сканы: `.png` `.jpg` `.webp` `.tiff` `.bmp` | OCR через `kb_ocr.py` (RapidOCR, без системных зависимостей) | `processed/ocr/` |
| экспорты чатов | custom parsers | `processed/markdown/` + возможно `review/needs-redaction/` |
| `.zip`, `.tar`, `.tar.gz` | распаковка в `raw/unsorted/` для повторного ingest | `processed/markdown/` (листинг) |

STT/OCR запускаются автоматически **после `pip install -r requirements-media.txt`**
(см. `01_PREREQUISITES.md` и `15_MEDIA_PROCESSING.md`). Если backend недоступен,
файл мягко уходит в `review/needs-ai-decision/`, а в review package встраивается
подсказка по установке под конкретную ОС — агент должен показать именно её, а не
вслепую советовать `ffmpeg`.

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

---

## Работа с длинными справочными материалами (книги, курсы, руководства)

Часть входных материалов — это **длинные справочные тексты**, а не сырые заметки: изданные книги о писательском мастерстве, учебники по программированию, книги о бизнес-стратегии, руководства по методологии исследований. Пайплайн способен извлечь их текст, но это несёт три риска:

1. **Стоимость токенов:** книга на 300 страниц ≈ 70-90K слов. Агент сожжёт ~50-100K токенов, пытаясь резюмировать её во время ревью.
2. **Серая зона копирайта:** полный текст защищённой авторским правом книги внутри `knowledge/` (а оттуда — в Repomix-индексе) — некомфортно даже для личного использования и опасно, если базой когда-нибудь поделятся.
3. **Загрязнение голоса/стиля:** особенно для ролей писателя или контент-мейкера — проза известного автора внутри `voice/` или `principles/` будет незаметно просачиваться в тон AI, вытесняя собственный голос пользователя.

### Рекомендуемый паттерн: PDF как справочник, заметки как знания

```
raw/documents/unsorted/Save-the-Cat.pdf
        ↓ pipeline
assets/documents/2026-05-16__save-the-cat.pdf   ← остаётся здесь, НЕ индексируется
assets-index/documents.md                        ← содержит однострочную запись, ИНДЕКСИРУЕТСЯ

raw/reference/unsorted/save-the-cat-my-takeaways.md
        ↓ pipeline → review (низкая complexity → авто-извлечение) → knowledge/
knowledge/principles/save-the-cat-beats.md       ← твоя интерпретация, ИНДЕКСИРУЕТСЯ
```

Пользователь (или агент во время ревью) пишет **сопутствующую заметку**, которая фиксирует *правила так, как их понимает пользователь*, его собственными словами. Именно эту заметку AI читает каждый день. Оригинал книги остаётся в `assets/` и открывается по запросу, когда пользователю нужна точная цитата или ссылка на страницу.

### Когда агент обрабатывает длинную справочную книгу в ревью

Если книга попала в `review/needs-ai-decision/`, агент должен:

1. **Сначала проверить копирайт/объём.** Если файл — полный текст защищённой авторским правом книги, НЕ извлекать её прозу в `knowledge/`. Вместо этого:
   - Убедиться, что оригинал лежит в `assets/`
   - Добавить однострочную запись в `assets-index/documents.md` (пайплайн уже сделал это)
   - Спросить пользователя: *«Хочешь, я подготовлю по этой книге заметку "выводы для тебя"? Я ограничусь твоими собственными формулировками и сошлюсь на источник.»*
2. **Если да — написать заметку с выводами.** 5-15 буллетов или коротких абзацев в `knowledge/principles/<book-slug>-takeaways.md`. Указать источник через frontmatter `source:` и span-цитаты (см. `11_PROVENANCE.md`).
3. **Вести индекс книжной полки.** Для ролей, где это происходит регулярно (писатель, исследователь, программист с учебниками, основатель с бизнес-книгами), поддерживать `knowledge/principles/<role>-bookshelf.md` — однострочный каталог всех справочных книг + ссылка на заметку с выводами + статус (`read` / `partially read` / `to read`).

### Когда извлечение УМЕСТНО

- **Книги в общественном достоянии** (срок авторских прав истёк)
- **Открытые лицензии** (CC-BY и т.п.) — оригинальный текст можно извлекать безопасно
- **Отрывки в рамках fair use** (абзац, а не глава) — уже покрыто паттерном артефакта `influences`
- **Собственные тексты пользователя** — черновики, рукописи, опубликованные работы, права на которые принадлежат ему

### Быстрое дерево решений

```
Файл в raw/documents/unsorted/ определён как длинный PDF/EPUB/DOCX
      ↓
Это защищённая копирайтом книга, которую пользователь не писал?
      ├─ Да  → ассет остаётся в assets/, агент предлагает написать заметку с выводами
      └─ Нет → стандартный пайплайн (извлечь → обработать → ревью, если сложно)
```
