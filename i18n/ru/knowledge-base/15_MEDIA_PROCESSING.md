---
translation_of: knowledge-base/15_MEDIA_PROCESSING.md
source_commit: 41b95e18eccb87d255fee3f7c367d1c2e6847849
source_version: 0.9.3
translated_at: 2026-06-29
translator: ai-assisted
---

# 15 — Обработка медиа (транскрибация, OCR, архивы)

> Контракт для превращения **нетекстовых входов** — аудио, видео, изображений, архивов —
> в текст, который pipeline может маршрутизировать, обогащать и индексировать.
>
> **Reference implementations:** `scripts/kb_stt.py` (speech-to-text),
> `scripts/kb_ocr.py` (OCR) и helper `_run_archive` в
> `scripts/kb_ingest.py`. Они уже подключены в `kb_ingest.py` и запускаются
> автоматически во время ingest.

---

## Цели дизайна

1. **Работа из коробки на любой платформе.** Без зависимости от системных утилит,
   которые легко настроить неправильно. Значения по умолчанию ставятся через `pip`
   и несут с собой собственные кодеки и модели. В частности: **системный `ffmpeg` не нужен.**
2. **Local-first / privacy-first.** Транскрибация и OCR выполняются на машине пользователя.
   Cloud backends **выключены по умолчанию** и используются только по явному согласию.
3. **Graceful degradation.** Если backend отсутствует, файл всё равно попадает в `assets/`,
   а в review создаётся пакет с OS-specific подсказкой по установке — pipeline не теряет данные
   и не падает целиком.

## Установка

```bash
pip install -r requirements-media.txt   # faster-whisper + rapidocr
```

Проверка:

```bash
python3 scripts/kb_stt.py --check
python3 scripts/kb_ocr.py --check
python3 scripts/kb_doctor.py            # STT/OCR/ffmpeg появятся в отчёте
```

## Конфигурация (`kb.config.yml` → `media`)

```yaml
media:
  stt:
    enabled: true
    backends: ["faster-whisper", "openai-whisper"]
    model: "small"          # tiny | base | small | medium | large-v3
    language: "auto"        # "auto" или ISO code ("ru", "en", …)
    device: "auto"          # auto | cpu | cuda
    compute_type: "int8"    # int8 (быстрый CPU) | float16 (GPU) | float32
    timestamps: true        # добавлять [mm:ss] per segment
    allow_cloud: false      # не отправлять аудио в облако, пока это false
  ocr:
    enabled: true
    backends: ["rapidocr", "tesseract"]
    language: "auto"
  archives:
    enabled: true
    max_files: 200
```

## Speech-to-text (STT)

- **Backend по умолчанию: `faster-whisper`.** Аудио декодируется через PyAV,
  который поставляется со встроенными FFmpeg libraries — значит, **системный `ffmpeg` не нужен**
  ни на macOS, ни на Windows, ни на Linux.
- **Fallback backend: `openai-whisper`.** Используется только если присутствует в `backends`
  и найден системный `ffmpeg`. `kb_common.find_ffmpeg()` умеет искать шире, чем PATH
  (например, в `/opt/homebrew/bin`), чтобы обойти типичную macOS GUI-PATH проблему.
- Выход: `processed/transcripts/<slug>.md`, где в header зафиксированы backend,
  model, detected language и duration; сегменты перечислены с `[mm:ss]` timestamps, если включены.
- Метаданные: YAML получает поля `stt_backend`, `stt_model`, `stt_language`,
  `stt_duration_seconds`, `stt_segments`.

Поддерживаемые входы: `.mp3 .wav .m4a .flac .ogg .aac .opus` (audio) и
`.mp4 .mov .webm .mkv .avi .m4v` (video — транскрибируется audio track).

## OCR (images / scans / screenshots)

- **Backend по умолчанию: `rapidocr-onnxruntime`** — идёт со своими ONNX models и runtime;
  системные зависимости не требуются.
- **Fallback backend: `tesseract`** через `pytesseract` (требует системный бинарник `tesseract`).
- Выход: `processed/ocr/<slug>.md`.
- Поддерживаемые входы: `.png .jpg .jpeg .webp .tiff .bmp`.

## Архивы

- `.zip`, `.tar`, `.tar.gz`/`.tgz` распаковываются в `raw/unsorted/unsorted/`
  (имена файлов уплощаются и префиксуются именем архива), чтобы каждый файл
  был снова обработан на следующем проходе ingest. Короткий листинг попадает в
  `processed/markdown/`.
- `.rar` стандартная библиотека не распаковывает — такой файл уходит в review
  с подсказкой распаковать вручную (или установить инструмент наподобие `unar`).
- `media.archives.max_files` ограничивает число извлекаемых файлов как защита от zip bomb.

## Поведение агента (важно)

Когда приходит audio/video/image-файл, а транскрибация или OCR недоступны,
review package в `review/needs-ai-decision/` содержит точную install-команду
для ОС пользователя. Агент должен:

1. **Сначала запустить `python3 scripts/kb_doctor.py`**, чтобы подтвердить, что именно доступно.
2. **Показать пользователю install hint** (например: `pip install -r requirements-media.txt`).
   Не нужно слепо вызывать `ffmpeg` или предполагать, что системные утилиты уже есть.
3. Только после установки backend-а перезапустить ingest (`./shell/reindex.sh`
   или `python3 scripts/kb_reindex.py`) — не транскрибировать вручную в чате,
   если только пользователь сам этого не хочет.

## Поведение по завершению

Media-шаги никогда не пробрасывают исключение наружу из ingest: отсутствие backend-а
перехватывается и превращается в review-routing с подсказкой. Прогон, состоящий
только из media-файлов без backend-а, всё равно завершается с кодом `0`:
файлы сохранены, queued, automation/watchers продолжают работать.
