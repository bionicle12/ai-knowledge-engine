---
translation_of: knowledge-base/01_PREREQUISITES.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 01 — Проверка окружения

> AI-агент должен выполнить эти проверки **до** создания структуры базы знаний. Если чего-то нет, дайте пользователю команды установки для его ОС.
>
> **Рабочий каталог:** корень проекта — папка, содержащая `setup/` (скопированный набор развёртывания). Все команды ниже рассчитаны на него.
> **Эталонные шаблоны:** `setup/templates/requirements*.txt`. Агент копирует их в корень развёрнутой базы в фазе 1 `02_INIT.md`.
> **После развёртывания** запустите `python3 scripts/kb_doctor.py` (или `bash shell/doctor.sh`) — он повторно проверяет окружение, зависимости, структуру и модель spaCy. Проверка **пройдена при коде выхода 0**; одни предупреждения не приводят к провалу.

---

## Обязательные компоненты

| Инструмент | Минимум | Рекомендуется | Зачем |
|------|--------:|------------:|-----|
| Node.js | `20.0.0+` | `22 LTS+` | Запускает Repomix |
| Python | `3.11+` | `3.12+` | Локальный конвейер ingest |
| Git | любой | актуальный | История, hooks |
| Repomix | `1.14.0` | версия из `index.repomix_version` | Индексация знаний (глобальная установка или резервный запуск через `npx`) |
| IDE с AI | обязательна | Codex / Cursor / JetBrains + AI | Проверка и взаимодействие с базой |

## Проверка

```bash
node --version      # >= 20.0.0
python3 --version   # >= 3.11
git --version
repomix --version   # or, without a global install: npx --yes repomix@1.14.0 --version
```

Если `python` не найден, попробуйте `python3` (Windows: `py -3`).

## Установка Repomix

```bash
# Globally, pinned to the version the base expects (index.repomix_version)
npm install -g repomix@1.14.0
```

Без глобального `repomix` скрипт `kb_reindex.py` запускает `npx --yes repomix@<index.repomix_version>`, пока `index.npx_fallback` равен `true` (значение по умолчанию). Для этого нужны Node.js с `npm` и доступ к сети при первом запуске. Установите `index.npx_fallback: false` в `kb.config.yml`, чтобы требовать глобальную установку.

## Виртуальное окружение Python — в корне проекта

Создайте venv в **корне проекта**, рядом с `setup/` — в папке, которая после `finalize.sh` станет корнем базы. Никогда не создавайте его внутри `knowledge-base/` или `setup/`: virtualenv жёстко сохраняет абсолютный путь и ломается при переносе, поэтому `finalize.sh` никогда его не перемещает.

```bash
# Linux / macOS — from the project root
python3 -m venv .venv
source .venv/bin/activate        # later `python3 ...` commands use the venv
python3 -m pip install --upgrade pip
python3 -m pip install -r setup/templates/requirements.txt
```

```powershell
# Windows PowerShell — from the project root
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r setup\templates\requirements.txt
```

Shell-обёрткам (`shell/*.sh`) и launchers для двойного клика не нужна активация venv: они используют `.venv/` в корне базы, а пока база строится в `knowledge-base/` рядом с `setup/` — `.venv/` в корне проекта, затем переходят к `python3` (launchers для двойного клика также принимают `venv/` старых баз). Задайте `KB_PYTHON=/path/to/python`, чтобы явно выбрать интерпретатор.

**`ensurepip is not available`** (Debian / Ubuntu): модуль venv поставляется отдельным пакетом. Установите его, удалите недосозданную `.venv/` и снова выполните `python3 -m venv .venv`:

```bash
sudo apt install python3-venv     # or the versioned package the error names, e.g. python3.12-venv
```

**Перемещённый или сломанный venv** (`.venv/bin/pip` не работает, `VIRTUAL_ENV` указывает на старую папку, после активации `python3` остаётся системным): не ремонтируйте его. Удалите `.venv/` и создайте заново командами выше. `kb_doctor.py` предупреждает о таком venv.

**База остаётся в подпапке** (вы пропускаете `finalize.sh` и удаляете `setup/`): тогда обёртки ищут только `<base>/.venv`, поэтому создайте venv внутри папки базы или задайте `KB_PYTHON`.

## Файлы requirements

Агент копирует все эти файлы в корень базы (02, фаза 1). Версии закреплены в самих файлах — читайте их там, не перепечатывайте список.

| Файл | Что устанавливает | Когда |
|------|------------------|------|
| `requirements.txt` | Основа: YAML/frontmatter, конвертация документов (DOCX, PPTX, PDF, RTF, XLSX/CSV), spaCy + RAKE для NLP, наблюдатель за файлами | Всегда |
| `requirements-nlp.txt` | Ключевые слова KeyBERT — подтягивает PyTorch | Необязательно; без него ingest использует ключевые слова RAKE |
| `requirements-media.txt` | Распознавание речи и OCR (ниже) | Необязательно |
| `requirements-dev.txt` | pytest | Только для разработки движка |

KeyBERT подтягивает PyTorch, а обычный `pip` выбирает CUDA-сборку (гигабайты, много минут). Сначала установите wheel только для CPU:

```bash
python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python3 -m pip install -r setup/templates/requirements-nlp.txt
```

### Данные NLP: модель spaCy и NLTK

- spaCy нужна языковая модель (`python3 -m spacy download ru_core_news_md` или `en_core_web_md`) — см. `12_NLP_PREPROCESS.md`.
- RAKE нужны данные NLTK `stopwords` и `punkt`. Без них извлечение ключевых слов ничего не находит:

  ```bash
  python3 -m nltk.downloader stopwords punkt punkt_tab
  ```

## Медиа: транскрибация (STT) и OCR — из коробки на всех платформах

Транскрибация аудио/видео и OCR изображений **необязательны** и вынесены в отдельный файл requirements, чтобы основная установка оставалась лёгкой. Настройки по умолчанию работают в macOS, Windows и Linux **без системных утилит** — в частности, **системный `ffmpeg` не требуется**:

```bash
python3 -m pip install -r setup/templates/requirements-media.txt
```

Устанавливаются:

| Возможность | Библиотека | Системная зависимость? |
|------------|---------|--------------------|
| Распознавание речи (аудио + видео) | `faster-whisper` | **Нет** — декодирует аудио через встроенный PyAV |
| OCR (изображения / сканы) | `rapidocr-onnxruntime` | **Нет** — поставляет собственные ONNX-модели |

> **Почему:** Homebrew `ffmpeg` в `/opt/homebrew/bin` часто отсутствует в PATH, который IDE передаёт дочерним процессам, и транскрибация падала с *«ffmpeg not found»*. `faster-whisper` не нуждается в `ffmpeg`.

После установки проверьте доступность бэкендов:

```bash
python3 setup/scripts/kb_stt.py --check
python3 setup/scripts/kb_ocr.py --check
```

`kb_doctor.py` тоже сообщает состояние STT/OCR/ffmpeg. Полный контракт — в `15_MEDIA_PROCESSING.md`.

## Системные утилиты (действительно необязательные)

Они нужны лишь отдельным альтернативным бэкендам — настройки выше их не требуют.

| Утилита | Когда действительно нужна |
|---------|---------------------------|
| `pandoc` | Более богатые преобразования DOCX/HTML/MD |
| `poppler-utils` / `pdftotext` | Альтернативное извлечение текста PDF |
| `tesseract` | Бэкенд Tesseract OCR. RapidOCR (по умолчанию) читает только китайский и английский, поэтому для OCR другого текста нужен Tesseract с данными соответствующего языка и `pytesseract` (`requirements-media.txt`; см. `15_MEDIA_PROCESSING.md`) |
| `ffmpeg` | Только если вместо faster-whisper выбран STT-бэкенд `openai-whisper` |

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
# Tesseract and Poppler — via Chocolatey/Scoop, add to PATH
```

Если Node.js из вашего пакетного менеджера старее 20.0.0 — установите через `nvm`, `fnm` или NodeSource.

---

## Итоговая проверка

После установки все команды должны выполняться успешно:

```bash
node --version && python3 --version && git --version
repomix --version || npx --yes repomix@1.14.0 --version
```

Если PowerShell блокирует скрипт активации:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
