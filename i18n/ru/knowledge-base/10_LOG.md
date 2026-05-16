---
translation_of: knowledge-base/10_LOG.md
source_commit: 63ec5652913793e80cf7a899c691d34d88285f8a
source_version: 0.9.3
translated_at: 2026-05-17
translator: human
---

# 10 — Хронологический лог операций

> Append-only файл `log.md` фиксирует все операции с базой знаний: ingest, lint, review, query-writeback, session-capture. Это единая timeline эволюции базы.

---

## Зачем

- AI-агент видит **что происходило** с базой в хронологическом порядке
- Быстро определить: когда последний раз ревьюили, что добавляли, что менялось
- Парсится unix-утилитами для быстрого поиска
- Отделяет operational history от knowledge content

---

## Расположение

```
knowledge-base/
└── log.md     # ← append-only, НЕ индексируется Repomix
```

Добавить в `repomix.config.json` → `ignore.customPatterns`:
```json
"log.md",
"lint-report.md"
```

---

## Формат записи

Каждая запись начинается с heading level 2 в стандартном формате:

```
## [ISO-timestamp] operation-type | Human-readable title
```

### Типы операций

| Тип | Когда |
|-----|-------|
| `ingest` | Новый raw-файл обработан pipeline |
| `lint` | Запуск health-check |
| `review` | AI-ревью материала из review/ |
| `query-writeback` | Ценный ответ сохранён в knowledge/ |
| `session-capture` | Session summary записан в interactions/ |
| `update` | Ручное обновление страницы в knowledge/ |
| `archive` | Страница перемещена в _archive/ |
| `reindex` | Repomix-индекс перегенерирован |
| `nlp-enrich` | NLP-предобработка нового материала |

---

## Примеры записей

```markdown
# Operations Log

## [2026-05-06T20:30:00+03:00] ingest | Karpathy LLM-Wiki Article
- Source: raw/reference/unsorted/karpathy-llm-wiki.md
- NLP: 12 entities, 18 keywords, complexity: 0.65
- Created: knowledge/domain/llm-wiki-pattern.md
- Updated: knowledge/principles/knowledge-compilation.md
- Updated: knowledge/decisions/2026-05-06__kb-architecture-shift.md
- Tags: #architecture #knowledge-management #llm

## [2026-05-06T21:00:00+03:00] lint | Weekly health-check
- Mode: full
- Checked: 42 pages
- Errors: 1 (broken wikilink in principles/architecture.md)
- Warnings: 3 (stale: redis-patterns.md, caching.md; orphan: nats-evaluation.md)
- Auto-fixed: 0
- Report: lint-report.md

## [2026-05-07T10:15:00+03:00] query-writeback | Docker Swarm vs K8s comparison
- Question: "Почему Docker Swarm вместо K8s для нашего масштаба?"
- Created: knowledge/decisions/2026-05-07__swarm-vs-k8s.md
- Cross-refs added: [[docker-swarm]], [[infrastructure-decisions]]
- Confidence: medium

## [2026-05-07T14:00:00+03:00] session-capture | highway-clicker auth refactor
- Project: highway-clicker
- Session: interactions/sessions/2026-05-07__highway-clicker__auth/
- Duration: ~45 min
- Insights extracted: 2
- Knowledge updated: knowledge/playbooks/auth-implementation.md

## [2026-05-07T14:05:00+03:00] reindex | Post session-capture
- Pages indexed: 44 (+2 since last)
- Output: .repomix/output.xml
```

---

## Быстрый поиск

```bash
# Последние 10 операций
grep "^## \[" log.md | tail -10

# Все ingest за май
grep "^## \[2026-05" log.md | grep "ingest"

# Все ошибки lint
grep -A5 "^## \[" log.md | grep -B1 "Errors: [1-9]"

# Сколько операций каждого типа
grep "^## \[" log.md | sed 's/.*\] //' | sed 's/ |.*//' | sort | uniq -c | sort -rn
```

---

## Кто пишет в лог

| Источник | Как |
|----------|-----|
| `kb_ingest.py` | Автоматически после обработки каждого файла |
| `kb_lint.py` | Автоматически после каждого запуска |
| `reindex.sh` | Автоматически после перегенерации индекса |
| AI-агент | При query-writeback и session-capture |
| `kb_watch.py` (через `./watcher.sh`) | При автоматической обработке нового файла |

---

## Правила

1. **Append-only:** записи НЕ редактируются и НЕ удаляются
2. **ISO timestamps:** всегда с timezone offset
3. **Bullet-list body:** детали операции — bulleted list под heading
4. **Не индексируется:** log.md исключён из Repomix (operational data, не знание)
5. **Ротация:** при >1000 записей — архивировать в `log-archive/YYYY.md` и начать новый
6. **Git-friendly:** каждая запись — atomic append, минимальные merge-конфликты
