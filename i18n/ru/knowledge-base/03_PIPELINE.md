---
translation_of: knowledge-base/03_PIPELINE.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 03 — Контракт Python-пайплайна

> Спецификация `scripts/kb_ingest.py` — скрипта обработки сырых материалов.
>
> **Эталонная реализация:** `knowledge-base/scripts/kb_ingest.py` (+ общие утилиты в `kb_common.py`).
> При развёртывании агент **копирует эти файлы**, а не пишет их с нуля.
> Контракт ниже описывает работу скрипта; реализация ему соответствует.

---

## Назначение

`kb_ingest.py` не обязан быть умным. Его задача — **безопасная механика**: находить файлы, определять тип, преобразовывать в текст, перемещать оригиналы и ставить каждый файл в очередь на извлечение знаний агентом. Скрипт не вызывает LLM и не принимает смысловых решений: что станет знанием, решает агент в `!review` (см. `kb-docs/04_REVIEW.md`).

## Входные данные

Сканируются все папки `unsorted/` внутри `raw/` — `raw/<category>/unsorted/` и общая `raw/unsorted/` — **включая подпапки** (`raw/work/unsorted/Project X/notes.md`). Работает и `raw/` или `raw/<category>/`, являющаяся символической ссылкой на синхронизируемую папку (Dropbox, iCloud).

Файлы остаются на месте без изменений, если они:

- соответствуют `ingest.ignore_globs` (по умолчанию: `.DS_Store`, `Thumbs.db`, `desktop.ini`, `~$*`, `._*`, `*.part`, `*.crdownload`, `*.tmp`, `*.swp` — мусор ОС, файлы блокировки Office, незавершённые загрузки);
- пусты (0 байт);
- превышают `ingest.max_file_mb` (по умолчанию 200; `0` и меньше — без ограничения).

`--status` перечисляет пустые и слишком большие файлы, чтобы владелец мог удалить, исправить или разделить их.

Вложения и загрузки в чате не становятся входом пайплайна, пока пользователь не подтвердит добавление в основную базу знаний, а ИИ-агент не поместит их в наиболее подходящую папку `raw/<category>/unsorted/`.

## Команды

```bash
python3 scripts/kb_ingest.py                    # process everything waiting in raw/**/unsorted/
python3 scripts/kb_ingest.py <file>             # one file under raw/**/unsorted/
python3 scripts/kb_ingest.py assets/<type>/<f>  # re-process an existing asset
python3 scripts/kb_ingest.py --dry-run          # list what would be picked up and where, change nothing
python3 scripts/kb_ingest.py --no-nlp           # skip NLP enrichment
python3 scripts/kb_ingest.py --json             # machine-readable result
python3 scripts/kb_ingest.py --status [--json]  # what waits where (changes nothing)
python3 scripts/kb_ingest.py --mark-extracted <path> --to knowledge/<category>/<slug>.md [--to …]
python3 scripts/kb_ingest.py --mark-skipped <path> --reason "<why>"
python3 scripts/kb_ingest.py --set-category <category> assets/<type>/<f>  # re-process as coming from raw/<category>/
python3 scripts/kb_ingest.py --init-dirs        # create the folder layout and exit
```

`--dry-run` выводит каждый файл с будущим путём `assets/…` и отмечает дубликаты уже принятых файлов или других файлов пакета. Преобразование не выполняется, поэтому маршрутизация на разбор и содержимое архивов видны только при настоящем запуске.

Приём, повторная обработка и `--mark-*` захватывают блокировку пайплайна (`.kb-state/locks/pipeline.lock`, общую с переиндексацией и наблюдателем). Если её удерживает другой запуск, приём ждёт до 10 минут, затем завершается с кодом 2 без изменений. `--dry-run`, `--status` и `--init-dirs` блокировку не захватывают.

## Обработка каждого файла

1. **Хеширование** оригинала: `source_hash` = `sha256:<first 16 hex>` (см. `11_PROVENANCE.md`).
2. **Точный дубликат** уже принятого файла (тот же `source_hash`) → перемещение в `ingest.duplicates_dir` (по умолчанию `raw/_duplicates/<category>/…`) и запись `ingest-duplicate` в журнал. Больше ничего не происходит. В одной папке оригиналом становится файл с более коротким именем (`report.md` предпочтительнее `report (1).md`).
3. **Определение типа** по расширению (`.tar.gz` считается одним расширением). Файл без расширения или с неизвестным расширением распознаётся по сигнатуре: PDF, PNG, JPEG, GIF, RTF, DOCX/XLSX/PPTX, ZIP, TAR, TAR.GZ. Таким способом архивом может стать только файл без расширения или с одним `.gz` в конце (старые версии называли ресурсы `.tar.gz` как `…-tar.gz`); форматы на основе ZIP, например `.jar` и `.pages`, никогда не распаковываются.
4. **Стабильное имя** `YYYY-MM-DD__slug.ext`. Берётся дата из имени файла (`2026-09-15`, `2026_09_15`, `20260915`), а при её отсутствии — дата изменения файла. Если имя занято другим содержимым или ресурсом, чьи производные файлы получили бы то же имя (`plan.md` и `plan.txt` за один день), новый ресурс получает суффикс `__<hash8>`.
5. **Копирование** оригинала в `assets/<type>/`.
6. **Преобразование** в Markdown (матрица ниже). Текст декодируется независимо от кодировки (UTF-8, UTF-16, cp1251, …) и всегда сохраняется в UTF-8; исходная кодировка, отличная от UTF-8, записывается в `source_encoding`.
7. **NLP-обогащение** (см. `kb-docs/12_NLP_PREPROCESS.md`) → `processed/nlp-meta/<name>.yml`. Пропускается при `--no-nlp`, `nlp.enabled: false`, для расширений из `nlp.skip_extensions` (сам файл всё равно принимается) и для архивов.
8. **Оценка сложности** от 0.0 до 1.0 (см. `12`).
9. **Маршрутизация** (следующий раздел) и создание пакета разбора при необходимости.
10. **Обновление `assets-index/<type>.md`**.
11. **Запись метаданных** `processed/extracted-metadata/<name>.yml` — последней: файл без метаданных ещё не принят.
12. **Добавление в `log.md`** (операция `ingest`, а для ресурса — `reprocess`; см. `kb-docs/10_LOG.md`).
13. **Удаление оригинала** из `unsorted/` и опустевших подпапок.

Все записи для одного файла атомарны: если любой шаг завершается с ошибкой, включая Ctrl+C, всё записанное для этого файла откатывается, а оригинал остаётся в `unsorted/`. Следующий запуск повторяет попытку; до этого `--status` показывает `error`.

`<name>` — стабильное имя ресурса без расширения; обработанная копия, метаданные, NLP-метаданные, пакет разбора и блок assets-index одного ресурса используют это имя.

### Чего скрипт не делает

- **Важность.** Скрипт не оценивает важность. Агент назначает `importance` (1–10) во frontmatter страницы `knowledge/`, которую создаёт при извлечении; рефлексия взвешивает изменения страниц по этому значению (см. `kb-docs/13_AUTORUN.md`).
- **Фильтр неожиданности.** Пока не реализован (см. `docs/ROADMAP.md` в репозитории движка); приём не записывает `is_surprise`.
- **Определение языка.** `language` в NLP-метаданных равно `language_policy.primary`.

## Маршрутизация

Проверки выполняются по порядку; используется первое совпадение.

| Условие | Назначение |
|---|---|
| Архив (`.zip`, `.tar`, `.tar.gz`, `.tgz`, `.rar`) | `processed/` (список содержимого, в котором отмечены повреждённые элементы). Содержимое распаковывается в собственную папку архива `raw/<category>/unsorted/`, и каждый элемент проходит эту таблицу, включая проверки приватности, в том же запуске. Архив внутри архива не распаковывается → `review/needs-ai-decision/` (причина `N nested archive(s) not unpacked — unpack manually`). Если распаковка выключена (`media.archives.enabled: false`) или формат не поддерживается (`.rar`) → `review/needs-ai-decision/` с указанием причины |
| Файл поступил из `raw/<category>/`, где `<category>` входит в `privacy.redact_categories` (по умолчанию `chats`, `personal-context`), и `privacy.require_redaction_for_chats` равно true | `review/needs-redaction/` |
| `privacy.secret_scan` (по умолчанию true) находит строки, похожие на учётные данные: токены GitHub, AWS, Slack, Stripe и OpenAI, присваивания `password=` / `secret:` (включая ключи JSON/YAML; исключаются значения `true`/`null`, `$VAR` и `{{ template }}`), закрытые ключи PEM/OpenSSH/PGP — в преобразованном тексте или, для файла неизвестного типа до 8 MB (`id_rsa`, `*.pem`, `.env`, `*.json`, …), при чтении самого файла как текста; либо имя файла соответствует хранилищу учётных данных: `.env`, `*.env`, `.env.*` (кроме `*.example`, `*.sample`, `*.template`, `*.dist`), `*.p12`, `*.pfx`, `*.jks`, `*.keystore`, `*.kdbx` | `review/needs-redaction/` |
| Неизвестный тип, ничего не преобразовано | `review/needs-classification/` |
| Известный тип, но текста нет (нет конвертера для формата, отсутствует библиотека, преобразование не удалось, STT/OCR недоступны) | `review/needs-ai-decision/` с причиной и подсказкой по установке |
| Сработал триггер ИИ-разбора (ниже) | `review/needs-ai-decision/` |
| Всё остальное | Только `processed/` |

Маршрутизация определяет лишь необходимость пакета разбора и его очередь. Преобразованный текст всегда попадает в `processed/`, а каждый файл, кроме архивов, ждёт с `extraction: pending` в метаданных, пока агент не зафиксирует результат; см. [Реестр извлечения](#extraction-registry).

### Триггеры ИИ-разбора

Файл получает пакет в `review/needs-ai-decision/`, если:

- оценка `complexity >= nlp.complexity_threshold` (по умолчанию 0.7);
- это расшифровка встречи или звонка (результат STT);
- это экспорт чата из `raw/chats/` длиннее 500 строк;
- упоминаются решения или гипотезы ("we decided", "decided to", "decision:", "hypothesis", "мы решили", "решение:", "гипотез…");
- это новая версия принятого файла (то же исходное имя и тот же `raw_path` — категория и подпапка — при другом содержимом; метаданные до 0.16 не имеют `raw_path`, поэтому сопоставляются только по имени и категории): в метаданные записывается `previous_version` (последняя версия, даже если с тех пор повторно обработана более старая), а пакет перечисляет страницы `knowledge/`, ссылающиеся на старую версию. `Project X/README.md` и `Project Y/README.md` — разные файлы, а не версии;
- файл похож на объёмную справочную книгу (см. последний раздел).

Без spaCy NER оценка сложности не превышает 0.55, поэтому порог достижим только с NER. Такие метаданные содержат `complexity_basis`, а строка журнала — `(no NER)`. В любом случае ничего не теряется: файлы ниже порога тоже ждут в реестре извлечения.

## Матрица преобразования

| Тип | Обработка | Результат |
|------|----------|--------|
| `.md`, `.txt` | чтение текста с определением кодировки | `processed/markdown/` |
| `.rtf` | `striprtf` | `processed/markdown/` |
| `.docx` | `python-docx` (таблицы → таблицы Markdown) | `processed/markdown/` |
| `.pdf` | `pypdf`, раздел `## Page N` на каждую страницу (без резервного OCR) | `processed/markdown/` |
| `.pptx` | `python-pptx`, раздел `## Slide N` на каждый слайд | `processed/markdown/` |
| `.xlsx` | `openpyxl`, таблица на каждый лист | `processed/tables/` |
| `.csv` | стандартный модуль `csv`; определяются разделитель (`,` `;` табуляция `|`) и кодировка | `processed/tables/` |
| аудио: `.mp3` `.wav` `.m4a` `.flac` `.ogg` `.aac` `.opus` … | STT через `kb_stt.py` (faster-whisper, **без системного ffmpeg**) | `processed/transcripts/` |
| видео: `.mp4` `.mov` `.webm` `.mkv` `.avi` `.m4v` … | STT через `kb_stt.py` (аудиопоток декодируется PyAV) | `processed/transcripts/` |
| изображения/сканы: `.png` `.jpg` `.webp` `.tiff` `.bmp` | OCR через `kb_ocr.py` (RapidOCR, без системных зависимостей) | `processed/ocr/` |
| `.zip`, `.tar`, `.tar.gz`, `.tgz` | распаковка в собственную папку архива `raw/<category>/unsorted/` (один уровень: вложенные архивы не распаковываются); содержимое принимается в том же запуске | `processed/markdown/` (список) |
| `.rar` | не распаковывается (нужен внешний инструмент, например `unar`) | пакет разбора с подсказкой |
| `.doc`, `.odt`, `.epub`, `.xls`, `.ods`, `.ppt`, `.odp`, `.gif`, `.svg` | нет конвертера | только пакет разбора |

Для экспортов чатов нет специального парсера: экспорт `.txt`/`.md` читается как текст; помещённый в `raw/chats/` попадает в `review/needs-redaction/` (см. «Маршрутизация»).

Для каждого архива действуют ограничения `media.archives`: `max_files` (200), `max_total_mb` (500, общий размер после распаковки), `max_member_mb` (200). Распаковывается один уровень: архив внутри архива (по расширению, а для элемента без расширения — по содержимому) не распаковывается, поэтому вложенность не умножает лимиты. Архив направляется на разбор, а пакет объясняет ручное извлечение вложенного архива. Превышающие лимиты, вложенные, уже принятые и нечитаемые элементы пропускаются и перечисляются в разделе "Not unpacked". Длинные имена сокращаются с добавлением хеша, чтобы уложиться в ограничения файловой системы. Сам архив не требует извлечения знаний (`extraction: skipped`).

STT/OCR запускаются автоматически **после выполнения `pip install -r requirements-media.txt`** (см. `01_PREREQUISITES.md` и `15_MEDIA_PROCESSING.md`). При отсутствии бэкенда файл направляется в `review/needs-ai-decision/` с включённой в пакет подсказкой по установке для конкретной ОС; агент должен показать её, **а не** слепо вызывать `ffmpeg`.

## Формат метаданных

Для каждого принятого файла создаётся `processed/extracted-metadata/<name>.yml`:

```yaml
original_filename: "Q2 Strategy Draft v3.docx"
stable_filename: "2026-05-06__q2-strategy-draft-v3.docx"
asset_path: "assets/documents/2026-05-06__q2-strategy-draft-v3.docx"
processed_path: "processed/markdown/2026-05-06__q2-strategy-draft-v3.md"   # null when nothing converted
source_hash: "sha256:a1b2c3d4e5f60718"
file_type: "docx"
asset_type: "documents"
strategy: "docx"                   # converter used (passthrough, csv, stt, ocr, archive, unknown, …)
raw_category: "work"               # raw/<category>/ the file came from
processing_date: "2026-05-06T10:30:00+03:00"
raw_path: "raw/work/unsorted/Q2 Strategy Draft v3.docx"   # where it was dropped (since 0.16)
extracted_at: "2026-05-06"
valid_from: "2026-05-06"
lifecycle: "evolving"              # lifecycle.default
confidence: "medium"
complexity: 0.72
long_book_hint: false
needs_ai_review: true              # a review package exists
review_queue: "review/needs-ai-decision/"   # null → processed/ only
review_reason: "complexity 0.72 >= 0.7"
nlp_meta_path: "processed/nlp-meta/2026-05-06__q2-strategy-draft-v3.yml"
extraction: "pending"              # pending | done | skipped
extracted_to: []                   # knowledge/ pages, filled by --mark-extracted
```

Только при необходимости записываются: `complexity_basis` (нет NER), `source_encoding` (текст не в UTF-8), `previous_version` (новая версия принятого файла), `redaction: pending|resolved` + `redaction_reasons` (проверка приватности; только тип секрета и номер строки, никогда значение), `stt_*` (расшифровки), `archive_extracted_files` / `archive_notes` (архивы), `extraction_note` (пропуск).

Повторная обработка ресурса пересчитывает эти механические поля и сохраняет остальные: запись об извлечении, `importance`, заметки агента.

## Формат записи assets-index

Приём добавляет или обновляет один блок на ресурс в `assets-index/<type>.md`:

```markdown
## 2026-05-06__q2-strategy-draft-v3

- Type: documents
- Original: `assets/documents/2026-05-06__q2-strategy-draft-v3.docx`
- Converted: `processed/markdown/2026-05-06__q2-strategy-draft-v3.md`
- Extracted knowledge: `knowledge/domain/growth-channels.md`, `knowledge/decisions/2026-05-06__q2-budget-shift.md`
- Description: Draft Q2 growth strategy — channels, hypotheses, budget
```

Скрипт управляет строками `Type`, `Original`, `Converted`, `Category`, `Status` и `Extracted knowledge`. Заглушка `Description` записывается один раз; при разборе агент заменяет её кратким описанием в одну строку, а повторная обработка никогда не перезаписывает её или другие добавленные агентом строки.

**Приватный** ресурс (приватная категория или срабатывание сканера секретов) никогда не раскрывает имя файла и пути в индексе или индексируемом `log.md`. Его блок называется `<category> item <sha8>` (префикс хеша оригинала) и содержит `Type`, `Category`, `Status` (проверка приватности ожидается / завершена).

**Базы, наполненные до 0.16**, не записывали `raw_category`, поэтому чаты и личные файлы всё ещё имеют именованные блоки. Повторно обработайте каждый такой ресурс, указав категорию:

```bash
python3 scripts/kb_ingest.py --set-category chats assets/documents/2026-03-02__chat-with-ivan.txt
```

Это записывает `raw_category`, заменяет именованный блок вместе с Description, где может упоминаться имя файла, на нейтральный и открывает проверку приватности в `review/needs-redaction/`. Старые записи `log.md` и `log-archive/` по-прежнему содержат имя; если базой делятся, отредактируйте их вручную. Путь вне `assets/` → код завершения 2.

<a id="extraction-registry"></a>

## Реестр извлечения

Каждый принятый файл ждёт агента: метаданные содержат `extraction: pending`, пока агент не запишет результат. `!review` охватывает очереди `review/needs-*` **и** файлы `processed/` с ожидающими извлечения метаданными (их считает `--status`).

После извлечения знаний из файла:

```bash
# Knowledge went into one or more pages → extraction: done, pages added to extracted_to
python3 scripts/kb_ingest.py --mark-extracted assets/documents/2026-05-06__q2.docx \
  --to knowledge/domain/growth-channels.md --to knowledge/decisions/2026-05-06__q2-budget-shift.md

# Nothing worth keeping → extraction: skipped, reason in extraction_note
python3 scripts/kb_ingest.py --mark-skipped processed/markdown/2026-05-06__q2.md --reason "duplicate of the Q1 memo"
```

- Можно указать путь к ресурсу, обработанной копии, метаданным, NLP-метаданным или пакету разбора. Страницы `--to` должны существовать (`domain/x.md` читается как `knowledge/domain/x.md`).
- Обе команды обновляют блок assets-index, добавляют запись `review` в журнал и меняют `redaction: pending` на `resolved`. Пакет разбора удалите самостоятельно.
- Неизвестный путь или страница → код 2, никаких изменений.

Метаданные до 0.16 не имеют поля `extraction`. Они считаются ожидающими, если только страница `knowledge/` не ссылается на ресурс или обработанную копию в `source:`. Миграция heal `extraction-registry` заполняет поле (`done` + `extracted_to`, если есть ссылка, иначе `pending`).

## Статус

`python3 scripts/kb_ingest.py --status` не меняет базу (может обновить кеш метаданных в `.kb-state/`) и сообщает:

- файлы, ожидающие в `raw/**/unsorted/`, по причинам: `new` (ещё не принят), `empty`, `too-large`, `error` (последний запуск завершился ошибкой именно на этом файле, и с тех пор он не изменился);
- число файлов с `extraction: pending` и возраст самого старого;
- размер каждой очереди `review/needs-*` и возраст самого старого элемента.

`--status --json` выводит те же данные, которые возвращает `kb_ingest.collect_status(root)` (из них строится `STATUS.md`):

```json
{"unsorted": {"total": 2, "by_reason": {"new": 1, "error": 1}},
 "extraction_pending": 9, "extraction_pending_oldest_days": 30,
 "review": {"needs-ai-decision": {"count": 3, "oldest_days": 12}}}
```

## Коды завершения

| Код | Значение |
|------|---------|
| `0` | Все файлы обработаны (пропуски и дубликаты считаются обработанными) |
| `1` | Некоторые файлы не обработаны (перечислены в stderr; остаются в `unsorted/`) |
| `2` | Ошибка окружения или использования: отсутствующий/некорректный `kb.config.yml`, занятая блокировка пайплайна, неизвестный путь или страница `--mark-*`, отсутствующий аргумент пути, путь `--set-category` вне `assets/` |

Отсутствующая библиотека конвертера не считается ошибкой: файл попадает на разбор с указанием причины.

## Идемпотентность

Повторный запуск безопасен. Уже принятое содержимое распознаётся по хешу и перемещается в папку дубликатов, не копируясь в `assets/` второй раз. Повторная обработка ресурса (`kb_ingest.py assets/<type>/<file>`) переписывает производные файлы и сохраняет записи агента. Реестр метаданных кешируется в `.kb-state/ingest-registry.json` (повторно читаются только изменившиеся метаданные). Файлы с ошибками последнего запуска перечислены в `.kb-state/ingest-errors.json`.

---

## Работа с объёмными справочными материалами (книги, курсы, руководства)

Некоторые входные материалы — **объёмные справочные тексты**, а не сырые заметки: опубликованные книги о писательском мастерстве, учебники программирования, книги по бизнес-стратегии, руководства по исследовательской методологии. Пайплайн умеет извлекать их текст, но возникают три риска:

1. **Расход токенов:** книга на 300 страниц ≈ 70–90 тысяч слов. Агент тратит ~50–100 тысяч токенов на попытку пересказать её при разборе.
2. **Неопределённость с авторскими правами:** полный текст защищённой книги в `knowledge/`, а затем в индексе Repomix, сомнителен даже для личного использования и опасен при совместном доступе к базе.
3. **Загрязнение голоса и стиля:** особенно у писателей и авторов контента проза известного автора в `voice/` или `principles/` незаметно проникает в тон ИИ, вытесняя голос пользователя.

Преобразованный `.pdf` или `.docx` с минимум 25 000 слов (либо PDF с минимум 80 страницами) получает `long_book_hint: true` и пакет разбора с описанным ниже сценарием.

### Рекомендуемый подход: PDF как справочник, заметки как знания

```
raw/documents/unsorted/Save-the-Cat.pdf
        ↓ pipeline
assets/documents/2026-05-16__save-the-cat.pdf   ← stays here, NOT indexed
assets-index/documents.md                        ← contains a one-line entry, IS indexed

raw/reference/unsorted/save-the-cat-my-takeaways.md
        ↓ pipeline → processed/ (extraction pending) → !review → knowledge/
knowledge/principles/save-the-cat-beats.md       ← your interpretation, IS indexed
```

Пользователь (или агент при разборе) пишет **сопроводительную заметку**, фиксирующую *правила так, как их понимает пользователь*, его собственными словами. Именно её ИИ читает ежедневно. Оригинальная книга остаётся в `assets/` и открывается по запросу, когда нужна точная цитата или ссылка на страницу.

### Когда агент разбирает объёмную справочную книгу

Если книга попала в `review/needs-ai-decision/`, агенту следует:

1. **Сначала проверить авторские права и объём.** Если это полный текст защищённой книги, НЕ переносить её прозу в `knowledge/`. Вместо этого:
   - Убедиться, что оригинал в `assets/`
   - Описать книгу в записи `assets-index/documents.md` (созданной пайплайном)
   - Спросить пользователя: *«Хотите, я подготовлю заметку с полезными для вас выводами из этой книги? Сформулирую их вашими словами и укажу источник».*
2. **При согласии подготовить заметку с выводами.** 5–15 пунктов или коротких абзацев в `knowledge/principles/<book-slug>-takeaways.md`. Указать источник через `source:` во frontmatter и ссылки на фрагменты (см. `11_PROVENANCE.md`).
3. **Вести индекс книжной полки.** Для ролей, где это происходит регулярно (писатель, исследователь, программист с учебниками, основатель с бизнес-книгами), поддерживать `knowledge/principles/<role>-bookshelf.md`: по строке на книгу, ссылка на заметку с выводами и статус (`read` / `partially read` / `to read`).
4. **Записать результат** через `--mark-extracted … --to <takeaways page>` или `--mark-skipped … --reason "reference only"`.

### Когда извлечение уместно

- **Книги в общественном достоянии** (с истёкшими авторскими правами)
- **Открытые лицензии** (CC-BY и т. п.) — исходный текст можно извлекать
- **Цитаты в рамках добросовестного использования** (абзац, а не глава) — уже предусмотрены шаблоном артефакта `influences`
- **Собственные тексты пользователя** — черновики, рукописи, опубликованные работы, которыми он владеет

### Краткое дерево решений

```
File in raw/documents/unsorted/ is detected as a long PDF/EPUB/DOCX
      ↓
Is it a copyrighted book the user did not write?
      ├─ Yes → asset stays in assets/, agent offers to write a takeaway note
      └─ No  → standard review: extract into knowledge/, then --mark-extracted
```
