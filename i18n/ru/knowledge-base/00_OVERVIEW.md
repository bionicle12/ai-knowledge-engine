---
translation_of: knowledge-base/00_OVERVIEW.md
source_commit: 069af84d1cdad91b3ff8b3d5290c6f5391ac9b7f
source_version: 0.9.0
translated_at: 2026-05-17
translator: human
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
| 02 | `02_INIT.md` | Уточняешь роль, копируешь `kb.config.yml.template` и параметризуешь, создаёшь папки |
| 03 | `03_PIPELINE.md` | Копируешь `scripts/kb_ingest.py` + `scripts/kb_common.py` |
| 04 | `04_REVIEW.md` | Настраиваешь workflow ревью (без кода) |
| 05 | `05_INDEX.md` | Копируешь `templates/repomix.config.json.template`, копируешь `shell/reindex.sh` |
| 06 | `06_AGENTS_TEMPLATE.md` | Копируешь и параметризуешь `templates/AGENTS.md.template` |
| 07 | `07_INTERACTION_LOOP.md` | Объясняешь команды, скрипты копировать не нужно |
| 08 | `08_PORTABLE.md` | Подключение базы к рабочим проектам |
| 09 | `09_LINT.md` | Копируешь `scripts/kb_lint.py`, `shell/lint.sh` |
| 10 | `10_LOG.md` | Создаёшь пустой `log.md`, всё остальное делают скрипты |
| 11 | `11_PROVENANCE.md` | Конвенции frontmatter (без скриптов) |
| 12 | `12_NLP_PREPROCESS.md` | Ставишь spaCy-модель; NLP запускается из `kb_ingest.py` |
| 13 | `13_AUTORUN.md` | Копируешь `scripts/kb_watch.py`, `scripts/kb_reflect.py`, `scripts/kb_nlp_batch.py`, `shell/watcher.sh`; ставишь git hook |
| 14 | `14_INITIAL_POPULATION.md` | Генерируешь role-specific `DATA_PLACEMENT_EXAMPLES.md` из `examples/<role>.yml` |

После всех модулей: запусти `bash shell/doctor.sh` (или `python3 scripts/kb_doctor.py`) для финальной проверки.

---

## Что копируется в KB пользователя

```
{user-kb-root}/
├── kb.config.yml                      ← параметризовано из templates/kb.config.yml.template
├── repomix.config.json                ← из templates/repomix.config.json.template
├── AGENTS.md                          ← параметризовано из templates/AGENTS.md.template
├── KNOWLEDGE_STRUCTURE.md             ← из templates/KNOWLEDGE_STRUCTURE.md.template
├── DATA_PLACEMENT_EXAMPLES.md         ← начальный скелет; Фаза 3 расширяет его
├── requirements.txt                   ← из templates/requirements.txt
├── .gitignore                         ← из templates/.gitignore.template
│
├── scripts/                           ← дословная копия из knowledge-base/scripts/
│   ├── kb_common.py
│   ├── kb_ingest.py
│   ├── kb_lint.py
│   ├── kb_watch.py
│   ├── kb_reflect.py
│   ├── kb_nlp_batch.py
│   └── kb_doctor.py
│
├── reindex.sh                         ← из shell/reindex.sh
├── watcher.sh                         ← из shell/watcher.sh
├── lint.sh                            ← из shell/lint.sh
├── doctor.sh                          ← из shell/doctor.sh
│
└── (структура папок создаётся через kb_ingest.py --init-dirs)
```

Скрипты в KB пользователя — **идентичны** скриптам в этом репо. При обновлении `kb_upgrade.py` сравнит версии и обновит их.

---

## Что ты (агент) НЕ должен делать

- Не придумывать свой Python-пайплайн. Копируй `scripts/kb_ingest.py`.
- Не придумывать свою lint-логику. Копируй `scripts/kb_lint.py`.
- Не писать свой watcher с кастомным debouncing. Копируй `scripts/kb_watch.py`.
- Не пропускай `kb_doctor.py` в конце развёртывания.

---

## Краткая ментальная модель

```
Пользователь кидает файлы    ┌──── kb_ingest.py ────┐
в raw/*/unsorted/        ────►│  - hash & rename     │──► assets/<type>/<stable>.ext
                              │  - convert to MD     │──► processed/markdown/<stable>.md
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

`VERSION` в родительском репо хранит `instructions_version` (например, `0.7.0`).
При развёртывании параметризуешь `kb.config.yml.template` текущей версией.
При будущем обновлении `kb_upgrade.py` сравнит версии и обновит скрипты.
