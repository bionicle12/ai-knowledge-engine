---
translation_of: knowledge-base/14_INITIAL_POPULATION.md
source_commit: 41b95e18eccb87d255fee3f7c367d1c2e6847849
source_version: 0.9.3
translated_at: 2026-06-29
translator: ai-assisted
---

# 14 — Initial Population Helper

> После завершения `02_INIT` агент **обязан** сгенерировать персонализированный `DATA_PLACEMENT_EXAMPLES.md` для выбранной роли. Это устраняет «эффект пустых папок»: пользователь смотрит на `raw/work/unsorted/` и не понимает, что туда класть.
>
> **Reference template:** `knowledge-base/templates/DATA_PLACEMENT_EXAMPLES.md.template` — стартовый скелет.
> **Источник примеров:** секция `placement_examples:` внутри `examples/<role>.yml`.

---

## Идея

Каждый `examples/*.yml` теперь содержит секцию `placement_examples:` с конкретными примерами «что → куда» для типичных артефактов этой роли. Агент:

1. Читает выбранный шаблон роли (`examples/<role>.yml`)
2. Берёт `placement_examples:` и связывает с entities из конфига
3. Генерирует персонализированный `DATA_PLACEMENT_EXAMPLES.md` (заменяет стартовый скелет из templates)
4. Опционально создаёт `raw/_samples/` с placeholder-md файлами, демонстрирующими naming convention и frontmatter

После генерации агент **показывает пользователю короткое summary** в чате: «Вот 5 примеров того, что можно положить в базу прямо сейчас».

---

## Когда запускается

| Триггер | Что делает |
|---------|-----------|
| Конец `02_INIT` (deployment) | Генерирует первичный `DATA_PLACEMENT_EXAMPLES.md` |
| Команда пользователя `!populate` | Перегенерирует с актуальным состоянием entities |
| Изменение `kb.config.yml` (новые entities) | Опционально регенерация при следующей сессии |

---

## Структура `placement_examples:` в role-template

```yaml
# examples/<role>.yml

placement_examples:
  intro: |
    Свободное вступление от лица роли. 1-2 параграфа: «Если ты <роль>,
    то скорее всего у тебя есть...»

  by_artifact:
    # Ключ — тип артефакта; значение — куда класть и какие примеры
    - artifact: "ADR (Architecture Decision Record)"
      destination: "raw/reference/unsorted/"
      examples:
        - "ADR-0042: переход с REST на GraphQL.md"
        - "Решение: использовать Docker Swarm вместо K8s.txt"
      knowledge_target: "knowledge/decisions/"
      tip: "После обработки ADR попадает в knowledge/decisions/ — иммутабельный лог решений."

    - artifact: "Записи технических митингов"
      destination: "raw/media/unsorted/"
      examples:
        - "2026-05-15-design-review.mp3"
        - "Sync с тимлидом 14:00.mp4"
      tip: "Аудио будет автотранскрибировано (если установлены ffmpeg + STT)."

    - artifact: "Постмортемы и расследования"
      destination: "raw/work/unsorted/"
      examples:
        - "2026-05-15-postmortem-redis-spike.md"
        - "N+1 в users API — расследование.txt"
      knowledge_target: "knowledge/playbooks/debugging.md"

  quickstart:
    # 3-5 файлов для немедленного наполнения, чтобы пользователь
    # получил пользу за 5 минут.
    - "Любой README.md из текущего рабочего проекта → raw/reference/unsorted/"
    - "Заметка про принятое арх. решение (даже одна строка) → raw/reference/unsorted/"
    - "Скриншот архитектурной диаграммы → raw/media/unsorted/"

  do_not_drop:
    # Что точно НЕ нужно класть в базу
    - "Чужой код без явной лицензии"
    - "API-ключи и секреты (даже зачёркнутые)"
    - "Приватные переписки команды без согласия"
```

---

## Как агент использует placement_examples

1. После `02_INIT.md` агент читает `examples/<role>.yml`, ищет ключ `placement_examples`. Если ключа нет — использует `templates/DATA_PLACEMENT_EXAMPLES.md.template` без расширений.
2. Если ключ есть — формирует `DATA_PLACEMENT_EXAMPLES.md` со следующими секциями:
   - заголовок и `intro` из шаблона
   - таблица «You have → Put it in» (общие правила, всегда есть)
   - **Role-specific examples** — раскрывает каждый пункт `by_artifact` в подсекцию с примерами файлов и ссылками на knowledge target
   - **Quickstart (5 минут)** — список из `quickstart`
   - **Don't drop** — список из `do_not_drop`
3. Файл записывается в корень развёрнутой базы как `DATA_PLACEMENT_EXAMPLES.md` (перезаписывая шаблонный).
4. Агент пишет короткое summary в чат пользователя:
   ```
   ✅ База развёрнута. Вот первые шаги для наполнения:

   1. Положи README любого своего проекта в raw/reference/unsorted/
   2. Если есть PDF/DOCX со стратегией — в raw/documents/unsorted/
   3. Запусти ./shell/reindex.sh

   Подробности — в DATA_PLACEMENT_EXAMPLES.md
   ```

---

## Опциональный шаг: `raw/_samples/`

Если пользователь явно подтверждает «хочу примеры», агент создаёт `raw/_samples/` с шаблонными `.example.md` файлами:

```markdown
<!-- raw/_samples/decision-record.example.md -->
---
# Этот файл — ПРИМЕР формата. Не индексируется.
# Скопируй в raw/reference/unsorted/, переименуй, заполни — и pipeline его подхватит.
---

# ADR: <название решения>

## Дата
2026-MM-DD

## Контекст
Что побудило принять это решение?

## Решение
Что мы решили сделать?

## Альтернативы
Что рассмотрели и отвергли?

## Последствия
Какие последствия (плюсы и минусы)?
```

Папка `raw/_samples/` исключается из ingest по соглашению (имя начинается с `_`). Пользователь может удалить её в любой момент.

> **Примечание:** Текущий `kb_ingest.py` сканирует `raw/**/unsorted/`, поэтому файлы из `raw/_samples/` **не** попадают в pipeline по умолчанию. Это безопасно.

---

## Контракт для shell/python (опционально)

Эту операцию можно автоматизировать через `scripts/kb_populate.py` (не реализуется в Фазе 3 — пока всё делает агент в режиме чата). Если потребуется — добавить в Фазу 4:

```python
# scripts/kb_populate.py (Phase 4)
"""kb_populate — generate DATA_PLACEMENT_EXAMPLES.md from a role template.

Usage:
    python3 scripts/kb_populate.py --role programmer-senior
    python3 scripts/kb_populate.py --role custom --from path/to/role.yml
    python3 scripts/kb_populate.py --create-samples  # also create raw/_samples/
"""
```

Пока генерацию делает агент по этой инструкции.

---

## Чек-лист для агента

При завершении развёртывания:

- [ ] Прочитан `examples/<role>.yml`, найден `placement_examples:`
- [ ] Сгенерирован `DATA_PLACEMENT_EXAMPLES.md` с role-specific секциями
- [ ] Файл записан в корень развёрнутой базы (поверх template-скелета)
- [ ] Пользователю показано краткое summary с 3-5 quickstart-пунктами
- [ ] (Опционально) Создана папка `raw/_samples/` с примерами форматов

---

## Интеграция

- **02_INIT:** в финале фазы 1 («Создание структуры») агент переходит к этому модулю
- **03_PIPELINE:** `raw/_samples/` не попадает в pipeline (имя начинается с `_`)
- **05_INDEX:** `raw/_samples/` исключён ignore-паттерном `raw/**`
- **10_LOG:** generation записывается в `log.md` как `populate | DATA_PLACEMENT_EXAMPLES generated`

---

## Будущие улучшения (Фаза 4+)

- Версионирование сгенерированного файла (`generated_at`, `from_template_version`)
- Автоматический re-generation при изменении entities в kb.config.yml
- Перевод секций под основной язык базы (использование `language` из конфига)
- A/B тесты разных формулировок quickstart на основе фидбэка пользователей
