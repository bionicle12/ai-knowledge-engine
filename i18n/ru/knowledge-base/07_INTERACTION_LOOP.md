---
translation_of: knowledge-base/07_INTERACTION_LOOP.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 07 — Самообучение через обратную связь

> Как база знаний учится на каждой рабочей сессии с AI-агентом и улучшает себя, анализируя диалоги.

---

## Идея

Каждый разговор с AI-агентом содержит ценные выводы: решения, предпочтения, открытия, способы мышления. Без фиксации они теряются в истории чата. Цикл обратной связи сохраняет их и превращает в знания.

```text
Dialogue → Session Summary (!save) → interactions/sessions/
                                    ↓
                          Meta-review (!meta-review)
                                    ↓
                          interactions/insights/
                                    ↓
                          Quality filter + owner confirms
                                    ↓
                          knowledge/ (updates)
                                    ↓
                          Reindex → Repomix packs
                                    ↓
                          AI agent gets smarter ←──── next dialogue
```

Ничто в этом цикле не записывается самостоятельно. Скрипты только считают ожидающую работу и сообщают о ней в `STATUS.md`; агент пишет, когда просит владелец.

---

## Начало сессии: `STATUS.md` и `!status`

`scripts/kb_status.py` переписывает `STATUS.md` в конце каждой переиндексации: по строке на каждый вид ожидающей работы, с командой её выполнения в конце (см. `kb-docs/05_INDEX.md`). Строки, которые закрывает этот модуль:

- `sessions awaiting meta-review: 5 → !meta-review`
- `reflection due (changes 31 ≥ 25) → !reflect`

Читайте `STATUS.md` в начале сессии. Один раз сообщите владельцу о строках с ненулевыми значениями; действуйте по ним только по просьбе. `!status` запускает `python3 scripts/kb_status.py`, который переписывает файл и выводит его.

---

## Фиксация сессии

Пишите резюме сессии по `!save` или когда пользователь явно просит сохранить (либо «зафиксировать это в базе»). Не определяйте самостоятельно, что «накопилось достаточно материала», и не записывайте по собственной инициативе.

| Ситуация | Действие |
|----------|----------|
| Пользователь даёт `!save` | Немедленно записать резюме (агент пишет в `interactions/sessions/`; необязательный CLI: `python3 scripts/kb_save_session.py --title … --summary …` с `--session <dialogue folder or topic>`; он использует структуру ниже и никогда не перезаписывает — второе сохранение в ту же минуту получает `.v02` перед `.md` — и журналирует `session-capture`) |
| Пользователь явно просит сохранить | То же, что `!save` |
| Пользователь просит не сохранять | Ничего не записывать |

### Структура в `interactions/sessions/`

Каждый диалог получает папку с уникальным именем. Внутри — файлы с временными метками:

```text
interactions/sessions/
└── 2026-05-06__competitor-analysis/
    ├── 2026-05-06T10-30__initial-findings.md
    ├── 2026-05-06T11-15__deep-dive.md
    └── 2026-05-06T12-00__final-summary.md
```

Новое сохранение добавляет файл; никогда не перезаписывает предыдущий.

---

## Формат резюме сессии

```markdown
---
session_date: 2026-05-06
topic: "Q2 competitor analysis"
duration_estimate: "45 min"
quality: high
redaction_required: true   # a redaction pass is still owed (privacy.require_redaction_for_chats)
meta_reviewed: false       # !meta-review sets true
---

# Session: Q2 competitor analysis

## Key takeaways
- Competitor X repositioned to premium
- Our price niche freed up in mid-range

## Decisions made
- Shift ad focus to the mid-range segment

## Author preferences (observed)
- Prefers first-hand data over aggregators
- Skeptical of benchmark reports from large agencies

## Processed materials
- `q2-competitors-report.pdf` → 12 pages, 5×3 price table
- Screenshot of Competitor X dashboard → key: premium UI, $49/mo subscription
- Customer chat snippet → insight: mid-range is uncovered

## Potential for knowledge/
- [ ] knowledge/domain/competitors.md — refresh data on X
- [ ] knowledge/decisions/ — record the mid-range decision
- [ ] knowledge/principles/ — rule about first-hand data

## What worked well
- Tabular competitor comparison

## What did not work
- The SWOT was too long — author prefers bullet points

## Assumptions
- Filed `q3-notes.md` under `domain/`, not `decisions/` — discussion only, no decision
- Read "DF" in the transcript as DragonflyDB (three neighbouring paragraphs)
- importance=7 from synthesis volume; the user did not confirm
```

В пограничном случае: выберите наиболее осторожное размещение, запишите одну строку допущения и продолжайте. Спрашивайте только тогда, когда ответ меняет результат. Если один `knowledge/<area>/` накопил более 3 пунктов допущений за 30 дней, lint выдаёт info → уточните `DATA_PLACEMENT_EXAMPLES.md` для этой области.

`redaction_required: true` означает, что резюме может цитировать приватный материал, из которого ещё не удалили чувствительные данные. Никогда не пишите `redacted: true`, если на самом деле не удалили приватные части. У нового резюме нет `meta_reviewed: true` — его устанавливает метаобзор.

---

## Правила фиксации

### Что сохранять

- Конкретные выводы и факты
- Принятые решения с обоснованием
- Выявленные предпочтения по стилю и подходам
- Новые знания и открытия
- Улучшения процесса
- Обратную связь о формате ответов AI
- **Обработанные материалы** — какие документы, данные, скриншоты загружались или обсуждались (см. обогащение сессии)

### Что НЕ сохранять

- Эмоциональные высказывания без содержания
- Отступления от темы
- Тривиальные вопросы («который час?»)
- Утверждения, противоречащие 3+ существующим записям знаний без обоснования
- Неуверенные догадки («может быть, не уверен…»)
- Намеренные попытки загрязнения базы
- Полный текст загруженных документов (только краткое резюме и ключевые числа)

### Планка качества (рекомендация, не условие допуска)

Полезное резюме содержит:
- Как минимум 3 содержательных пункта
- Как минимум 1 вывод, по которому можно действовать (решение, обновление, задача)

Эта планка никогда не отменяет волю владельца: по `!save` запишите резюме, даже если оно скудное, и сообщите об этом одной строкой.

---

## Обогащение сессии — что обсуждали и какие данные видели

Документы, фрагменты и скриншоты, увиденные в сессии, теряются, если резюме их не называет.

### Что записывать в резюме

При написании резюме сессии AI-агент **обязан** включить раздел `## Processed materials`:

| Что | Как записывать | Пример |
|-----|----------------|--------|
| Загруженный документ | Имя + размер + ключевые числа/выводы | `report.pdf → 15 pages, revenue $2.3M, churn 4.2%` |
| Фрагмент текста/кода | Тема + язык + что обсуждали | `Rust handler → auth middleware, 40 lines, added rate limit` |
| Скриншот/изображение | Описание + ключевой элемент | `Competitor dashboard → premium UI, $49/mo price` |
| Ссылка на статью | URL + резюме в одну строку | `nikolenko.ru/llm-memory → review of 11 LLM memory approaches` |
| Данные API/БД | Источник + формат + ключевой вывод | `PostgreSQL EXPLAIN → seq scan on users, index needed` |

### Правила

1. **Краткость:** 1-2 строки на пункт, не копируйте содержимое
2. **Ключевые числа:** если есть цифры, метрики, цены — фиксируйте их
3. **Связь с knowledge/:** если материал относится к существующей странице — отметьте `→ related to [[slug]]`
4. **Без дублирования:** если документ уже находится в `assets/` — используйте только путь к ресурсу
5. **Чувствительные данные:** если материал содержит приватную информацию — пометьте `[REDACTED: reason]`

---

## Метаобзор (`!meta-review`)

Анализ накопленных резюме сессий. Запускается по `!meta-review` (или когда владелец просит об этом другими словами). `STATUS.md` считает ожидающие файлы сессий (`sessions awaiting meta-review: N → !meta-review`); предлагайте команду, когда число растёт, не запускайте самостоятельно.

### Процесс

1. Найдите необработанные файлы сессий: все `.md` внутри `interactions/sessions/`, во frontmatter которых не указано `meta_reviewed: true`. `!import` сохраняет входящую копию, отличающуюся от локального файла, рядом с ним (`<name>__from-<label>-<sha8>.md`, `kb-docs/16_MERGE.md`): это та же сессия — если хотя бы в одной копии есть `meta_reviewed: true`, пометьте другую, не анализируя повторно
2. Ищите повторяющиеся паттерны:
   - Какие вопросы встречаются чаще всего?
   - Какие предпочтения по стилю повторяются?
   - Какие области знаний требуют обновления?
   - Где AI ответил плохо — и почему?
3. Запишите каждый паттерн (3+ повторений, см. антисаботаж) в `interactions/insights/YYYY-MM__insight-slug.md`
4. Запишите отчёт запуска `interactions/meta-reviews/YYYY-MM-DD.md`: проанализированные файлы сессий, найденные паттерны, предложенные обновления `knowledge/`
5. Владелец подтверждает или отклоняет каждое предложенное обновление; применяйте только подтверждённые
6. Пометьте каждый проанализированный файл сессии — добавьте `meta_reviewed: true` во frontmatter, создав его при отсутствии (логическое значение YAML; строка `"true"` не считается). Файлы, которые ничему не научили, тоже помечаются
7. Запишите операцию `meta-review` в журнал

Отсутствие паттернов — допустимый результат: запишите отчёт, пометьте файлы, остановитесь.

### Формат вывода

```markdown
---
period: "2026-05"
sessions_analyzed: 12
---

# Insight: Author prefers bullet points over prose

## Pattern
In 8 of 12 sessions the author asked to reformat long paragraphs into lists.

## Recommendation
Update knowledge/voice/communication-style.md:
add the rule "default to bullet points; prose only for narrative".

## Action
- [ ] Update knowledge/voice/communication-style.md
```

---

## Рефлексия — выводы более высокого уровня (с учётом режима)

Периодический синтез: от сырых фактов → к выводам высокого уровня. `scripts/kb_reflect.py` решает, **когда** пора проводить рефлексию; сама рефлексия — работа агента (`!reflect`, ~15K токенов). Активный профиль задаётся в `mode_profiles.<knowledge_base.mode>.reflection` файла `kb.config.yml`.

### Когда пора проводить

`python3 scripts/kb_reflect.py --check-threshold` сравнивает **оценку изменений** с последней рефлексии с профилем:

- каждая запись `ingest` в `log.md` имеет вес `importance` из её метаданных ingest или `default_ingest_importance` (1), если его нет;
- каждая страница `knowledge/`, содержимое которой изменилось с последней рефлексии, имеет вес её `importance` (3, если не задан); учёт обращений (`last_accessed`, `access_count`) не считается изменением, а сгенерированные страницы (`generated_by:`) и `_archive/` не учитываются (подробности: `kb-docs/13_AUTORUN.md`).

| Решение | Значение |
|---------|----------|
| `THRESHOLD_MET` | Пора проводить рефлексию |
| `STAGNANT` | Пора было бы проводить, но последние две рефлексии дали 0 выводов и с тех пор не было ingest |
| `SKIP` | Делать нечего |

Когда проверка выдаёт `THRESHOLD_MET`, `STATUS.md` показывает `reflection due … → !reflect`, а переиндексация, запускающая консолидацию (не чаще, чем каждые `autorun.consolidation_interval_hours`, когда `autorun.consolidation_on_reindex` равен true), записывает `reflect-request`. Саму рефлексию ничто не запускает: предложите владельцу `!reflect`.

#### `knowledge_base.mode: default` — с ограничением частоты

| Триггер | Как |
|---------|-----|
| **Порог importance** | Оценка изменений ≥ `importance_threshold` (25) |
| **Еженедельно** | ≥ `min_interval_days` (7) с последней рефлексии — или с развёртывания, если рефлексий ещё не было — **и** как минимум одно изменение |
| **Команда `!reflect`** | Пользователь явно просит рефлексию — выполняется всегда |

Для базы без рефлексий недельный отсчёт начинается с развёртывания (`deployed_at` в `kb.config.yml` или первая запись `log.md`, если она старше): первый ingest сам по себе не означает рефлексию. Рефлексия, записанная с 0 выводов, перезапускает недельный отсчёт.

#### `knowledge_base.mode: super` — по потребности

| Триггер | Как |
|---------|-----|
| **Каждое значимое изменение** | Оценка изменений ≥ 5: одна изменённая страница с importance 5, две изменённые страницы без importance или пять ingest без importance |
| **Команда `!reflect`** | Пользователь явно просит |
| **Без минимального интервала** | Без привязки к 7 дням; совсем нет изменений → `SKIP` |

Каждая рефлексия стоит ~15K токенов.

```yaml
# kb.config.yml — mode_profiles.<mode>.reflection (read by kb_reflect.py):
mode_profiles:
  default:
    reflection:
      trigger: "threshold+weekly"    # threshold, plus weekly once min_interval_days passed
      importance_threshold: 25       # due when the change score reaches it
      min_interval_days: 7           # weekly spacing
      require_changes: true          # weekly: only with at least one change
      max_insights_per_run: 3        # ceiling, not a quota — 0 insights is valid
      # default_ingest_importance: 1 # weight of an ingest without importance
  super:
    reflection:
      trigger: "on-demand"
      importance_threshold: 5
      min_interval_days: 0
      require_changes: false
      max_insights_per_run: 5
```

### Ограничители

- **Честный ноль.** Отсутствие нового вывода — допустимый ожидаемый результат. Зафиксируйте его (`python3 scripts/kb_reflect.py --record-result 0`) и остановитесь. Не выдумывайте выводы ради заполнения `max_insights_per_run`.
- **Метаинсайт (уровень 2)** допустим, только если с последней рефлексии уровня 1 появились новые факты уровня 0 (ingest). `kb_reflect.py --json` сообщает об этом в `meta_insight_allowed`.
- **Застой.** Две последовательные рефлексии с 0 выводов → проверка выдаёт `STAGNANT` вместо `THRESHOLD_MET`, пока не появится новый ingest. Пользовательская `!reflect` всё равно выполняется.

### Процесс

1. `python3 scripts/kb_reflect.py --json`: оценка изменений, `max_insights_per_run`, `meta_insight_allowed`, пары `exploration`
2. AI формулирует 3 важных вопроса о недавнем опыте
3. Для каждого ищет релевантные страницы через маршрутизацию и wikilinks
4. Синтезирует вывод более высокого уровня
5. Записывает не более `max_insights_per_run` страниц в `knowledge/insights/` с `[[wikilinks]]` на страницы-источники — или не записывает ни одной
6. **Всегда завершайте командой** `python3 scripts/kb_reflect.py --record-result N` (N = число записанных страниц выводов, 0 допустим). Только этот вызов ставит отметку `.last_reflection` и журналирует `reflect | insights: N`; без него оценка изменений продолжает расти, а рефлексия остаётся ожидающей

### Формат вывода

```markdown
---
source: "reflection"
extracted_at: 2026-05-06
confidence: medium
importance: 7
lifecycle: "evolving"
tags: [architecture, insight]
children:
  - "knowledge/domain/caching.md"
  - "knowledge/decisions/2026-03__dragonfly.md"
---

# Insight: caching is our key performance lever

Conclusion: over 3 months we changed the caching layer three times...

Related: [[caching]], [[dragonfly-migration]], [[cache-patterns]]
```

### Дерево знаний

Уровень 0: `domain/` + `playbooks/` (факты) → уровень 1: `insights/` (синтез) → уровень 2: метаинсайты в `insights/`. **Не более 3 уровней.**

---

## Саморедактирование — эволюция заметок (с учётом режима)

Когда новое знание связано с существующим, старая страница получает запись `context_annotations`. Python-аннотатора нет: в обоих режимах аннотации — работа агента, а `mode_profiles.<mode>.annotations.engine` определяет, сколько усилий потратить.

### Когда применяется

- Разрешение сущностей при ingest сопоставило сущность с существующей страницей: `processed/nlp-meta/<name>.yml` → `entities[].existing_page` (пакет проверки перечисляет их в "NLP enrichment")
- Страница query-writeback пересекается с существующей

### `engine: "python"` (режим default) — шаблонная заметка

Добавьте запись, не читая связанную страницу. `note` — шаблонный текст, построенный из NLP-совпадения: `"NLP-match: entity 'knowledge-base'"`.

### `engine: "ai"` (режим super) — содержательная аннотация (~1-3K токенов)

AI-агент **читает** связанную страницу и новый материал, затем пишет:

1. **Содержательную аннотацию:** не просто "NLP-match", а описание, *в чём* состоит связь
2. **Конкретные предложения правок** существующей страницы (если новый материал дополняет или уточняет её)
3. **Выявление противоречий** между новым и существующим знанием
4. **Рекомендацию объединить/разделить**, когда аннотаций >5

### Формат `context_annotations`

```yaml
# default mode:
context_annotations:
  - date: 2026-05-06
    related: "knowledge/domain/llm-wiki-pattern.md"
    note: "NLP-match: entity 'knowledge-base'"

# super mode:
context_annotations:
  - date: 2026-05-06
    related: "knowledge/domain/llm-wiki-pattern.md"
    note: "New benchmark showed throughput drop — extends Performance section in [[caching]]"
    suggested_edit: "Add a paragraph about degradation under load"
    contradiction: null
```

### Правила

1. **default:** `note` — шаблонный текст; связанная страница не читается
2. **super:** `note` — содержательное описание связи (~1-3K токенов)
3. **Максимум 5 аннотаций** на страницу (больше → lint `annotation-overflow` предлагает создать вывод)
4. Файлы с `lifecycle: permanent` — аннотации добавляются, тело не трогается

---

## Фильтрация по новизне — пока не реализована

`mode_profiles.*.surprise` зарезервирован (`docs/ROADMAP.md` движка): ни один скрипт не оценивает новизну источника, а ingest не пишет `is_surprise`. Пока механизма нет, применяйте результат вручную при извлечении или writeback — сначала проверяйте связанные страницы:

- **Ничего нового** → обновите существующую страницу или добавьте запись `context_annotations` вместо создания новой
- **Новое** → добавьте
- **Противоречит** существующим знаниям → добавьте И создайте запись в `knowledge/open-questions/`

---

## Антисаботаж

Фильтр качества защищает базу от деградации:

1. **Проверка фактов:** если вывод противоречит 3+ существующим фактам — не добавляйте; создайте вопрос в `knowledge/open-questions/`
2. **Повторяемость:** единичный случай — не паттерн. Записывайте как паттерн только после 3+ повторений
3. **Конструктивность:** эмоциональные или разрушительные высказывания отфильтровываются на этапе резюме сессии
4. **Прозрачность:** каждое обновление `knowledge/` фиксирует источник (какую сессию или вывод) во frontmatter

---

## Query → Wiki Writeback

Ценный ответ AI может стать страницей `knowledge/`, не дожидаясь метаобзора — **когда владелец согласится** (или по `!save` / «сохрани это»). Предложите одной строкой («Сохранить это сравнение как `knowledge/domain/rag-vs-wiki.md`?»); не записывайте самостоятельно.

### Когда предлагать

| Критерий | Пример |
|----------|--------|
| Синтез из 3+ источников | Сравнение архитектур, обзор подходов |
| Архитектурное решение с обоснованием | «Почему Docker Swarm, а не K8s» |
| Сравнительный анализ | Таблица компромиссов, плюсы/минусы |
| Ответ противоречит knowledge/ | → предложить запись в `knowledge/open-questions/` |

### Когда НЕ предлагать

- Тривиальные ответы (однострочные)
- Код без архитектурного обоснования
- Ответы, полностью дублирующие существующую страницу `knowledge/`
- Ответы с низкой уверенностью без проверки

### Формат страницы writeback

```markdown
---
source: "query-writeback"
session: "interactions/sessions/2026-05-07__highway-clicker__kb/"
extracted_at: 2026-05-07
confidence: medium
verification_method: "ai-review"
lifecycle: "evolving"
importance: 6
tags: [architecture, comparison]
query: "Why is LLM Wiki better than RAG at our scale?"
---

# RAG vs LLM Wiki: analysis for our project

## Conclusion
...

## Rationale
...

## Related pages
- [[knowledge-management]]
- [[decisions/2026-05__kb-architecture]]
```

### После writeback

1. Допишите в `log.md` (операция `query-writeback`)
2. Добавьте `[[wikilinks]]` на связанные страницы `knowledge/`
3. Маршрутизация пересоздаётся при переиндексации: `kb_route.py` переписывает `knowledge/routing/*.md` и блок `AUTO-ROUTING` в `routing-table.md` — никогда не редактируйте их вручную; правьте `routing-table.md` вне блока, только если странице нужна новая строка темы
4. При следующей переиндексации страница попадает в свой пак Repomix

---

## `!audit` — чистый контекст, по пакам

Автор страницы не должен быть её единственным проверяющим. `kb_reindex.py` пишет `.repomix/audit/<pack>__request.md` (пак + список проверки + формат отчёта) и `CROSS_PACK__request.md` (только заголовки).

`!audit` → одна **новая сессия** на каждый файл запроса. Вы не можете открыть её самостоятельно: попросите владельца начать новый чат (или субагента с чистым контекстом, если инструмент это позволяет) и передать ему файл запроса. Находка без `file:line` и цитаты отбрасывается. Скрипта `kb_audit.py` нет.

## `!profile-review`

`knowledge/profile/` имеет `permanent` по политике папки (`lifecycle.by_folder` → `profile: permanent`, значение по умолчанию в `kb.config.yml`), поэтому проверка устаревания его пропускает.

1. Прочитайте, что вы знаете об авторе из `knowledge/profile/`. Чего не хватает? Задавайте **по три вопроса**, важные первыми. По ответам обновляйте страницы.
2. Затем: что может быть устаревшим или неполным? Тот же ритм.

Поставьте отметку `profile_review.reviewed_at` в `kb.config.yml` (измените только эту строку; сохраните комментарии). Lint предупреждает через 30 дней, если поле задано; отсутствующее поле не даёт предупреждения.

## `!quiz`

База экзаменует владельца. Это единственная команда, которая проверяет человека, а не страницы.

1. Просмотрите `knowledge/profile/`, `knowledge/principles/`, `knowledge/decisions/` и `knowledge/routing-table.md`. Не загружайте всю базу.
2. Задайте **пять вопросов** о том, что уже находится в базе. Начните с **самых дорогих ошибок** (тихое противоречие, решение, которое владелец не хотел бы увидеть перевёрнутым, факт, который AI выдумает, если страница скудная). Затем пробелы покрытия. Затем проверка воспоминания о датированном решении.
3. По одному вопросу допустимо, если владелец отвечает в чате; пачкой — только по его просьбе.
4. Запишите лист в `interactions/quiz/YYYY-MM-DD.md` (не индексируется): вопрос, ответ владельца, страница, где это должно было находиться, нужна ли правка страницы. Журналируйте операцию `quiz`.
5. Если ответ противоречит странице — не «исправляйте» её молча. Покажите diff и ждите.

Скрипта `kb_quiz.py` нет.

## Слот исследования (`!reflect`)

Когда `kb_reflect.py --json` возвращает пары `exploration`, возьмите **не более двух** как вопросы рефлексии: «Что связывает [[A]] и [[B]], чего граф не показывает?» Пары — несвязанные компоненты (или узлы без направленного пути) с пересечением тегов/заголовков `< 0.8`. Пустой список допустим — не выдумывайте связь. Новые выводы из реальной связи идут в `knowledge/insights/`.

---

## Журналирование

Все операции цикла обратной связи записываются в `log.md` (см. `kb-docs/10_LOG.md`):
- `session-capture` — когда записывается резюме сессии
- `query-writeback` — когда сохраняется ценный ответ
- `meta-review` — когда завершается `!meta-review` (проанализированные сессии, записанные выводы)
- `quiz` — когда `!quiz` пишет в `interactions/quiz/`
- `reflect` — записывается `kb_reflect.py --record-result N`; `reflect-request` — записывается `kb_reflect.py --generate` во время консолидации
