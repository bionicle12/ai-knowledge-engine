---
translation_of: knowledge-base/10_LOG.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 10 — Журнал операций (хронология)

> Журнал `log.md`, допускающий только добавление, фиксирует операции с базой знаний: приём, разбор, query-writeback, сохранение сессий, рефлексию, восстановление, слияния. Это единая временная шкала развития базы.

---

## Зачем

- ИИ-агент видит **что происходило** с базой в хронологическом порядке
- Можно быстро узнать, когда был последний разбор, что добавлено и изменено
- Формат разбирается Unix-утилитами для быстрого поиска
- История операций отделена от содержания знаний

---

## Расположение

```
<base root>/
├── log.md         # ← append-only, NOT indexed by Repomix
└── log-archive/   # ← rotated older entries (see Rules)
```

Стандартный `repomix.config.json` уже исключает `log.md`, `log-archive/**` и `lint-report.md` из индекса (`ignore.customPatterns`).

---

## Формат записи

Каждая запись начинается с заголовка второго уровня строго в таком формате:

```
## [ISO-timestamp] operation-type | Human-readable title
```

Скрипты записывают через `kb_common.append_log`, который заполняет время (местное со смещением) и превращает `details` в пункты списка.

### Типы операций

| Тип | Когда | Кто записывает |
|------|------|------------|
| `ingest` | Новый сырой файл обработан пайплайном | `kb_ingest.py` (один раз на файл) |
| `ingest-duplicate` | Сырой файл повторяет существующий ресурс и перенесён в `ingest.duplicates_dir` | `kb_ingest.py` |
| `reprocess` | Существующий ресурс обработан повторно | `kb_ingest.py` |
| `nlp-batch` | Пакетное NLP-обогащение `processed/` обновило хотя бы один файл | `kb_nlp_batch.py` |
| `lint` | Выполнена проверка здоровья | Только `kb_lint.py --log` |
| `reflect-request` | Достигнут порог и запрошена рефлексия | `kb_reflect.py --generate` |
| `reflect` | Рефлексия завершена (`insights: N`, допустим 0) | `kb_reflect.py --record-result N` |
| `heal` | Приведение базы в актуальное состояние после обновления применило автоисправления | `kb_heal.py` |
| `export` | Записан пакет синхронизации | `kb_export.py` |
| `import` | Пакет синхронизации объединён | `kb_import.py` |
| `import-undo` | Объединение пакета отменено | `kb_import.py --undo` |
| `populate` | Из файла роли создан `DATA_PLACEMENT_EXAMPLES.md` | `kb_populate.py` (в базе с `kb.config.yml`) |
| `review` | ИИ обработал элемент `review/` или `processed/` | `kb_ingest.py --mark-extracted` / `--mark-skipped` или ИИ-агент |
| `query-writeback` | Ценный ответ сохранён в `knowledge/` | ИИ-агент |
| `session-capture` | Сводка сессии записана в `interactions/` | `kb_save_session.py` или ИИ-агент |
| `meta-review` | Завершён метаобзор сводок сессий (`!meta-review`): сессии проанализированы, инсайты записаны | ИИ-агент |
| `update` | Ручная правка страницы `knowledge/` | ИИ-агент |
| `archive` | Страница перенесена в `_archive/` | ИИ-агент |
| `refactor` | Сокращение инструкций (`!refactor` / `17_REFACTOR.md`) | ИИ-агент |
| `quiz` | Экзамен владельца (`!quiz`), ответы в `interactions/quiz/` | ИИ-агент |

`kb_ingest.py --mark-extracted` / `--mark-skipped` дают записи `review` заголовок `extracted: <asset file>` / `skipped: <asset file>`. Запись о файле приватной категории (`privacy.redact_categories` или находящемся на проверке приватности) никогда не содержит имя файла: заголовок `<category> item <sha8>` совпадает с блоком `assets-index/`, а пункты не содержат путей ресурсов.

`kb_doctor.py`, `kb_reindex.py`, `kb_route.py` и `kb_mutate.py` не пишут в журнал.

---

## Примеры записей

```markdown
# Operations Log

## [2026-05-06T20:30:00+03:00] ingest | 2026-05-06__karpathy-llm-wiki.md
- Source hash: sha256:3f2a9c0e71b4d5a8
- Asset: assets/documents/2026-05-06__karpathy-llm-wiki.md
- Processed: processed/markdown/2026-05-06__karpathy-llm-wiki.md
- NLP meta: processed/nlp-meta/2026-05-06__karpathy-llm-wiki.yml
- Complexity: 0.65

## [2026-05-06T21:00:00+03:00] lint | Health-check
- Mode: full
- Checked: 42 pages
- Errors: 1
- Warnings: 3
- Info: 0
- Auto-fixed: 0
- Report: lint-report.md

## [2026-05-07T10:15:00+03:00] query-writeback | Docker Swarm vs K8s comparison
- Question: "Why Docker Swarm instead of K8s at our scale?"
- Created: knowledge/decisions/2026-05-07__swarm-vs-k8s.md
- Cross-refs added: [[docker-swarm]], [[infrastructure-decisions]]
- Confidence: medium

## [2026-05-07T14:00:00+03:00] session-capture | highway-clicker auth refactor
- Project: highway-clicker
- Session: interactions/sessions/2026-05-07__highway-clicker__auth/
- Duration: ~45 min
- Insights extracted: 2
- Knowledge updated: knowledge/playbooks/auth-implementation.md
```

Конкретные пункты записи определяет скрипт; контракт задаёт формат заголовка.

---

## Быстрый поиск

```bash
# Last 10 operations
grep "^## \[" log.md | tail -10

# All ingest entries in May
grep "^## \[2026-05" log.md | grep "ingest"

# All logged lint runs that found errors
grep -A5 "^## \[.*\] lint |" log.md | grep -B3 "Errors: [1-9]"

# How many of each operation type
grep "^## \[" log.md | sed 's/.*\] //' | sed 's/ |.*//' | sort | uniq -c | sort -rn
```

---

## Правила

1. **Только добавление:** записи НЕ редактируются и НЕ удаляются (ротация перемещает их, не теряя)
2. **Время ISO:** всегда со смещением часового пояса (без него запись читается как местное время)
3. **Тело — список:** детали операции оформляются пунктами под заголовком
4. **Без индексации:** `log.md` исключён из Repomix (операционные данные, не знания)
5. **Ротация:** когда в log.md больше `logging.rotation_threshold` записей (по умолчанию 1000; 0 = выключено), `append_log` переносит самые старые в `<logging.archive_dir>/log-YYYY-MM.md` по месяцу записи и оставляет новейшую половину
6. **Удобство для Git:** каждая запись добавляется атомарно → минимум конфликтов слияния
