---
translation_of: knowledge-base/01_PREREQUISITES.md
source_commit: 1237e839a201180ed4cfa249a370365be0f63c37
source_version: 0.8.1
translated_at: 2026-05-16
translator: human
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

Создать в корне базы:

```txt
pyyaml>=6.0
python-slugify>=8.0
python-docx>=1.1
python-pptx>=0.6.23
pypdf>=5.0
pandas>=2.2
openpyxl>=3.1
```

Опционально (OCR, изображения):

```txt
pytesseract>=0.3
pillow>=10.0
```

## Системные утилиты (опционально)

| Утилита | Зачем |
|---|---|
| `pandoc` | DOCX/HTML/MD конвертации |
| `poppler-utils` / `pdftotext` | Текст из PDF |
| `tesseract` | OCR для сканов |
| `ffmpeg` | Аудио из видео для STT |

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
# Tesseract и Poppler — через Chocolatey/Scoop, добавить в PATH
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
