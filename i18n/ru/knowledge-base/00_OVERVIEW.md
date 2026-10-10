---
translation_of: knowledge-base/00_OVERVIEW.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 00 — Обзор развёртывания

> **Прочитайте первым.** Карта для AI-агента: что читать, что копировать, в каком порядке.
> Разобравшись с процессом, последовательно проходите пронумерованные модули.

---

## Что делаете вы (агент)

Развёртываете **Raw-First Knowledge Pipeline** в проекте пользователя. Пользователь скопировал этот набор в проект как `setup/`; вы строите базу в `<project-root>/knowledge-base/`, а в конце переносите её содержимое в корень проекта. Выполняйте все команды из **корня проекта**, если шаг не требует иного.

1. Проверьте окружение и создайте venv в корне проекта (`01`)
2. Спросите пользователя о роли и предпочтениях (`02`, фаза 0)
3. Скопируйте файлы движка **один раз** (`02`, фаза 1): `scripts/` (без `tests/`), `shell/`, `templates/`, `examples/`, а модули инструкций — в `kb-docs/`
4. Подставьте параметры в шаблоны (`kb.config.yml`, `AGENTS.md`, …) и создайте папки
5. Последовательно пройдите модули `03`–`18` и настройте всё необходимое для каждого (`02`, фаза 3 уточняет, какие сейчас читать целиком)
6. Проверьте через `kb_doctor.py` (проверка пройдена при коде выхода 0), затем выполните `setup/shell/finalize.sh` (`02`, «Завершение развёртывания»)
7. Подготовьте краткую памятку пользователю «что куда класть»

**Важно:** вы НЕ пишете Python/shell-скрипты с нуля. Они находятся в `setup/scripts/` и `setup/shell/`. Скопируйте их. Адаптируйте только конфигурацию (`kb.config.yml`) и параметризуемые шаблоны.

---

## Порядок чтения модулей

Файлы копируются в фазе 1 `02`; каждый модуль ниже объясняет, что настроить, а не что копировать.

| # | Модуль | Что настраивает |
|---|--------|-----------------|
| 00 | Этот файл | Общая картина |
| 01 | `01_PREREQUISITES.md` | Node.js, Python, Git, Repomix; venv в корне проекта; установка `requirements.txt` (+ необязательные файлы NLP/медиа) |
| 02 | `02_INIT.md` | Интервью о роли, слепые зоны, четыре эскиза структуры (`kb_structure.py`); копирование файлов движка и `kb-docs/`; параметризация `kb.config.yml` и других шаблонов; создание папок |
| 03 | `03_PIPELINE.md` | Контракт ingest (`kb_ingest.py`): `raw/` → `assets/`, `processed/`, `review/`; реестр извлечения |
| 04 | `04_REVIEW.md` | Процесс проверки по `!review` (без кода) |
| 05 | `05_INDEX.md` | Пакеты индекса (`repomix.config.json`, `kb_reindex.py`, `shell/reindex.sh`) и `STATUS.md` |
| 06 | `06_AGENTS_TEMPLATE.md` | `AGENTS.md` из `templates/AGENTS.md.template` |
| 07 | `07_INTERACTION_LOOP.md` | Команды, цикл обратной связи, необязательный `kb_save_session.py` |
| 08 | `08_PORTABLE.md` | Использование между проектами |
| 09 | `09_LINT.md` | Lint (`kb_lint.py`, `kb_mutate.py`, `shell/lint.sh`) |
| 10 | `10_LOG.md` | `log.md`; скрипты дописывают в него |
| 11 | `11_PROVENANCE.md` | Соглашения frontmatter (без скриптов) |
| 12 | `12_NLP_PREPROCESS.md` | Модель spaCy; NLP выполняется внутри `kb_ingest.py` |
| 13 | `13_AUTORUN.md` | Watcher (`kb_watch.py`, `shell/watcher.sh`), git hook (`shell/install-hooks.sh`), триггер рефлексии (`kb_reflect.py`) |
| 14 | `14_INITIAL_POPULATION.md` | `DATA_PLACEMENT_EXAMPLES.md` для роли (`kb_populate.py`) |
| 15 | `15_MEDIA_PROCESSING.md` | STT/OCR (`kb_stt.py`, `kb_ocr.py`, `requirements-media.txt`); конфигурация `media:` |
| 16 | `16_MERGE.md` | Экспорт/импорт между машинами (`kb_export.py`, `kb_import.py`, `shell/export.sh`, `shell/import.sh`); конфигурация `sync:` — только если база работает на нескольких машинах |
| 17 | `17_REFACTOR.md` | Сокращение инструкций (`!refactor`): двухшаговый аудит, решения владельца, eval; `--global` только формирует отчёт |
| 18 | `18_HEAL.md` | Догоняющее исправление после обновления (`!heal`, `kb_heal.py`) |

После модуля 18: `python3 knowledge-base/scripts/kb_doctor.py --root knowledge-base` (или `bash knowledge-base/shell/doctor.sh`) должен завершиться с кодом 0, затем следуйте `02_INIT.md` → «Завершение развёртывания».

---

## Что создаётся при развёртывании

Агент строит базу в `<project-root>/knowledge-base/`, сохраняя исходную папку `setup/`. После всех проверок агент выполняет `bash setup/shell/finalize.sh`, чтобы перенести результат в корень проекта, скопировать модули инструкций в `kb-docs/` и удалить `setup/` и `knowledge-base/`.

Расположение ДО finalize:

```
{user-project-root}/
├── .venv/                            ← создан в 01, остаётся здесь навсегда
├── setup/                            ← набор развёртывания (источник)
│   ├── 00_OVERVIEW.md … 18_HEAL.md, README.md
│   ├── scripts/, shell/, templates/, examples/
│   └── shell/finalize.sh             ← запуск в самом конце
└── knowledge-base/                   ← здесь агент строит базу
    ├── kb.config.yml                 ← параметры из templates/kb.config.yml.template
    ├── repomix.config.json           ← из templates/repomix.config.json.template
    ├── AGENTS.md                     ← параметры из templates/AGENTS.md.template
    ├── KNOWLEDGE_STRUCTURE.md, DATA_PLACEMENT_EXAMPLES.md, START_HERE.md
    ├── requirements*.txt, .gitignore, .gitattributes
    ├── kb-docs/                      ← модули инструкций (00 … 18, README.md), читаются во время работы
    ├── scripts/                      ← эталонные Python-скрипты (точная копия, без tests/)
    ├── shell/                        ← POSIX-обёртки, git hook, launchers macOS/Windows
    ├── templates/, examples/         ← для повторных запусков (kb_populate, kb_upgrade)
    └── (структура папок из kb_ingest.py --init-dirs)
        raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/, eval/, sync/
```

Расположение ПОСЛЕ finalize — плоско в корне проекта, launchers на верхнем уровне, обёртки `*.sh` в `shell/`:

```
{user-project-root}/
├── kb.config.yml, AGENTS.md, KNOWLEDGE_STRUCTURE.md
├── DATA_PLACEMENT_EXAMPLES.md, START_HERE.md, repomix.config.json
├── CLAUDE.md                         (только для Claude Code: одна строка, @AGENTS.md)
├── reindex.command, watcher-start.command, watcher-stop.command   (launchers macOS)
├── export.command, import.command                                  (macOS: синхронизация между базами)
├── reindex.bat, watcher-start.bat, export.bat, import.bat          (launchers Windows)
├── requirements*.txt, .gitignore, .gitattributes
├── kb-docs/                          ← 00_OVERVIEW.md … 18_HEAL.md, README.md
├── shell/                            ← watcher.sh, reindex.sh, lint.sh, doctor.sh, export.sh, import.sh,
│                                        install-hooks.sh, hooks/post-commit, _kbpy.sh
├── scripts/                          ← Python-конвейер
├── templates/, examples/
├── raw/, processed/, knowledge/, assets/, assets-index/, review/, interactions/, eval/, sync/
└── .venv/                            ← finalize его не трогает
```

> Примечание: `finalize.sh` поднимает launchers `*.command` и `*.bat` из `shell/` в корень проекта (для двойного клика в Finder/Explorer); `*.sh` остаются в `shell/`. Скрипт никогда не перемещает и не удаляет `.git` или virtualenv, добавляет правила `.gitignore` / `.gitattributes` базы в начало файлов проекта (правила проекта сохраняют приоритет), перемещает конфликтующие файлы корня в `.kb-finalize-backup/<timestamp>/` только с `--force` и записывает прерванный запуск в `.kb-finalize.journal` для `--resume`. Подробности: `02_INIT.md` → «Завершение развёртывания».

Скрипты в KB пользователя **идентичны** скриптам этого набора. Позже `scripts/kb_upgrade.py` из репозитория движка (см. его `docs/UPGRADING.md`) сравнивает версии и обновляет скрипты, shell-обёртки и `kb-docs/`.

---

## Что вы (агент) НЕ ДОЛЖНЫ делать

- Не изобретайте собственный Python-конвейер. Скопируйте `scripts/kb_ingest.py`.
- Не изобретайте собственную логику lint. Скопируйте `scripts/kb_lint.py`.
- Не пишите собственный watcher с особым debouncing. Скопируйте `scripts/kb_watch.py`.
- Не пишите git hooks вручную. Установите `shell/hooks/post-commit` через `shell/install-hooks.sh`.
- Не создавайте и не переносите venv внутрь `knowledge-base/` — он находится в корне проекта.
- Не пропускайте `kb_doctor.py` в конце развёртывания.

## Если сомневаетесь в именах файлов

Инструкции иногда отстают от реальности. Если шаг требует запустить скрипт, который вы не находите:

1. **Проверьте реальное содержимое** `setup/shell/` и `setup/scripts/` — выведите список:
   ```bash
   ls setup/shell/
   ls setup/scripts/
   ```
2. Актуальные канонические имена (на момент читаемой версии):
   - **Финализация** развёртывания (перенос `knowledge-base/` в корень проекта, заполнение `kb-docs/`, удаление `setup/`): `setup/shell/finalize.sh`
   - Git post-commit hook: `setup/shell/hooks/post-commit`, установка через `shell/install-hooks.sh`
   - Конвейер: `setup/scripts/kb_ingest.py`
   - Lint: `setup/scripts/kb_lint.py`
   - Doctor (smoke-test): `setup/scripts/kb_doctor.py`
   - Watcher: `setup/scripts/kb_watch.py` (Python) или `setup/shell/watcher.sh`/`watcher-start.command`/`watcher-start.bat`
   - Оркестратор переиндексации: `setup/scripts/kb_reindex.py`
   - Передача состояния между сессиями (`STATUS.md`): `setup/scripts/kb_status.py`
   - Триггер рефлексии: `setup/scripts/kb_reflect.py`
   - Пакетный NLP: `setup/scripts/kb_nlp_batch.py`
   - STT / OCR: `setup/scripts/kb_stt.py`, `setup/scripts/kb_ocr.py`
   - Сохранение сессии (необязательный CLI): `setup/scripts/kb_save_session.py`
   - Общие утилиты (и версия движка: `kb_common.py --version`): `setup/scripts/kb_common.py`
   - Populate (генератор DATA_PLACEMENT_EXAMPLES.md): `setup/scripts/kb_populate.py`
   - Эскизы структуры (четыре варианта + слепые зоны): `setup/scripts/kb_structure.py`
   - Mutate (самопроверка L1 lint): `setup/scripts/kb_mutate.py`
   - Heal: `setup/scripts/kb_heal.py`
3. Если ожидаемый скрипт отсутствует, **не изобретайте его** — покажите пользователю вывод `ls` и спросите. Старые документы или ваша память могут ссылаться на переименованные файлы (например, `install.sh` переименован в `finalize.sh`); всегда доверяйте файловой системе больше памяти.

---

## Краткая модель

```
Пользователь кладёт файлы  ┌──── kb_ingest.py ─────┐
в raw/*/unsorted/    ────►│  - хеш и новое имя    │──► assets/<type>/<stable>.ext
                          │  - конверсия / STT/OCR│──► processed/markdown|transcripts|ocr/
                          │  - NLP-обогащение     │──► processed/nlp-meta/<stable>.yml
                          │  - оценка сложности   │──► processed/extracted-metadata/<stable>.yml
                          │  - маршрутизация      │──► review/needs-*/  (сложное или чувствительное)
                          └───────────────────────┘
                                      │
                          Каждый конвертированный файл ждёт извлечения
                          (`extraction: pending`). По !review агент
                          разбирает очереди review/ и ожидающие
                          элементы processed/ и записывает проверенные
                          знания в knowledge/.

knowledge/**.md  ────► kb_reindex.py (Repomix) ────► .repomix/<pack>.xml ────► читает AI
                                          └────────► STATUS.md (ожидающая работа, читать в начале сессии)

kb_lint.py проверяет knowledge/ на устаревание, битые ссылки и т. п.
kb_watch.py автоматизирует цикл при изменениях файлов.
kb_reflect.py решает, когда попросить агента о рефлексии более высокого уровня.
```

---

## Версионирование

Файл `VERSION` в репозитории движка содержит версию движка. В наборе развёртывания нет `VERSION`; то же число выводит `python3 setup/scripts/kb_common.py --version`. При развёртывании подставьте этот вывод в `{{KB_INSTRUCTIONS_VERSION}}` шаблона `kb.config.yml.template` (`instructions_version`). При будущем обновлении `kb_upgrade.py` сравнит версии и обновит скрипты.
