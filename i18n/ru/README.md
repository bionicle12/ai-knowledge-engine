---
translation_of: README.md
source_commit: 41b95e18eccb87d255fee3f7c367d1c2e6847849
source_version: 0.9.3
translated_at: 2026-06-29
translator: ai-assisted
---

<div align="center">

# 🧠 AI Knowledge Engine

**Превращает любого AI coding agent в самообучающийся движок знаний.**

Модульный фреймворк на базе инструкций, который учит AI-агентов (Claude, GPT, Cursor, Codex, Gemini)
создавать, поддерживать и развивать структурированную персональную базу знаний —
с local-first NLP и автоматической индексацией контекста.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](#требования)
[![Node.js 20+](https://img.shields.io/badge/Node.js-20+-339933.svg?logo=node.js&logoColor=white)](#требования)
[![Tests](https://img.shields.io/badge/tests-166_passing-brightgreen.svg)](#)
[![Coverage](https://img.shields.io/badge/coverage-69%25-yellow.svg)](#)
[![Version](https://img.shields.io/badge/version-0.9.3-blue.svg)](../../VERSION)
[![No Cloud Required](https://img.shields.io/badge/Cloud-Not_Required-green.svg)](#)

[English](../../README.md) · [Быстрый старт](#быстрый-старт) · [Возможности](#возможности) · [Архитектура](#архитектура) · [Примеры ролей](#примеры-ролей)

</div>

---

## Что это?

**AI Knowledge Engine** — это набор модульных Markdown-инструкций, которые любой AI-агент может прочитать и выполнить, чтобы:

1. 🗂️ **Индексировать кодовую базу** — упаковать проект в один AI-читаемый контекстный файл (настройка за 5 минут)
2. 🧠 **Построить базу знаний** — развернуть полноценный Raw-First Knowledge Pipeline с NLP-обогащением, provenance, self-learning и автоматическим обслуживанием

Никакого SaaS. Никаких API-ключей. Никакого облака. Всё работает локально на вашей машине.

> **Независимо от индексатора:** из коробки есть поддержка [Repomix](https://github.com/yamadashy/repomix), но архитектура рассчитана на любой инструмент, который умеет превращать кодовую базу в AI-контекст.

---

## Два режима

| Режим | Что вы получаете | Время настройки |
|------|------------------|-----------------|
| **Lite** → `quick-start/` | AI-оптимизированный индекс кодовой базы с автообновлением на каждый git commit | ~5 минут |
| **Full** → `knowledge-base/` | Персональный движок знаний с NLP, self-learning loop, AI review queue, health-checks и умным расписанием | ~30 минут |

---

## Быстрый старт

### Lite Mode: индексация кодовой базы

```bash
# 1. Установить индексатор
npm install -g repomix

# 2. Скопировать quick-start/ в свой проект
cp -r quick-start/ /path/to/your-project/docs/ai-init/

# 3. Сказать AI-агенту:
"Прочитай docs/ai-init/INIT_GUIDE.md и настрой индексацию контекста для этого проекта"
```

AI-агент проанализирует структуру проекта, настроит индексатор, установит git hooks и сгенерирует первый снимок контекста.

### Full Mode: база знаний

```bash
# 1. Скопировать knowledge-base/ из этого репо в свой проект как `setup/`
cp -r knowledge-base/ /path/to/your-project/setup/

# 2. Открыть проект в IDE с AI-агентом
cd /path/to/your-project

# 3. В чате отправить РОВНО это:
#
#    "Read setup/README.md and setup/00_OVERVIEW.md, then deploy a
#     knowledge base for [your role] inside ./knowledge-base/.
#     When kb_doctor passes, run setup/shell/finalize.sh to flatten
#     the base into the project root."
```

Агент:
1. Задаст уточняющие вопросы по вашей роли или придумает кастомную конфигурацию
2. Построит базу **внутри `./knowledge-base/`**, не трогая исходный `setup/`
3. Параметризует `kb.config.yml`, `AGENTS.md`, `KNOWLEDGE_STRUCTURE.md`
4. Сгенерирует `DATA_PLACEMENT_EXAMPLES.md` детерминированно и без токенов через `kb_populate.py`
5. Сгенерирует `START_HERE.md` — ваш первый файл после развёртывания
6. Запустит `kb_doctor.py`, чтобы проверить, что всё связано корректно
7. **Запустит `bash setup/shell/finalize.sh`** — поднимет содержимое `knowledge-base/` в корень проекта и удалит `setup/` и временную `knowledge-base/`

После развёртывания корень проекта выглядит так:

```text
your-project/
├── START_HERE.md              ← читайте это первым
├── AGENTS.md                  ← инструкции для агента
├── kb.config.yml              ← конфиг
├── DATA_PLACEMENT_EXAMPLES.md ← куда что класть (под вашу роль)
├── reindex.command            ← macOS double-click
├── watcher-start.command      ← macOS double-click
├── watcher-stop.command       ← macOS double-click
├── reindex.bat, watcher-start.bat ← Windows double-click
├── shell/                     ← Linux/CLI: watcher.sh, reindex.sh, lint.sh, doctor.sh
├── scripts/                   ← Python pipeline
├── templates/, examples/
├── raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/
└── .repomix/                  ← AI-ready output
```

> ⚠️ **Критично:** каждую новую чат-сессию начинайте строкой: *"Read AGENTS.md and use it as the primary instruction for everything that follows."* Иначе агент не знает о существовании вашей базы знаний. `START_HERE.md` будет это напоминать.

---

## Возможности

### Lite Mode
- 📦 **Настройка одной командой** — AI-агент сам выполняет всю конфигурацию
- 🔄 **Автообновление** — Git hooks пересобирают контекст на каждый commit
- 🎯 **Понимание стека** — готовые паттерны для React, Rust, Python, Go, Node.js и не только
- 🔒 **Сканирование безопасности** — поиск утекших секретов до индексации
- 📊 **Контроль токенов** — Tree-sitter-сжатие уменьшает объём на 50-70%
- 📂 **Профили** — отдельные context files по подсистемам: backend, frontend, infra

### Full Mode
- 🔬 **Raw-First Pipeline** — кидаете PDF, DOCX, PPTX в `raw/` → авто-конвертация в Markdown → NLP-обогащение → чистые знания
- 🎙️ **Media Processing** — транскрибация аудио/видео, OCR по изображениям и распаковка архивов работают из коробки через локальные optional backends
- 🧠 **Self-Learning Loop** — `!save` для сессий, `!reflect` для higher-level insights, `!audit` для полного review
- 🔗 **Cross-Linked Knowledge** — `[[wikilinks]]` и routing tables для навигации по сотням страниц
- 📊 **NLP Enrichment** — NER, keyword extraction, entity resolution (spaCy + KeyBERT) — ноль токенов, чистый CPU
- 📜 **Provenance Tracking** — каждый факт привязан к источнику через хеши и span-level citations
- 🔍 **Surprise Filter** — антидубликация: в базу попадает только реально новая информация
- ⚕️ **Health Checks** — Python-based lint для stale pages, orphan pages, broken links и contradictions
- ⏰ **Smart Scheduling** — авто-рефлексия по importance threshold, с пропуском пустых периодов
- 🔐 **Privacy-by-Default** — raw, review и interaction logs никогда не индексируются
- 🌍 **Полная портабельность** — чистые Markdown-файлы, без БД и серверов, работает на любой машине с `rsync`
- 🔧 **Reference Implementations** — Python и shell-скрипты копируются и используются как есть, а не изобретаются заново
- ⬆️ **Upgrade Path** — `kb_upgrade.py` обновляет развернутые базы, стараясь сохранить пользовательские кастомизации

---

## Архитектура

```text
                    ┌─────────────┐
Пользователь ─────→ │   raw/      │  ← PDF, DOCX, заметки, чаты, скриншоты
                    └──────┬──────┘
                           │ kb_ingest.py (Python + NLP)
                           ▼
                    ┌─────────────┐
                    │ processed/  │  ← Markdown + NLP metadata (0 токенов)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │knowledge/│ │ review/  │ │ assets/  │
        │ (clean)  │ │(complex) │ │(binary)  │
        └────┬─────┘ └──────────┘ └──────────┘
             │
             ▼ индексатор контекста
        ┌──────────────┐
        │  output.xml  │  ← AI-ready snapshot
        └──────────────┘
```

### Cost Model

Расход токенов зависит от **рабочего режима** (`mode` в `kb.config.yml`):

| Уровень | Операции | default | super |
|--------|----------|--------:|------:|
| **Python (бесплатно)** | NLP, lint L1, конвертация | 0 tok | 0 tok |
| **Лёгкий AI** | Оценка важности | ~500 | ~1-2K |
| **Mode-switched** | Surprise filter, annotations, entity resolution | 0 tok (Python) | ~3-9K tok (AI) |
| **Тяжёлый AI** | Reflection, deep review, writeback | ~15-100K | ~15-100K |

| Режим | В день (активно) | В неделю |
|------|------------------:|---------:|
| `default` | **~3-4K токенов** | ~20-30K |
| `super` | **~50-200K+ токенов** | ~500K-1.5M |

---

## Структура знаний

Полный режим создаёт богатую и довольно opinionated-структуру прямо в **корне проекта** (без вложенной `knowledge-base/`):

```text
your-project/
├── START_HERE.md               # Читайте это первым
├── AGENTS.md                   # Инструкции для AI-агента (генерируется автоматически)
├── KNOWLEDGE_STRUCTURE.md      # Эта карта
├── DATA_PLACEMENT_EXAMPLES.md  # "Есть X → положи сюда" (под роль)
├── kb.config.yml               # Конфиг: роль, сущности, режим
├── repomix.config.json         # Конфиг индексатора
├── requirements.txt
│
│   # Double-click launchers (macOS / Windows) лежат в корне:
├── reindex.command, reindex.bat                      # Ручной reindex
├── watcher-start.command, watcher-start.bat          # Авто-пайплайн
├── watcher-stop.command                              # Остановить daemon на macOS
│
├── shell/                      # Linux / CLI: *.sh wrappers
│   ├── watcher.sh, reindex.sh
│   ├── lint.sh, doctor.sh
│   └── (launchers были подняты в корень через finalize.sh)
│
├── scripts/                    # Python pipeline (лучше не править без необходимости)
│   ├── kb_ingest.py            # Raw → processed → knowledge
│   ├── kb_lint.py              # Health check (Level 1)
│   ├── kb_reflect.py           # Логика запуска reflection
│   ├── kb_watch.py             # File watcher daemon
│   ├── kb_nlp_batch.py         # Batch NLP re-enrichment
│   ├── kb_populate.py          # Генерация DATA_PLACEMENT_EXAMPLES.md
│   ├── kb_doctor.py            # Smoke test
│   └── kb_common.py            # Общие утилиты
├── templates/                  # Остаются для повторных запусков (kb_populate, kb_upgrade)
├── examples/                   # Role YAMLs
│
├── raw/                        # 🚫 Сырые материалы (НЕ индексируются)
│   ├── documents/unsorted/
│   ├── reference/unsorted/
│   ├── work/unsorted/
│   ├── chats/unsorted/
│   ├── media/unsorted/
│   ├── personal-context/unsorted/
│   └── unsorted/
│
├── processed/                  # 🚫 Конвертированные артефакты (НЕ индексируются)
├── assets/                     # 🚫 Бинарные оригиналы (НЕ индексируются)
│
├── knowledge/                  # ✅ Чистые знания — ИНДЕКСИРУЮТСЯ
│   ├── profile/, principles/, voice/
│   ├── domain/, projects/, decisions/
│   ├── playbooks/, insights/, opinions/
│   ├── timelines/, routing/
│   ├── open-questions/
│   └── _archive/
│
├── assets-index/               # ✅ Markdown-описания ассетов — ИНДЕКСИРУЮТСЯ
├── review/                     # 🚫 Очереди review (НЕ индексируются)
│   ├── needs-classification/
│   ├── needs-ai-decision/
│   ├── needs-redaction/
│   └── excluded-sensitive/
│
├── interactions/               # 🚫 Логи сессий (напрямую НЕ индексируются)
└── .repomix/output.xml         # 🚫 Сгенерированный индекс (пересобирается локально)
```

---

## Запуск watcher (автообработка raw)

Watcher следит за `raw/<sub>/unsorted/` и запускает ingest pipeline, когда туда падают новые файлы.

### macOS (double-click, без терминала)

| Действие | Файл |
|---------|------|
| Запустить watcher | Двойной клик по `watcher-start.command` |
| Остановить watcher | Нажать Ctrl+C в открывшемся окне Terminal — или, если запускали daemon mode, двойной клик по `watcher-stop.command` |
| Ручной reindex | Двойной клик по `reindex.command` |

### Linux

```bash
./shell/watcher.sh              # foreground, Ctrl+C для остановки
./shell/watcher.sh --daemon     # background
./shell/watcher.sh --status
./shell/watcher.sh --stop
./shell/reindex.sh              # one-shot reindex
```

### Windows

| Действие | Файл |
|---------|------|
| Запустить watcher | Двойной клик по `watcher-start.bat` |
| Остановить watcher | Закрыть окно cmd или нажать Ctrl+C |
| Ручной reindex | Двойной клик по `reindex.bat` |

---

## Команды пользователя

Это команды, которые вы говорите AI-агенту в IDE-чате.

> 🚨 **Перед любой командой в новом чате сначала отправьте:**
> *"Read AGENTS.md and use it as the primary instruction for everything that follows."*

| Команда | Что делает | Стоимость | Когда использовать |
|---------|------------|-----------|--------------------|
| `!save` | Сохраняет session summary с ключевыми решениями и инсайтами | ~2K токенов | После продуктивных сессий от 45+ минут |
| `!reflect` | Синтезирует higher-level insights из накопленных фактов | ~15K токенов | Автотриггером или вручную |
| `!audit` | Полный AI-review базы: contradictions, gaps, merge candidates | ~50–100K токенов | Раз в 2–4 недели |
| `!review` | Разбирает очереди `review/`: превращает помеченные материалы в страницы `knowledge/`, редактирует чувствительное, задаёт вопросы, если нужен ввод | ~5–30K токенов | Когда после ingest накапливается `review/needs-ai-decision/` |
| `!populate` | Перегенерирует `DATA_PLACEMENT_EXAMPLES.md` (после правок в role YAML) | ~50 токенов | После редактирования `examples/<role>.yml` |
| `!super` | Переключает режим: default ↔ super | 0 токенов | Когда нужна максимальная скорость обучения |
| `!super on/off` | Явно включает или выключает super mode | 0 токенов | См. Operating Modes |
| `!super status` | Показывает текущий режим | 0 токенов | Быстрая проверка |

### Operating Modes

Система поддерживает два режима, управляемых через `!super`:

| Режим | Парадигма | Token Cost | Лучше для |
|------|-----------|------------|-----------|
| **default** | Python-first, throttled | ~3-4K/день | Ограниченный токен-бюджет, ежедневная работа |
| **super** | AI-first, on-demand | ~50-200K+/день | Безлимитные планы, интенсивное накопление знаний |

**Default mode** использует Python-first processing: NLP, heuristic filters и бережное расписание AI-вызовов.
AI подключается только для importance scoring и surprise checks по большим документам.

**Super mode** заменяет Python-эвристики полноценным AI-анализом на каждом шаге:
- 🔍 **Semantic surprise detection** — AI оценивает каждый ingest на реальную новизну (+40% к точности относительно Python NLP overlap)
- 📝 **Intelligent annotations** — AI генерирует содержательные связи и предложенные правки (+60% пользы относительно шаблонных annotations)
- 🌐 **Cross-language entity resolution** — AI понимает синонимы и мультиязычные варианты (+30% coverage)
- ⚡ **On-demand reflection** — запускается после каждого значимого ingest (importance ≥5), а не по недельному расписанию
- 🧪 **Daily AI audit** — Lint Level 2 автоматически срабатывает при консолидации
- 📥 **Auto review processing** — `review/needs-ai-decision/` разбирается без ожидания `!audit`

> ⚠️ **Внимание:** super mode может сжечь весь дневной лимит токенов за одну активную сессию. Используйте только с безлимитным или высоким лимитом.

### Умные триггеры

Система отслеживает **importance score** каждого ingest-элемента. Когда суммарный score превышает порог (default: 25, super: 5), reflection запускается автоматически. Если ничего не изменилось — токены не тратятся.

```text
Дней без reflection:  1  2  3  4  5  6  7  8  9
Изменения?            -  -  -  -  -  -  -  -  ✓
                                                 ↑
                                        Trigger! (>7 days + changes exist)
```

---

## Модули инструкций

Система knowledge base собирается из модульных instruction files, которые AI-агент читает последовательно:

| # | Модуль | Назначение |
|---|--------|-----------|
| 00 | Overview | Карта развёртывания: что читать, что копировать, в каком порядке (read first) |
| 01 | Prerequisites | Проверка окружения: Node.js, Python, Git, indexer |
| 02 | Init | Уточнение роли, выбор сущностей, создание структуры |
| 03 | Pipeline | Python ingest script: конвертация + NLP + source hashing |
| 04 | Review | AI review workflow для сложных/неоднозначных материалов |
| 05 | Index | Индексация контекста, `[[wikilinks]]`, routing tables |
| 06 | Agents Template | Шаблон `AGENTS.md` с token budget |
| 07 | Interaction Loop | Self-learning + session capture + query writeback |
| 08 | Portable | Портабельность + Dynamic Context Enrichment |
| 09 | Lint | Health checks: Level 1 (Python) + Level 2 (AI) + `--metrics` |
| 10 | Log | Append-only хронология операций |
| 11 | Provenance | Source hash, span citations, regression tests |
| 12 | NLP Preprocess | NER + keyword extraction + entity resolution |
| 13 | Autorun | File watcher, git hooks, smart scheduling |
| 14 | Initial Population | Генерация role-specific `DATA_PLACEMENT_EXAMPLES.md` |
| 15 | Media Processing | STT, OCR, архивы и graceful degradation |

---

## Примеры ролей

Готовые конфигурации лежат в `knowledge-base/examples/`:

| Шаблон | Роль | Highlights |
|--------|------|------------|
| `programmer-senior.yml` | Senior Software Engineer | Архитектура, debugging, стек, code principles |
| `marketing-director.yml` | Marketing Director | Стратегия, бренд, кампании, анализ аудитории |
| `creative-hybrid.yml` | Creative Hybrid | Код + music production + indie gamedev |
| `product-manager.yml` | Product Manager | Приоритизация, метрики, user research, PRD |
| `researcher.yml` | Researcher / Analyst | Literature graph, гипотезы, методология |
| `founder.yml` | Startup founder | Инвесторы, найм, продукт, decision logs |
| `startup-opportunity-explorer.yml` | Startup Opportunity Explorer | Идеи, рыночные гэпы, валидация, web-app MVPs |
| `content-creator.yml` | Content creator | Voice fingerprinting, аудитория, монетизация |
| `fiction-writer.yml` | Fiction writer | Craft theory, voice training по influences, critique драфтов |
| `psychologist-gestalt.yml` | Gestalt-oriented psychologist | Этика, анонимизированные кейсы, супервизия, Gestalt interventions |
| `music-video-director.yml` | Music video writer-director | Хип-хоп и short-form concepts, treatments, production, edit rhythm |
| `russian-software-engineering-student.yml` | Software engineering student in Russia | Учебный план, лабы, экзамены, вузовские документы, стажировки |

Не нашли свою роль? Просто скажите AI-агенту свою профессию — он сгенерирует кастомную конфигурацию с релевантными сущностями, knowledge paths и примерами workflow.

---

## Поддерживаемые AI-агенты

Тестировалось и проектировалось под:

| Агент | Статус | Комментарий |
|------|--------|-------------|
| **Claude** (Anthropic) | ✅ Fully supported | Cursor, API, Claude Desktop |
| **GPT** (OpenAI) | ✅ Fully supported | Cursor, Copilot, ChatGPT |
| **Codex CLI** | ✅ Fully supported | OpenAI Codex |
| **Gemini** | ✅ Fully supported | JetBrains AI, Google AI Studio |
| **Любой Markdown-capable агент** | ✅ Compatible | Должен уметь читать `.md` и запускать shell-команды |

---

## Требования

| Компонент | Минимум | Для чего нужен |
|-----------|---------|----------------|
| **Node.js** | 20.0+ | Context indexer (Repomix) |
| **Python** | 3.11+ | Ingest pipeline, NLP, lint |
| **Git** | любой | Hooks, history tracking |
| **IDE с AI** | обязательно | Взаимодействие с агентом |

### Optional system tools

```bash
# Ubuntu / Debian
sudo apt install -y pandoc poppler-utils tesseract-ocr

# macOS
brew install pandoc poppler tesseract
```

---

## Содействие

Вклад приветствуется. Чем можно помочь:

- 🌍 **Переводы** — перевести instruction modules на другие языки
- 📝 **Role Templates** — добавить `examples/*.yml` для новых профессий
- 🔧 **Pipeline Scripts** — улучшать Python ingest, NLP и lint scripts
- 📖 **Документация** — прояснять инструкции, добавлять диаграммы, чинить неточности
- 🧪 **Testing** — пробовать проект с разными AI-агентами и сообщать о совместимости

Перед крупной работой лучше сначала открыть issue и обсудить подход.

---

## Лицензия

[MIT](../../LICENSE) — свободно для личного и коммерческого использования.

---

<div align="center">

**Сделано для людей, которые разговаривают с AI.**

Если проект помогает вам выстроить лучший knowledge workflow — [⭐ поставьте звезду](../../).

</div>
