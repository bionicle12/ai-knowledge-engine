---
translation_of: knowledge-base/09_LINT.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 09 — Lint: периодическая проверка здоровья базы знаний

> Операция lint проверяет состояние **существующей** базы. В отличие от разбора (04), работающего с входящими материалами, lint анализирует уже имеющееся в `knowledge/`.
>
> **Эталонная реализация:** `knowledge-base/scripts/kb_lint.py`. Агент копирует этот скрипт при развёртывании.

---

## Зачем

Без обслуживания база знаний деградирует: факты устаревают, страницы теряют связи, появляются противоречия. Lint выявляет проблемы до того, как ИИ-агент начнёт отвечать по устаревшим данным.

---

## Два уровня проверок

### Уровень 1: автоматический (Python)

Выполняется `scripts/kb_lint.py`: детерминированно, без LLM. Имя в первом столбце принимает `--only`, оно же выводится в квадратных скобках отчёта.

| Проверка | Что делает | Серьёзность |
|-------|--------------|----------|
| `frontmatter` | Проверяет обязательные поля всех файлов `knowledge/`: `source`, `extracted_at`, `tags`, `lifecycle`; допустимы `lifecycle` = `permanent` / `evolving` / `temporal`. Также сообщает **`frontmatter-yaml`** — frontmatter не разбирается (некорректный YAML, не отображение, нет закрывающего `---`); `--fix` такую страницу никогда не меняет; и **`frontmatter-type`** — `source` / `source_hash` не строка, `supersedes` не slug/путь или их список, `citations` не список отображений | 🔴 ошибка |
| `stale` | Более новая из дат `last_verified` / `extracted_at` старше `lifecycle.stale_warning_days` (по умолчанию 30). **Никогда** для `_archive/`, сгенерированных страниц (`generated_by:`), эффективного lifecycle `permanent` или `valid_until` ≥ сегодня; страница без обеих дат не считается устаревшей. То же правило (`kb_common.stale_status`) использует просмотрщик графа | 🟡 предупреждение |
| `broken-link` | `[[wikilink]]` не ведёт ни на одну страницу знаний. Сопоставление без учёта регистра; поддерживаются `[[page#section]]`, `[[page.md]]`, `[[page\|alias]]`, `[[knowledge/domain/page]]` и частичный путь вроде `[[sub/page]]` (по окончанию, как в Obsidian); вложения (`![[diagram.png]]`) и ссылки внутри кода игнорируются | 🔴 ошибка |
| `orphan` | На страницу нет входящих `[[wikilink]]` с других страниц. Пропускает `routing/`, `routing-table.md`, `_archive/` и сгенерированные страницы | 🟡 предупреждение |
| `source-hash` | `source_hash` отличается от фактического хеша источника (отсутствующий источник — предупреждение; `source:` вне базы через `..`, абсолютный путь или символическую ссылку — предупреждение, такой файл никогда не читается). **Пропускает** эффективный lifecycle `permanent`. Хеши кешируются в `.kb-state/lint-hash-cache.json` и пересчитываются только при изменении размера или mtime источника | 🔴 ошибка |
| `empty-category` | **Пользовательская** подпапка `knowledge/` без `.md`. Стандартные папки, создаваемые `kb_ingest.py --init-dirs`, служат полками совместимости и никогда не отмечаются | 🟡 предупреждение |
| `superseded` | Страница A содержит `supersedes: B` (slug, путь или их список), но B не в `_archive/`. **Пропускает** B с эффективным lifecycle `permanent` | 🟡 предупреждение |
| `duplicate-slug` | У двух файлов вне `_archive/` одинаковый slug без учёта регистра в разных подпапках | 🔴 ошибка |
| `citation` | `citations[].source_span` не указывает файл внутри базы либо диапазон `#Lx-Ly` заканчивается после последней строки; отсутствие `source_span` тоже отмечается. Для других форматов (`#page=`, `#section=`, таймкоды) проверяется только файл | 🟡 предупреждение |
| `domain-overflow` | Подпапка `knowledge/` содержит > 15 `.md`, не считая страниц в любых папках `_archive/` → предложение консолидации | 🟡 предупреждение |
| `low-importance` | `importance` < 3 + эффективный lifecycle `temporal` + `last_accessed` старше 90 дней (без `last_accessed` — более новая из `last_verified` / `extracted_at`) → предложение переместить в `_archive/`. Пропускает `_archive/` и сгенерированные страницы | ℹ️ информация |
| `annotation-overflow` | У файла > 5 `context_annotations` → предложение создать инсайт | ℹ️ информация |
| `expired-temporal` | Эффективный lifecycle `temporal` + `valid_until` < сегодня + файл вне `_archive/` | 🟡 предупреждение |
| `invariants` | В `AGENTS.md` отсутствует обязательный блок `AI-KE:INVARIANT` (`forbidden`, `language`) либо повреждены маркеры. Пропускается, если `AGENTS.md` отсутствует | 🔴 ошибка |
| `agents-bytes` | **Развёрнутый** `AGENTS.md` больше `instructions_lint.agents_max_bytes` (по умолчанию 10240 / 10 KiB) → предложение `!refactor`. Стандартный шаблон уже содержит все управляемые блоки (INDEX, STATUS, VIEW) и укладывается в 9 KiB, оставляя место дополнениям базы | 🟡 предупреждение |
| `instruction-absolutes` | Число `always` / `never` / `must` / `forbidden` и русских `всегда` / `никогда` / `обязательно` / `запрещено` / `запрещается` / `нельзя` вне блоков INVARIANT превышает `absolute_max_outside_invariants` (по умолчанию 8) | 🟡 предупреждение |
| `work-ordering` | Любая настроенная фраза без учёта регистра (`thoroughly`, `consider all`, `максимально тщательно`, …): они увеличивают объём рассуждений, а не точность | 🟡 предупреждение |
| `instruction-duplicates` | `AGENTS.md` повторяет `privacy.*` или `language_policy` из `kb.config.yml`. Текст **внутри** `AI-KE:INVARIANT` освобождён от проверки: копия там намеренная и должна переживать сокращения | ℹ️ информация |
| `instructions-review` | `instructions_review.reviewed_at` старше `review_stale_days` (по умолчанию 90). **Пропускает** отсутствующее поле. Процедура: `17_REFACTOR.md` | 🟡 предупреждение |
| `assumption-hotspot` | Более 3 пунктов `## Assumptions` с упоминанием одного `knowledge/<area>/` за 30 дней → уточнить `DATA_PLACEMENT_EXAMPLES.md` | ℹ️ информация |
| `profile-review` | `profile_review.reviewed_at` старше 30 дней. **Пропускает** отсутствующее поле. Процедура: `!profile-review` | 🟡 предупреждение |
| `secret` | Страница `knowledge/`, включая frontmatter, содержит похожий на учётные данные текст по шаблонам `privacy.secret_scan`, используемым при приёме: токены GitHub / Slack / Stripe / OpenAI, ключи доступа AWS, заголовки закрытых ключей (ошибка), присваивания вида `password:` / `secret=` (предупреждение: возможны совпадения в прозе о паролях). Сообщает тип и номера строк, никогда значение. Проверка безопасности repomix молча исключает такую страницу из пакета, а `knowledge/` коммитится: удалить значение (оставив заглушку вроде `<redacted>`) или перенести страницу в `review/needs-redaction/`. Отключена при `privacy.secret_scan: false` | 🔴 ошибка / 🟡 предупреждение |

В отчёте встречаются ещё два имени, не являющиеся проверками `--only`: `unreadable` (страница не является текстом UTF-8) и `config` (`kb.config.yml` не разбирается; lint работает со значениями по умолчанию из кода).

**Эффективный lifecycle** — собственное значение `lifecycle` страницы, если оно отлично от `lifecycle.default`; иначе — самое глубокое совпадение в `lifecycle.by_folder` (по умолчанию `decisions`, `profile`, `principles` → `permanent`), иначе `lifecycle.default` (`evolving`). Поэтому страница решения, которой `--fix` или шаблон поставил `lifecycle: evolving`, всё равно постоянная, а явное `lifecycle: temporal` имеет приоритет над папкой.

Сбой проверки из-за страницы отмечается **на этой странице** (ошибка с именем проверки), после чего выполнение продолжается; одна необычная страница никогда не останавливает lint.

Пороги проверок бюджета инструкций находятся в верхнеуровневом `instructions_lint:` файла `kb.config.yml`, не в скрипте и не в `mode_profiles.*.lint` (этот блок относится к уровню 2).

### Уровень 2: ИИ-разбор (LLM) с учётом режима

> ⚠️ **Стоимость:** 50–100K токенов за полный проход (все файлы `knowledge/` в контексте).

Уровень 2 — работа агента; скрипты её не планируют. Агент читает `mode_profiles.<mode>.lint` из `kb.config.yml`:

#### `mode: default`

- Запускается **только** по `!audit`
- `level2_weekly_day` зарезервирован для пока не реализованного недельного расписания (см. `docs/ROADMAP.md`)

#### `mode: super`

- `level2_trigger: "daily"` — политика агента, не расписание: агент может предложить `!audit` в начале сессии и начать после согласия владельца. Ежедневная консолидация в `kb_reindex.py` — скрипт, который никогда не запускает агента (`kb-docs/13_AUTORUN.md`)
- `review_auto_process: true` — если `STATUS.md` показывает элементы `needs-ai-decision`, агент предлагает `!review` в начале сессии и начинает после согласия владельца (`kb-docs/04_REVIEW.md`)

```yaml
# In kb.config.yml — read by the AI agent:
mode_profiles:
  default:
    lint:
      level2_trigger: "manual"       # manual | weekly | daily
      level2_weekly_day: "sunday"    # not implemented yet
      review_auto_process: false
  super:
    lint:
      level2_trigger: "daily"
      review_auto_process: true
```

| Проверка | Что делает |
|-------|--------------|
| **Противоречия** | Находит страницы с несовместимыми утверждениями |
| **Недостающие ссылки** | Страницы на близкие темы без связей |
| **Пробелы данных** | Области со слишком малым объёмом знаний для уверенного ответа |
| **Кандидаты на консолидацию** | Страницы, которые стоит объединить |
| **Рекомендации по актуальности** | Какие страницы перепроверить/обновить |

---

## Формат lint-report

`--output report` записывает `lint-report.md`; без него тот же текст идёт в stdout. `--json` выводит `root`, `scope`, `pages_scanned`, `issues` (`check`, `severity`, `path`, `message`, `fixable`), `fixed`, `metrics`, `exit_code`.

```markdown
# Lint Report — 2026-05-06

## Summary
- Pages scanned: 42
- Errors: 2
- Warnings: 3
- Info: 1
- Auto-fixed: 0

## 🔴 Errors
- **[frontmatter]** `knowledge/domain/caching.md` — missing required fields: extracted_at *(fixable)*
- **[broken-link]** `knowledge/principles/architecture.md` — [[infrastructure-scaling]] does not resolve

## 🟡 Warnings
- **[stale]** `knowledge/projects/highway-clicker.md` — last_verified 2026-03-15 is 52 days old (threshold: 30)
- **[orphan]** `knowledge/domain/nats-evaluation.md` — no inbound wikilinks from any other knowledge page
- **[superseded]** `knowledge/domain/redis-caching.md` — superseded by knowledge/domain/dragonfly-caching.md but not in _archive/

## ℹ️ Info
- **[low-importance]** `knowledge/projects/q1-offsite.md` — importance 2, temporal, last_accessed 2026-01-10 (116 days ago) — consider moving it to knowledge/_archive/
```

Запуск `--quick` добавляет в сводку `- Mode: quick (error-level checks only)`, а `--only` — `- Mode: partial (--only)`.

---

## Контракт `scripts/kb_lint.py`

```text
Usage:
    python3 scripts/kb_lint.py                          # Full lint
    python3 scripts/kb_lint.py --quick                  # Only the checks that can report an error
    python3 scripts/kb_lint.py --fix                    # Add missing frontmatter fields
    python3 scripts/kb_lint.py --output report          # Write to lint-report.md
    python3 scripts/kb_lint.py --only frontmatter       # Run a subset of checks
    python3 scripts/kb_lint.py --json                   # Machine-readable output
    python3 scripts/kb_lint.py --metrics                # Add health metrics
    python3 scripts/kb_lint.py --stale-days 60          # Override lifecycle.stale_warning_days
    python3 scripts/kb_lint.py --log                    # Also record the run in log.md

Exit codes:
    0 — no issues
    1 — warnings or info only
    2 — at least one error (a crash of the script itself also exits 2)
```

Повреждённая установка тоже считается сбоем: когда `scripts/kb_common.py` старше `kb_lint.py` (частичное обновление сохранило изменённый `kb_common.py` и оставило рядом `kb_common.py.new`), lint перечисляет отсутствующие имена и завершается с 2. Папка без `kb.config.yml` не база: lint сообщает это, ничего не записывает и завершается с 2.

`--quick` выполняет `frontmatter`, `broken-link`, `source-hash`, `duplicate-slug`, `invariants`, `secret` — единственные проверки с уровнем ошибки — и выводит только ошибки. `kb_reindex.py` запускает его как шаг пайплайна.

### Возможности автоматического исправления

`--fix` делает ровно одно: добавляет отсутствующие поля frontmatter со значениями по умолчанию — `lifecycle: <lifecycle.default>` (`evolving`), `tags: []`, `extracted_at: <today>`. `source` никогда не выдумывается. Страница с неразбираемым frontmatter (`frontmatter-yaml`) остаётся побайтово неизменной.

Остальное выполняет ИИ-агент или владелец:

- Обновить `last_verified` после перепроверки страницы
- Перенести заменённые или просроченные страницы в `knowledge/_archive/` (никогда `permanent`)
- Исправить или удалить неработающие вики-ссылки
- Разрешить противоречия, создать связи, решить вопрос удаления/слияния
- Изменить `lifecycle` (только по явному запросу пользователя)

---

## Запуск lint

`shell/lint.sh` запускает `scripts/kb_lint.py` из корня базы, передавая все аргументы и код завершения. Интерпретатор выбирает `shell/_kbpy.sh`: `$KB_PYTHON`, иначе `.venv` базы, иначе `python3` (`shell/doctor.sh` так же работает с `kb_doctor.py`):

```bash
./shell/lint.sh                  # full lint
./shell/lint.sh --output report  # lint-report.md
./shell/lint.sh --log            # and a `lint` entry in log.md
```

### Что оставляет запуск

- **`.kb-state/lint-summary.json`** — каждый запуск CLI без `--only` записывает `{"errors", "warnings", "infos", "at", "scope", "full_at"}` (читает `kb_status.py` для `STATUS.md`). `--quick` измеряет только ошибки, сохраняя число предупреждений и информационных записей последнего полного прохода; `full_at` содержит его время. `--only` ничего не записывает.
- **`.kb-state/lint-hash-cache.json`** — кеш хешей источников (выше).
- **`log.md`** — только с `--log`. Lint выполняется при каждой переиндексации; запись каждого запуска засорила бы журнал.

---

## Мутационная проверка (`kb_mutate.py`)

Копирует базу с небольшим начальным кластером во временное дерево, внедряет **семь** дефектов L1 и оценивает lint:

неработающая вики-ссылка, дубликат slug, несовпадение `source_hash`, устаревшие `last_verified` + `extracted_at`, страница без входящих ссылок, просроченный `valid_until`, отсутствующее поле frontmatter.

Мутация считается убитой, только если проверка срабатывает **на изменённой ею странице**; посторонняя проблема в другом месте копии не считается.

```bash
python3 scripts/kb_mutate.py
python3 scripts/kb_doctor.py --with-mutation   # not in the default doctor run
```

Строка отчёта: `7 mutations / 7 killed / 0 survivors`. Выжившие мутации означают, что проверка L1 не видит реальный дефект: исправьте её или зафиксируйте ограничение. Противоречия L2 здесь не внедряются; это задача `!audit`.

---

## Проверка окружения (`kb_doctor.py`)

Lint проверяет знания; `kb_doctor.py` (`./shell/doctor.sh`) — установку. Он никогда не пишет в базу (нет записи `log.md`).

**Doctor пройден = код завершения 0.** Предупреждения (`⚠️`) — рекомендации, они не проваливают проверку; код 2 означает минимум одну ошибку (`❌`). Итоговая строка заканчивается соответственно `PASS` или `FAIL`. Сбой проверки становится одной ошибкой, остальные продолжаются; сбой самого doctor или полностью неимпортируемый `kb_common.py` тоже дают код 2.

Помимо Python-пакетов, папок, `kb.config.yml`, файлов инструкций Codex / Claude Code, spaCy, медиабэкендов, папок синхронизации, состояния heal и `repomix.config.json`, он проверяет:

| Проверка | Ошибка, если | Предупреждение, если |
|-------|------------|--------------|
| `index:repomix` | нет `repomix` и нет `npx` + `node` для закреплённого резервного запуска (`index.repomix_version`, `index.npx_fallback`) | — |
| `index:packs` | пакет имеет `FAILED` в `.repomix/PACKS_STATUS.md` или файл сообщает `Index not built` | индекс ещё не собран; пакет не пересобран (`STALE` — repomix недоступен); `knowledge/` изменилась после переиндексации; превышен предел (`⚠ OVER`); repomix исключил файлы ("Left out by repomix": проверка безопасности или файл исключений); не удалось прочитать ни одной строки пакета |
| `scripts:consistency` | `scripts/kb_*.py` не импортируется либо использует имя `kb_common`, отсутствующее в `scripts/kb_common.py` (частичное обновление; сам doctor работает со старым `kb_common.py`) | — |
| `upgrade:sidecars` | — | необъединённые `.new` после `kb_upgrade` → `!heal` |
| `kb-docs` | `AGENTS.md`, `CLAUDE.md`, `START_HERE.md` или `KNOWLEDGE_STRUCTURE.md` ссылается на отсутствующий `kb-docs/NN_*.md` | совсем нет `kb-docs/` (база до 0.16) |
| `agent-env:claude-md-import` | — | в `CLAUDE.md` нет `@AGENTS.md`; либо `index.primary_agent: claude-code`, а `CLAUDE.md` отсутствует (Claude Code не загрузит `AGENTS.md`) |
| `venv:*` | — | нет `.venv` базы (`venv:missing` — обёртки, лаунчеры и Git-хук запускают `python3`, поэтому необязательные пакеты не используются); окружение, которое они не используют: `knowledge-base/.venv` после `finalize.sh` или окружение запущенного doctor (`venv:stranded`); `.venv/.venv` (вложенное окружение); перемещённое `.venv` (`activate` или `bin/pip` указывают старое место); doctor запущен вне окружения базы |
| `nlp:nltk-data` | — | установлен `rake-nltk`, но нет данных NLTK `stopwords` / `punkt` |
| `log:writable` | `log.md` или корень базы недоступен для записи; проверяется без записи | — |

`--self-test` (для собственной папки движка `knowledge-base/`) пропускает проверки развёртывания: окружение Codex, индекс, `kb-docs/`, venv и heal. `--skip-nlp` пропускает spaCy и проверку данных NLTK.

---

## Рекомендуемая частота

| Режим | Частота | Кто запускает |
|------|-----------|-------------|
| `--quick` | Каждая переиндексация | Автоматически (`kb_reindex.py`, `shell/reindex.sh`) |
| Полный lint | Еженедельно | Вручную или cron |
| ИИ-разбор (уровень 2) | Ежемесячно | ИИ-агент в IDE по запросу |

---

## Интеграция с другими модулями

- **03_PIPELINE:** приём пишет frontmatter с `source_hash` → lint проверяет
- **05_INDEX:** lint проверяет вики-ссылки → индекс обновляется
- **10_LOG:** `kb_lint.py --log` записывает запуск в `log.md`
- **11_PROVENANCE:** lint проверяет хеши источников, файлы/диапазоны строк цитат и правила lifecycle
- **13_AUTORUN:** cron/наблюдатель запускает `--quick` при изменениях
