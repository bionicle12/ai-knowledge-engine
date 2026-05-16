---
translation_of: knowledge-base/08_PORTABLE.md
source_commit: 63ec5652913793e80cf7a899c691d34d88285f8a
source_version: 0.9.3
translated_at: 2026-05-17
translator: human
---

# 08 — Портабельность: использование базы в других проектах

> Как подключить обученную базу знаний к рабочим проектам, чтобы AI-агент использовал накопленную экспертизу при работе с кодом.

---

## Проблема

База знаний живёт в отдельном проекте. Но работа происходит в **других проектах** — репозиториях с кодом, где AI-агент тоже должен знать автора: стиль, решения, принципы, предпочтения.

## Рекомендуемая схема: соседний проект + ссылка

```text
~/www/main/
├── knowledge-base/          # ← База знаний (отдельный проект)
│   ├── AGENTS.md
│   ├── knowledge/
│   ├── interactions/
│   └── .repomix/output.xml
│
├── highway-clicker/         # ← Рабочий проект
│   ├── AGENTS.md            # содержит ссылку на базу
│   └── ...
│
└── another-project/         # ← Ещё один проект
    ├── AGENTS.md
    └── ...
```

### Почему соседний проект, а не внутри?

- База знаний — **про автора**, а не про конкретный проект
- Одна база обслуживает множество проектов
- Обновления базы не засоряют git-историю рабочих проектов
- Можно бэкапить/переносить отдельно

---

## Подключение к рабочему проекту

### Вариант 1: Секция в AGENTS.md проекта (рекомендуется)

Добавить в `AGENTS.md` рабочего проекта:

```markdown
## Personal Knowledge Base

Рядом с этим проектом находится персональная база знаний автора.

- Путь: `../knowledge-base/`
- Индекс: `../knowledge-base/.repomix/output.xml`
- Профиль: `../knowledge-base/knowledge/profile/`
- Принципы: `../knowledge-base/knowledge/principles/`

### Когда использовать

- Перед архитектурными решениями — прочитай `knowledge/principles/`
- Для стиля кода/текста — прочитай `knowledge/voice/`
- Для контекста проекта — прочитай `knowledge/projects/`
- При обсуждении идей — используй полный индекс `.repomix/output.xml`

### Session capture

При работе в этом проекте — записывай session summaries в базу знаний:
- Путь: `../knowledge-base/interactions/sessions/`
- Формат папки: `YYYY-MM-DD__<project-name>__<topic>/`
- Автоматический capture работает по тем же правилам (см. 07_INTERACTION_LOOP.md)
- Реиндекс вручную: `cd ../knowledge-base && ./reindex.sh`
```

### Вариант 2: Симлинк на индекс

```bash
# В рабочем проекте
ln -s ../knowledge-base/.repomix/output.xml .kb-context.xml
```

Добавить в `AGENTS.md`:
```markdown
## Personal Context
Прочитай `.kb-context.xml` для контекста автора перед стратегическими решениями.
```

### Вариант 3: Копия индекса (для изолированных окружений)

Если проект не на той же машине:

```bash
cp ../knowledge-base/.repomix/output.xml ./docs/kb-context.xml
```

Обновлять вручную при необходимости. Подходит для CI/CD или удалённых окружений.

---

## Session capture из рабочего проекта

Когда AI-агент работает в `highway-clicker` и хочет записать выводы:

1. Пишет session summary в `../knowledge-base/interactions/sessions/`
2. Использует формат: `YYYY-MM-DD__highway-clicker__<topic>/`
3. Добавляет тег проекта в frontmatter:

```markdown
---
session_date: 2026-05-06
project: "highway-clicker"
topic: "Рефакторинг WebSocket auth"
quality: high
---

# Session: Рефакторинг WebSocket auth

## Ключевые выводы
- Решили использовать SIWE для MetaMask вместо кастомной подписи
- ...
```

4. Реиндекс базы — **вручную**: `cd ../knowledge-base && ./reindex.sh`
   - Не автоматически, чтобы не замедлять работу в рабочем проекте

---

## Дообучение при работе в проекте

База продолжает учиться, даже когда ты работаешь не в ней:

```text
Работа в highway-clicker
        ↓
AI пишет session summary → ../knowledge-base/interactions/sessions/
        ↓
Когда удобно: cd ../knowledge-base && ./reindex.sh
        ↓
Meta-review → knowledge/ обновляется
        ↓
Следующий сеанс в highway-clicker — AI уже умнее
```

### Что попадает в базу из рабочих проектов

- Архитектурные решения и их обоснования
- Выявленные предпочтения стиля кода
- Паттерны дебага, которые сработали
- Инструменты и подходы, которые понравились/не понравились
- Межпроектные инсайты

### Что НЕ попадает

- Код проекта (он уже в git)
- Секреты и конфиги проекта
- Детали, специфичные только для одного проекта без переиспользуемой ценности

---

## Перенос базы на другую машину

```bash
# Упаковать (без .venv и бинарных ассетов)
tar czf knowledge-base-portable.tar.gz \
  --exclude='.venv' \
  --exclude='assets/' \
  --exclude='.repomix/' \
  knowledge-base/

# На новой машине
tar xzf knowledge-base-portable.tar.gz
cd knowledge-base
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./reindex.sh
```

Если нужны ассеты — добавить `assets/` в архив (увеличит размер).

---

## Множественные проекты — как не запутаться

| Вопрос | Ответ |
|--------|-------|
| Где живёт база? | Один раз, рядом с проектами (`../knowledge-base/`) |
| Где AI пишет session summary? | Всегда в `../knowledge-base/interactions/sessions/` |
| Как различать проекты? | По имени папки сессии: `2026-05-06__highway-clicker__topic/` |
| Когда реиндексить? | Автоматически (см. `13_AUTORUN.md`) или `./reindex.sh` |
| Нужен ли AGENTS.md в каждом проекте? | Да, с секцией «Personal Knowledge Base» |
| Можно ли разные базы для разных ролей? | Да, но обычно одна база на человека |

---

## Dynamic Context Enrichment

AI-агент подгружает знания **не целиком**, а по ссылкам — по мере необходимости.

### Проблема

Загрузка всего `.repomix/output.xml` (~100KB+) расходует контекст. Большинство знаний для конкретной задачи не нужны.

### Решение: ленивая загрузка через routing

```text
routing-table.md (20 строк)
        ↓ AI определяет тему
routing/rt-infrastructure.md (15 строк)
        ↓ AI находит нужные страницы
domain/docker-swarm.md + domain/caching.md
        ↓ AI следует [[wikilinks]] если нужен контекст
decisions/2026-03__swarm-deployment.md
```

**Итого: ~4 файла вместо всего индекса.**

### В AGENTS.md рабочего проекта

```markdown
## Dynamic Context Loading

При работе с базой знаний:
1. Сначала прочитай `../knowledge-base/knowledge/routing-table.md`
2. Определи 1-2 релевантных routing pages по теме задачи
3. Прочитай только нужные knowledge/ страницы
4. Если нужен дополнительный контекст — следуй [[wikilinks]]
5. НЕ читай весь .repomix/output.xml если можно обойтись 3-5 страницами

Это экономит контекст и позволяет работать с большими базами.
```

### Live-обогащение контекста

Во время работы AI может **динамически** подгружать знания:

1. В процессе ответа обнаружил `[[wikilink]]` в загруженной странице
2. Понял, что связанная страница даст более точный ответ
3. Подгрузил её и интегрировал в рассуждение
4. Если обнаружил пробел — создал `query-writeback` страницу

Это превращает базу из **статического справочника** в **живую систему**, которая:
- Обновляется при ingest (автоматически через `13_AUTORUN.md`)
- Обогащается при query-writeback (см. `07_INTERACTION_LOOP.md`)
- Подгружается по запросу через routing + wikilinks
- Проверяется lint'ом (см. `09_LINT.md`)

