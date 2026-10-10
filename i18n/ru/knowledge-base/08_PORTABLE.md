---
translation_of: knowledge-base/08_PORTABLE.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 08 — Переносимость: использование базы в других проектах

> Как подключить обученную базу знаний к рабочим проектам, чтобы AI-агент использовал накопленный опыт при написании кода.

---

## Проблема

База знаний живёт в отдельном проекте. Но работа идёт в **других проектах** — репозиториях кода, где AI-агент тоже должен знать автора: его стиль, решения, принципы и предпочтения.

## Рекомендуемая структура: соседний проект + ссылка

```text
~/www/main/
├── knowledge-base/          # ← The KB (separate project)
│   ├── AGENTS.md
│   ├── knowledge/
│   ├── interactions/
│   └── .repomix/            # index packs + PACKS_STATUS.md
│
├── highway-clicker/         # ← Working project
│   ├── AGENTS.md            # contains a pointer to the base
│   └── ...
│
└── another-project/         # ← Another project
    ├── AGENTS.md
    └── ...
```

### Почему соседний проект, а не вложенный?

- База знаний — **об авторе**, а не о конкретном проекте
- Одна база обслуживает много проектов
- Обновления базы не засоряют git-историю рабочих проектов
- Её можно отдельно резервировать и переносить

---

## Индекс — это набор паков

`kb_reindex.py` строит индекс из паков (см. `kb-docs/05_INDEX.md`):

- `.repomix/core.xml` — профиль, принципы, стиль, таблицы маршрутизации. Небольшой пак; его безопасно загружать первым.
- `.repomix/<section>.xml` — пак на каждый крупный раздел `knowledge/` (`domain.xml`, `insights.xml`, …); слишком большой раздел делится по подпапкам (`library-craft.xml`).
- `.repomix/aux.xml` — небольшие разделы, объединённые вместе; страницы непосредственно в `knowledge/` тоже попадают сюда, а когда их объём вырастает — в `knowledge-root.xml`.
- `.repomix/PACKS_STATUS.md` — все паки с размером, отметкой `⚠ OVER` при превышении потолка токенов и указанием, когда их загружать (для `aux.xml` — какие разделы он содержит). Ищите пак раздела здесь, не угадывайте имя файла.

Единого индекса всей базы для загрузки нет. База, развёрнутая до появления режима паков (без раздела `index:` в `kb.config.yml`), по-прежнему строит старый `.repomix/output.xml`; далее предполагается использование паков.

---

## Подключение к рабочему проекту

### Вариант 1: раздел в AGENTS.md проекта (рекомендуется)

Добавьте в `AGENTS.md` рабочего проекта:

```markdown
## Personal Knowledge Base

Next to this project sits the author's personal knowledge base.

- Path: `../knowledge-base/`
- Index: `../knowledge-base/.repomix/PACKS_STATUS.md` — lists the packs and when to load each
- Profile: `../knowledge-base/knowledge/profile/`
- Principles: `../knowledge-base/knowledge/principles/`

### When to use it

- Before architectural decisions — read `knowledge/principles/`
- For code/text voice — read `knowledge/voice/`
- For project context — read `knowledge/projects/`
- When discussing ideas — load `.repomix/core.xml` plus at most one pack whose "Load when" matches; never load a pack marked `⚠ OVER` whole

### Session capture

Write session summaries into the KB only on `!save` or when the author asks
(rules: `../knowledge-base/kb-docs/07_INTERACTION_LOOP.md`):
- Path: `../knowledge-base/interactions/sessions/`
- Folder format: `YYYY-MM-DD__<project-name>__<topic>/`, one timestamped file per save
- Reindex manually: `cd ../knowledge-base && ./shell/reindex.sh`
```

### Вариант 2: симлинк на папку индекса

```bash
# In the working project
ln -s ../knowledge-base/.repomix .kb-index
```

Добавьте в `AGENTS.md`:
```markdown
## Personal Context
Before strategic decisions read `.kb-index/PACKS_STATUS.md`, then `.kb-index/core.xml`
and at most one matching pack.
```

### Вариант 3: копирование паков (для изолированных сред)

Если проект находится на другой машине:

```bash
mkdir -p ./docs/kb-context
cp ../knowledge-base/.repomix/PACKS_STATUS.md ../knowledge-base/.repomix/core.xml ./docs/kb-context/
cp ../knowledge-base/.repomix/domain.xml ./docs/kb-context/    # only the packs this project needs
```

Обновляйте вручную по мере необходимости. Подходит для CI/CD и удалённых сред. Паки содержат личные знания автора: не включайте копию в общий репозиторий (добавьте `docs/kb-context/` в его `.gitignore`).

---

## Сохранение сессий из рабочего проекта

Когда владелец говорит `!save` (или просит записать выводы), пока агент работает в `highway-clicker`:

1. Агент записывает резюме сессии в `../knowledge-base/interactions/sessions/`
2. Использует формат папки `YYYY-MM-DD__highway-clicker__<topic>/`, внутри — файлы с временными метками (структура: `kb-docs/07_INTERACTION_LOOP.md`)
3. Добавляет тег проекта во frontmatter:

```markdown
---
session_date: 2026-05-06
project: "highway-clicker"
topic: "WebSocket auth refactor"
quality: high
redaction_required: true   # as in kb-docs/07_INTERACTION_LOOP.md
meta_reviewed: false
---

# Session: WebSocket auth refactor

## Key takeaways
- Decided to use SIWE for MetaMask instead of a custom signature
- ...
```

4. Переиндексирует базу **вручную**: `cd ../knowledge-base && ./shell/reindex.sh`
   - Не автоматически, чтобы не замедлять рабочий проект

---

## Продолжение обучения из рабочих проектов

База продолжает учиться, даже когда вы работаете вне неё:

```text
Работа в highway-clicker
        ↓
!save → AI пишет резюме сессии → ../knowledge-base/interactions/sessions/
        ↓
Когда удобно: cd ../knowledge-base && ./shell/reindex.sh
        ↓
STATUS.md: "sessions awaiting meta-review" → !meta-review → обновления knowledge/
        ↓
Следующая сессия в highway-clicker — AI знает больше
```

### Что поступает в базу из рабочих проектов

- Архитектурные решения и их обоснования
- Выявленные предпочтения по стилю кода
- Приёмы отладки, которые сработали
- Инструменты и подходы, которые понравились или не понравились
- Выводы, полезные для нескольких проектов

### Что НЕ поступает

- Код проекта (уже есть в git)
- Секреты и конфигурации проекта
- Детали одного проекта без повторно используемой ценности

---

## Перенос базы на другую машину

```bash
# Pack (without the venv, binary assets and machine-local state)
tar czf knowledge-base-portable.tar.gz \
  --exclude='.venv' \
  --exclude='assets/' \
  --exclude='.repomix/' \
  --exclude='.kb-state/' \
  --exclude='.kb-backups/' \
  --exclude='STATUS.md' \
  knowledge-base/

# On the new machine
tar xzf knowledge-base-portable.tar.gz
cd knowledge-base
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# optional, if the old machine had them: requirements-nlp.txt, requirements-media.txt
./shell/reindex.sh
```

`.repomix/`, кеши `.kb-state/` и `STATUS.md` восстанавливаются при первой переиндексации. Резервные копии — `.kb-backups/` (heal), `.kb-state/upgrade-backups/` и `.kb-state/refactor-backups/` — локальны для машины и остаются на ней. Если нужны ресурсы — добавьте `assets/` в архив (он станет больше).

Чтобы синхронизировать две рабочие копии одной базы (ноутбук + десктоп), используйте `!export` / `!import`, а не перенос архивов туда и обратно (см. `kb-docs/16_MERGE.md`).

---

## Несколько проектов — организация работы

| Вопрос | Ответ |
|--------|-------|
| Где живёт база? | В одном экземпляре рядом с проектами (`../knowledge-base/`) |
| Куда AI пишет резюме сессий? | Всегда в `../knowledge-base/interactions/sessions/`, по `!save` |
| Как различаются проекты? | По имени папки сессии: `2026-05-06__highway-clicker__topic/` |
| Когда переиндексировать? | Автоматически (см. `kb-docs/13_AUTORUN.md`) или через `./shell/reindex.sh` |
| Нужен `AGENTS.md` в каждом проекте? | Да, с разделом "Personal Knowledge Base" |
| Разные базы для разных ролей? | Возможно, но обычно одна база на человека |

---

## Динамическое обогащение контекста

AI-агент загружает знания **по мере необходимости** через ссылки — только то, что нужно.

### Проблема

Загрузка всех паков расходует контекст. Большая часть знаний не относится к конкретной задаче.

### Решение: загрузка по мере необходимости через маршрутизацию

```text
routing-table.md (20 строк)
        ↓ AI выбирает тему
routing/domain.md (15 строк, генерируется для каждого раздела)
        ↓ AI находит нужные страницы
domain/docker-swarm.md + domain/caching.md
        ↓ AI следует по [[wikilinks]], если нужен дополнительный контекст
decisions/2026-03__swarm-deployment.md
```

**~4 файла вместо целых паков.**

### В AGENTS.md рабочего проекта

```markdown
## Dynamic Context Loading

When working with the KB:
1. First read `../knowledge-base/knowledge/routing-table.md`
2. Pick 1-2 relevant routing pages by topic
3. Read only the needed `knowledge/` pages
4. If more context is needed — follow `[[wikilinks]]`
5. Load a pack from `../knowledge-base/.repomix/` only when 3-5 pages will not do (`PACKS_STATUS.md` says which)

This conserves context and keeps work fast on large bases.
```

### Обогащение контекста в ходе ответа

Во время ответа AI может **динамически** подтягивать знания:

1. Заметил `[[wikilink]]` на загруженной странице
2. Решил, что связанная страница улучшит ответ
3. Подтянул её и учёл в рассуждении
4. Если обнаружился пробел — предложил страницу `query-writeback` (записывается после согласия владельца)

Это превращает базу из **статичного справочника** в **живую систему**, которая:
- Обновляется при ingest (автоматически — см. `kb-docs/13_AUTORUN.md`)
- Обогащается через query-writeback (см. `kb-docs/07_INTERACTION_LOOP.md`)
- Загружается по запросу через маршрутизацию и wikilinks
- Проверяется lint (см. `kb-docs/09_LINT.md`)
