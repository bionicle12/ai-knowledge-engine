---
translation_of: knowledge-base/00_OVERVIEW.md
source_commit: e497375d391668b75c4fefdddae3dde4d3e200c5
source_version: 0.15.0
translated_at: 2026-08-23
translator: ai-assisted
---

# 00 — Карта развёртывания

> **Прочитай это первым.** Карта для AI-агента: что читать, что копировать и в каком порядке.
> Когда поток понятен — следуй пронумерованным модулям последовательно.

---

## Что ты (агент) делаешь

Разворачиваешь **Raw-First Knowledge Pipeline** в проекте пользователя:

1. Проверяешь окружение (Node.js, Python, Git, индексатор)
2. Уточняешь у пользователя его роль и предпочтения
3. Копируешь и параметризуешь шаблоны из `templates/`
4. Копируешь reference-скрипты из `scripts/` и `shell/`
5. Запускаешь `kb_doctor.py` чтобы проверить развёртывание
6. Генерируешь role-specific `DATA_PLACEMENT_EXAMPLES.md` (Фаза 3)
7. Выдаёшь пользователю краткое summary «что куда класть»

**Важно:** ты НЕ пишешь Python/shell-скрипты с нуля. Они лежат в `scripts/` и `shell/` рядом с этим файлом. Копируй их. Адаптируй только конфиг (`kb.config.yml`).

---

## Порядок чтения модулей

| # | Модуль | Что ты делаешь |
|---|--------|----------------|
| 00 | Этот файл | Получаешь общую картину |
| 01 | `01_PREREQUISITES.md` | Проверяешь окружение, копируешь `templates/requirements.txt`, ставишь зависимости |
| 02 | `02_INIT.md` | Уточняешь роль, слепые зоны, четыре эскиза структуры (`kb_structure.py`), копируешь `kb.config.yml.template` и параметризуешь, создаёшь папки |
| 03 | `03_PIPELINE.md` | Копируешь `scripts/kb_ingest.py` + `scripts/kb_common.py` |
| 04 | `04_REVIEW.md` | Настраиваешь workflow ревью (без кода) |
| 05 | `05_INDEX.md` | Копируешь `templates/repomix.config.json.template`, `shell/reindex.sh` + `scripts/kb_reindex.py` |
| 06 | `06_AGENTS_TEMPLATE.md` | Копируешь и параметризуешь `templates/AGENTS.md.template` |
| 07 | `07_INTERACTION_LOOP.md` | Объясняешь команды; опционально `scripts/kb_save_session.py` |
| 08 | `08_PORTABLE.md` | Подключение базы к рабочим проектам |
| 09 | `09_LINT.md` | Копируешь `scripts/kb_lint.py`, `scripts/kb_mutate.py`, `shell/lint.sh` |
| 10 | `10_LOG.md` | Создаёшь пустой `log.md`, всё остальное делают скрипты |
| 11 | `11_PROVENANCE.md` | Конвенции frontmatter (без скриптов) |
| 12 | `12_NLP_PREPROCESS.md` | Ставишь spaCy-модель; NLP запускается из `kb_ingest.py` |
| 13 | `13_AUTORUN.md` | Копируешь `scripts/kb_watch.py`, `scripts/kb_reflect.py`, `scripts/kb_nlp_batch.py`, `shell/watcher.sh`; ставишь git hook |
| 14 | `14_INITIAL_POPULATION.md` | Копируешь `scripts/kb_structure.py`; генерируешь role-specific `DATA_PLACEMENT_EXAMPLES.md` из `examples/<role>.yml` (`kb_populate.py`) |
| 15 | `15_MEDIA_PROCESSING.md` | Копируешь `scripts/kb_stt.py`, `scripts/kb_ocr.py`, `templates/requirements-media.txt`; настраиваешь `media:` |
| 16 | `16_MERGE.md` | Копируешь `scripts/kb_export.py`, `scripts/kb_import.py`, `shell/export.sh`, `shell/import.sh`; настраиваешь `sync:` (нужно только если база работает на нескольких машинах) |
| 17 | `17_REFACTOR.md` | Ужатие инструкций (`!refactor`): двухшаговый разбор, решения владельца, eval; `--global` только отчёт |
| 18 | `18_HEAL.md` | Копируешь `scripts/kb_heal.py`; догоняющая починка после апгрейда (`!heal`) |

После всех модулей: запусти `bash shell/doctor.sh` (или `python3 scripts/kb_doctor.py`) для финальной проверки.

---

## Что создаётся при развёртывании

Агент собирает базу внутри `<project-root>/knowledge-base/`, оставляя исходный `setup/`. После проверки запускает `bash setup/shell/finalize.sh` — содержимое поднимается в корень проекта, оба каталога `setup/` и `knowledge-base/` удаляются.

Layout ДО finalize:

```
{user-project-root}/
├── setup/                            ← upstream-инструкции (источник)
│   ├── 00_OVERVIEW.md … 18_HEAL.md (включая 17_REFACTOR.md)
│   ├── README.md
│   ├── scripts/, shell/, templates/, examples/
│   └── shell/finalize.sh             ← запуск в конце
└── knowledge-base/                   ← агент собирает базу здесь
    ├── kb.config.yml                 ← параметризовано из templates/kb.config.yml.template
    ├── repomix.config.json           ← из templates/repomix.config.json.template
    ├── AGENTS.md                     ← параметризовано из templates/AGENTS.md.template
    ├── KNOWLEDGE_STRUCTURE.md, DATA_PLACEMENT_EXAMPLES.md, START_HERE.md
    ├── requirements.txt, .gitignore
    ├── scripts/                      ← Python reference-скрипты (дословная копия)
    ├── shell/                        ← POSIX-обёртки + macOS/Windows launcher-ы
    ├── templates/, examples/         ← для повторных прогонов (kb_populate, kb_upgrade)
    └── (структура папок через kb_ingest.py --init-dirs)
        raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/, eval/
```

Layout ПОСЛЕ finalize — плоско в корне проекта:

```
{user-project-root}/
├── kb.config.yml, AGENTS.md, KNOWLEDGE_STRUCTURE.md
├── DATA_PLACEMENT_EXAMPLES.md, START_HERE.md, repomix.config.json
├── reindex.command, watcher-start.command, watcher-stop.command   (macOS)
├── reindex.bat, watcher-start.bat                                  (Windows)
├── requirements.txt
├── shell/                            ← Linux/CLI: watcher.sh, reindex.sh, lint.sh, doctor.sh
├── scripts/                          ← Python pipeline
├── templates/, examples/
└── raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/, eval/
```

> Примечание: `finalize.sh` поднимает `*.command` и `*.bat` из `shell/` в корень. `*.sh` остаются только в `shell/`.

Скрипты в KB пользователя — **идентичны** скриптам в этом репо. При обновлении `kb_upgrade.py` сравнит версии и обновит их.

---

## Что ты (агент) НЕ должен делать

- Не придумывать свой Python-пайплайн. Копируй `scripts/kb_ingest.py`.
- Не придумывать свою lint-логику. Копируй `scripts/kb_lint.py`.
- Не писать свой watcher с кастомным debouncing. Копируй `scripts/kb_watch.py`.
- Не пропускай `kb_doctor.py` в конце развёртывания.

## Если имена файлов сомнительны

1. **Смотри, что реально лежит** в `setup/shell/` и `setup/scripts/`:
   ```bash
   ls setup/shell/
   ls setup/scripts/
   ```
2. Канонические имена (на момент этой версии):
   - Finalize: `setup/shell/finalize.sh`
   - Pipeline: `setup/scripts/kb_ingest.py`
   - Lint: `setup/scripts/kb_lint.py`
   - Doctor: `setup/scripts/kb_doctor.py`
   - Watcher: `setup/scripts/kb_watch.py` / `setup/shell/watcher.sh`
   - Reindex: `setup/scripts/kb_reindex.py`
   - Reflect / NLP batch: `kb_reflect.py`, `kb_nlp_batch.py`
   - STT / OCR: `kb_stt.py`, `kb_ocr.py`
   - Session save (опциональный CLI): `kb_save_session.py`
   - Common / populate / structure: `kb_common.py`, `kb_populate.py`, `kb_structure.py`
   - Mutate (самопроверка L1): `kb_mutate.py`
   - Heal: `kb_heal.py`
3. Если скрипта нет — **не выдумывай**; покажи `ls` пользователю.

---

## Краткая ментальная модель

```
Пользователь кидает файлы    ┌──── kb_ingest.py ────┐
в raw/*/unsorted/        ────►│  - hash & rename     │──► assets/<type>/<stable>.ext
                              │  - convert / STT/OCR │──► processed/markdown|transcripts|ocr/
                              │  - NLP enrich        │──► processed/nlp-meta/<stable>.yml
                              │  - estimate complexity│──► processed/extracted-metadata/<stable>.yml
                              │  - route             │──► review/needs-ai-decision/  (если сложный)
                              └──────────────────────┘
                                          │
                          На простых файлах ревью не нужно.
                          На сложных файлах агент ревьюит и пишет
                          curated knowledge в knowledge/.

knowledge/**.md  ────► repomix indexes ────► .repomix/output.xml ────► потребляет AI

kb_lint.py запускается над knowledge/ — отлавливает stale, broken links, и т.д.
kb_watch.py автоматизирует весь loop при изменениях файлов.
kb_reflect.py решает, когда просить агента о higher-level рефлексии.
```

---

## Версионирование

`VERSION` в родительском репо хранит `instructions_version` (например, `0.12.0`).
При развёртывании параметризуешь `kb.config.yml.template` текущей версией.
При будущем обновлении `kb_upgrade.py` сравнит версии и обновит скрипты.
