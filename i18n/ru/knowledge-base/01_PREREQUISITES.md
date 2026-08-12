---
translation_of: knowledge-base/01_PREREQUISITES.md
source_commit: 4dbd06897ededf6c49c1c5f3ead9a299b51638b9
source_version: 0.12.0
translated_at: 2026-08-13
translator: ai-assisted
---

# 01 — Проверка окружения

> AI-агент должен выполнить эти проверки **до** создания структуры базы. Если чего-то не хватает — дать пользователю команды установки под его ОС.
>
> **Reference template:** `knowledge-base/templates/requirements.txt`. Агент копирует его в корень развёрнутой базы как `requirements.txt`.
> **После развёртывания** запусти `python3 scripts/kb_doctor.py` — он автоматически проверит окружение, зависимости, структуру и spaCy-модель.

---

## Обязательные компоненты

| Инструмент | Минимум | Рекомендация | Зачем |
|---|---:|---:|---|
| Node.js | `20.0.0+` | `22 LTS+` | Запуск Repomix |
| Python | `3.11+` | `3.12+` | Локальный ingest-пайплайн |
| Git | любая | актуальная | История изменений, hooks |
| Repomix | любая | актуальная | Индексация знаний |
| IDE с AI | обязательно | Codex / Cursor / JetBrains + AI | Ревью и работа с базой |

## Проверка

```bash
node --version      # >= 20.0.0
python3 --version   # >= 3.11
git --version
repomix --version
```

Если `python` не найден, попробуй `python3`.

## Установка Repomix

```bash
# Глобально
npm install -g repomix

# Или без установки
npx repomix@latest
```

## Python virtual environment

```bash
# Создать venv в корне базы
python3 -m venv .venv

# Активировать
source .venv/bin/activate        # Linux/macOS
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell

# Установить зависимости
pip install --upgrade pip
pip install -r requirements.txt
```

## requirements.txt

Скопируй `templates/requirements.txt` из этого репозитория в корень базы. Версии зафиксированы по minor-диапазонам для воспроизводимости:

```text
pyyaml>=6.0,<7.0
python-slugify>=8.0,<9.0
python-frontmatter>=1.1,<2.0
python-docx>=1.1,<2.0
python-pptx>=0.6.23,<1.0
pypdf>=5.0,<6.0
pandas>=2.2,<3.0
openpyxl>=3.1,<4.0
spacy>=3.7,<4.0
rake-nltk>=1.0,<2.0
keybert>=0.8,<1.0
watchdog>=4.0,<5.0
```

## Media: транскрибация (STT) и OCR — из коробки, на всех платформах

Транскрибация аудио/видео и OCR по изображениям **опциональны** и вынесены в отдельный
requirements-файл, чтобы базовая установка оставалась лёгкой. Значения по умолчанию
подобраны так, чтобы работать на macOS, Windows и Linux **без системных утилит** —
в частности, **системный `ffmpeg` не нужен**:

```bash
pip install -r requirements-media.txt
```

Это установит:

| Возможность | Библиотека | Системная зависимость? |
|-------------|------------|------------------------|
| Speech-to-text (audio + video) | `faster-whisper` | **Нет** — декодирует аудио через встроенный PyAV |
| OCR (images / scans) | `rapidocr-onnxruntime` | **Нет** — поставляется со своими ONNX-моделями |

> **Почему это важно (ловушка с macOS ffmpeg):** раньше подход опирался на системный
> `ffmpeg`. На Apple Silicon Homebrew ставит его в `/opt/homebrew/bin`, а этот путь
> часто **не попадает** в PATH, который IDE передаёт дочерним процессам. В итоге
> `ffmpeg` "как бы установлен", но транскрибация падает с ошибкой *"ffmpeg not found"*.
> `faster-whisper` полностью обходит эту проблему.

После установки проверьте, что backends видны:

```bash
python3 scripts/kb_stt.py --check
python3 scripts/kb_ocr.py --check
python3 scripts/kb_doctor.py        # также покажет статус STT/OCR/ffmpeg
```

Полный контракт — в `15_MEDIA_PROCESSING.md`.

## Системные утилиты (действительно опциональны)

Они нужны только для альтернативных backends — настройки по умолчанию выше в них не нуждаются.

| Утилита | Когда реально нужна |
|---|---|
| `pandoc` | Более качественные DOCX/HTML/MD конвертации |
| `poppler-utils` / `pdftotext` | Альтернативное извлечение текста из PDF |
| `tesseract` | Только если вы выбрали Tesseract OCR вместо RapidOCR |
| `ffmpeg` | Только если вы выбрали `openai-whisper` вместо faster-whisper |

### Ubuntu

```bash
sudo apt update
sudo apt install -y pandoc poppler-utils tesseract-ocr ffmpeg
```

### macOS

```bash
brew install pandoc poppler tesseract ffmpeg
```

### Windows

```powershell
winget install Gyan.FFmpeg
# Tesseract и Poppler — через Chocolatey/Scoop, затем добавить в PATH
```

Если Node.js из пакетного менеджера старее 20.0.0 — установить через `nvm`, `fnm` или NodeSource.

---

## Контрольная проверка

После установки все 4 команды должны работать без ошибок:

```bash
node --version && python3 --version && git --version && repomix --version
```

Если PowerShell блокирует activate-скрипт:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
