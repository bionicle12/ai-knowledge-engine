---
translation_of: knowledge-base/05_INDEX.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 05 — Индексация и Repomix

> Настройка индекса Repomix: что индексируется, что исключается и как обновляется автоматически.
>
> **Эталонный шаблон:** `knowledge-base/templates/repomix.config.json.template`. Агент копирует его в корень развёрнутой базы как `repomix.config.json` и при необходимости настраивает параметры.
> **Эталонные скрипты:** `knowledge-base/scripts/kb_reindex.py` (пайплайн и сборка индекса), `knowledge-base/scripts/kb_status.py` (`STATUS.md`) и тонкая обёртка `knowledge-base/shell/reindex.sh`, копируемые в `scripts/` и `shell/` развёрнутой базы.

---

## Принцип: только чистые данные

Индекс Repomix содержит **только**:

- `knowledge/**/*.md` — извлечённые знания
- `assets-index/**/*.md` — описания бинарных файлов
- Метафайлы: `KNOWLEDGE_STRUCTURE.md`, `DATA_PLACEMENT_EXAMPLES.md` (без `README.md`: у базы нет собственного README, а README проекта в корне не входит в пакеты; без `kb.config.yml`: `AGENTS.md` предписывает читать его напрямую в начале сессии, поэтому упакованная копия удвоила бы расход токенов)

**Не индексируются:** `raw/`, `processed/`, `assets/`, `review/`, `interactions/`, `setup/`, `scripts/`, **а также `AGENTS.md`** — он уже загружается в системный промпт каждой сессии; индексация оплатила бы его токены дважды.

**Обязательная защита приватности в коде.** `kb_reindex.py` добавляет эти шаблоны исключений в конфигурацию каждого пакета (и как `--ignore` при старой сборке), независимо от `repomix.config.json` или явного списка `packs:`:

- `raw/**`, `review/**`, `interactions/**` — каждый, если соответствующий флаг `privacy.raw_indexing_allowed` / `review_indexing_allowed` / `interactions_indexing_allowed` в `kb.config.yml` не установлен явно в `true`;
- всегда: `processed/**`, `assets/**`, `sync/**`, `eval/**`, `setup/**`, `kb-docs/**`, `.kb-state/**`, `.kb-backups/**`, `.kb-finalize-backup/**`, `.repomix/**`, `.venv/**`, `venv/**`, `.git/**`, `node_modules/**`, `log.md`, `log-archive/**`, `STATUS.md` (и `status.file`, если задан другой путь), `.env`, `.env.*`, `**/*.pem`, `**/*.key`.

Соответствующие им файлы никогда не входят в пакеты, даже при оценке числа токенов.

---

## Принцип: пакеты вместо монолита

Единый `.repomix/output.xml` перестаёт работать с ростом базы: библиотека справочных книг легко превышает 150–250 тысяч токенов и уже не помещается в окно 256K *ещё до начала сессии*. «Прочитать индекс для общего контекста» превращается в засорение контекста. Длинные диалоги деградируют: модель заметно теряет нить.

Поэтому индекс собирается в **смысловые пакеты**, каждый с пределом токенов:

| Профиль окна | Предел пакета |
|---------------|-------------|
| `400k` (Codex) | 120K |
| `256k` (Cursor / консервативное значение по умолчанию) | 80K |
| `200k` | 60K |
| `1m` (Claude Code 1M) | 150K |

- `core.xml` — профиль автора, принципы, голос, таблицы маршрутизации, два метафайла. По замыслу небольшой; его всегда безопасно загружать.
- По одному пакету на раздел `knowledge/` (`domain.xml`, `insights.xml`, …). Имена `core`, `aux`, `knowledge-root` зарезервированы: раздел `knowledge/core/` упаковывается как `knowledge-core.xml` и никогда не перезаписывает настоящий core.
- Страницы непосредственно в `knowledge/` (например `glossary.md`; сама таблица маршрутизации относится к core) образуют `knowledge-root.xml` или входят в `aux.xml`, пока невелики. Каждая страница `knowledge/` попадает ровно в один пакет, кроме папок верхнего уровня с `_` или `.` в начале (например `_archive/`), которые никогда не упаковываются.
- Раздел **выше предела автоматически делится по подпапкам**: `knowledge/library/craft/` → `library-craft.xml` и т. д. Справочная библиотека никогда не делит пакет с рабочими знаниями; книжные пакеты загружаются только для задач о них.
- Разделы меньше ~15K объединяются в общий `aux.xml` (маршрутизация между двадцатью микрофайлами столь же неудобна, как один гигантский файл).
- `.repomix/PACKS_STATUS.md` — автоматически создаваемая таблица пакетов с актуальными оценками токенов; агенты читают её вместо жёстко заданных чисел (подробности ниже).
- `.repomix/audit/<pack>__request.md` — задание `!audit` для каждого пакета (новая сессия, обязательны `file:line` и цитата), а также `CROSS_PACK__request.md` (только заголовки).

Правило загрузки для агента (уже в шаблоне AGENTS.md): выбрать маршрут через `knowledge/routing-table.md`, затем загрузить `core` и **не больше одного** предметного пакета на задачу.

Настройки находятся в разделе `index:` файла `kb.config.yml` (см. `templates/kb.config.yml.template`): `window_profile`, необязательные переопределения `pack_token_ceiling` / `merge_below_tokens`, `repomix_version`, `npx_fallback` (см. «Установка repomix» ниже) и `packs: auto` (рекомендуется) либо явный список пакетов. В явном списке имя пакета используется как имя файла: разделители пути заменяются на `-`, начальная точка удаляется, повторное имя получает суффикс `-2` с предупреждением.

```yaml
index:
  packs:
    - name: library-craft
      include: ["knowledge/library/craft/**"]
      when_to_load: "writing-craft questions"
```

`kb_reindex.py` планирует пакеты, создаёт `.repomix/configs/<pack>.json` из базового `repomix.config.json`, собирает только неактуальные пакеты и **предупреждает о превышении предела** — сигнале для дальнейшего деления (более глубокие подпапки или явный список `packs:`).

### Актуальность: `.repomix/manifest.json`

После каждой сборки `kb_reindex.py` записывает для каждого пакета SHA-256 созданной конфигурации, всех файлов пакета (`files`) и файлов исключений, которые repomix применяет дополнительно (`ignore_sha256`: `.gitignore`, `.ignore`, `.repomixignore` в корне базы и папке каждого файла, `.git/info/exclude`, а также `.gitignore` выше базы до корня охватывающего рабочего дерева Git), состояние и время последней успешной сборки. Пакет **актуален**, только если его выходной файл существует, а все три составляющие совпадают с последней успешной сборкой. Поэтому удаление, переименование или редактирование страницы, как и её скрытие/открытие через `.gitignore`, вызывает пересборку, а `touch` без изменения содержимого — нет. Первый запуск после обновления пересобирает все пакеты (у старых баз нет манифеста).

repomix записывает каждый пакет в `.repomix/<name>.xml.building` (`-o`); файл заменяет пакет, только если процесс завершился с кодом 0 **и** создал этот файл. Неудачная сборка или отсутствие результата получает `FAILED` и сохраняет прежнюю копию без изменений; она никогда не считается актуальной.

После каждой сборки `kb_reindex.py` сопоставляет состав пакета с записями `<file path=…>` полученного XML (`output.style: xml`, значение по умолчанию). repomix молча исключает файл, если проверка безопасности находит похожий на учётные данные текст либо его скрывает `.gitignore` / `.ignore` / `.repomixignore`. Такие файлы записываются для каждого пакета (`left_out` в манифесте), выводятся, перечисляются в `PACKS_STATUS.md` под "Left out by repomix" и учитываются в строке `index:` файла `STATUS.md`, пока пакет актуален. Проверка `secret` в `kb_lint.py` указывает строки (`09_LINT.md`).

Пакеты, вышедшие из плана (переименованный раздел, изменённый список `packs:`), **удаляются**: `.repomix/<name>.xml`, `configs/<name>.json`, `audit/<name>__request.md`. Старый `.repomix/output.xml` никогда не удаляется; в режиме пакетов запуск лишь напоминает, что его безопасно удалить.

### `.repomix/PACKS_STATUS.md`

Перезаписывается при каждом запуске индексации, даже если ничего не удалось собрать, по манифесту: время проверки, использованный сборщик, затем строка на пакет.

| Столбец | Значение |
|--------|---------|
| ~Tokens | Размер собранного пакета (оценка o200k); для несобранного — оценка исходных файлов. При превышении предела после числа идёт `⚠ OVER`. |
| Last build | `rebuilt <time>` (собран сейчас), `fresh (built <time>)`, `FAILED` (сборка не удалась или не создала результат), `STALE — repomix unavailable`; два последних дополняются `copy from <time> kept`, если старая копия осталась на диске. |
| Load when | Подсказка по маршрутизации. |

Итоговая строка считает пакеты `OVER ceiling`, `FAILED`, `STALE` с именами и перечисляет удалённые в этом запуске осиротевшие пакеты. Если весь индекс не удалось собрать (некорректный `repomix.config.json`, пустой явный список), файл начинается с `**Index not built:** <reason>`.

Базы, развёрнутые до режима пакетов, продолжают работать: без раздела `index:` или при `index.enabled: false` скрипт `kb_reindex.py` собирает старый монолит — `output.filePath` из базового `repomix.config.json`, обычно `.repomix/output.xml` — с обязательной защитой приватности и через тот же временный файл. При превышении ~150K токенов он выводит заметное предупреждение включить пакеты. Результат записывается в `.repomix/manifest.json` (`"mode": "legacy"`), а `PACKS_STATUS.md` получает единственную строку `output.xml (legacy monolith)` (предел 150K). При возврате от пакетов к старому режиму база теряет файлы пакетов (`.xml`, конфигурации, задания аудита): обновлять их больше нечему.

---

## Почему здесь обязательно `compress: false`

Для **кода** сжатие Tree-sitter — разумный компромисс: структура остаётся, тела методов исчезают; детали агент может перечитать в исходниках.

В **базе знаний сам текст и есть содержание**: формулировки, нюансы, полные абзацы извлечённых знаний. Сжатие удалило бы именно то, что база призвана сохранять. Поэтому каждый пакет базы сохраняет `compress: false, removeComments: false`, а размер регулируется **более подробным делением** (пакеты, подпапки), никогда сжатием.

---

## repomix.config.json (базовая конфигурация)

В режиме пакетов это **базовая конфигурация**: `kb_reindex.py` наследует `ignore` / `security` / `tokenCount` / параметры вывода в каждый `.repomix/configs/<pack>.json`, переопределяя только `include`, `filePath`, заголовок пакета и добавляя обязательные исключения приватности (выше) в `ignore.customPatterns`. Собственные `include`/`filePath` используются напрямую только в старом режиме без `index:`.

Полная эталонная копия — `templates/repomix.config.json.template`. Главное в обоих режимах:

- `compress: false`, `removeComments: false` — см. выше.
- `ignore.customPatterns` исключает `raw/`, `processed/`, `assets/`, `review/`, `interactions/`, `eval/`, `kb-docs/`, `.kb-state/`, `.kb-backups/`, `setup/`, `scripts/`, `.repomix/`, журналы, `STATUS.md`, `HEAL_PLAN.md`, файлы секретов и все бинарные форматы.
- `tokenCount.encoding: o200k_base`.
- Файл должен быть **обычным JSON**. Сам repomix допускает завершающие запятые и комментарии, Python — нет: если `kb_reindex.py` не может разобрать файл, он ничего не собирает, завершается с кодом 1, а `PACKS_STATUS.md` сообщает причину (список исключений этого файла помогает не допускать приватные папки в индекс).

---

## Установка repomix

`kb_reindex.py` использует `repomix` из `PATH` (`npm install -g repomix@1.14.0`; нужен Node.js). Если его нет и `index.npx_fallback: true` (по умолчанию), выполняется `npx --yes repomix@<index.repomix_version>`: версия закреплена (`1.14.0` по умолчанию), никогда не `@latest`; первый запуск её скачивает. Если недоступны оба способа, пакеты, которым нужна сборка, остаются `STALE`, выводится инструкция по установке repomix, а запуск **завершается с кодом 1**; уже актуальным пакетам repomix вообще не нужен.

---

## Запуск пайплайна: `kb_reindex.py` и `shell/reindex.sh`

`scripts/kb_reindex.py` — единая реализация. `shell/reindex.sh` (Linux/macOS) лишь запускает её, передаёт все флаги и возвращает её код; запускаемый двойным щелчком Windows-файл `shell/reindex.bat` вызывает её без флагов. Наблюдатель (`--no-ingest`: приём уже выполнен) и Git-хук (`--hook`: только индекс и `STATUS.md`) тоже обращаются к ней; единая реализация предотвращает расхождения шагов и сообщений. Полный запуск:

1. приём (`kb_ingest.py`);
2. страницы маршрутизации (`kb_route.py`);
3. быстрая проверка (`kb_lint.py --quick`);
4. консолидация, не чаще раза в `autorun.consolidation_interval_hours` (по умолчанию 24; маркер `.last_consolidation`): отчёт lint, пакетная NLP-обработка и, при `autorun.consolidation_on_reindex` равном true (по умолчанию), `kb_reflect.py --check-threshold`; при `THRESHOLD_MET` запускается `kb_reflect.py --generate`, записывающий запрос рефлексии в `log.md`;
5. индекс (пакеты или старый монолит);
6. `STATUS.md` (ниже).

| Флаг | Действие |
|------|--------|
| *(нет)* | Полный пайплайн. |
| `--quick` | Пропустить консолидацию (шаг 4). `--no-watch` — устаревший псевдоним. |
| `--no-ingest` | Пропустить приём (наблюдатель уже выполнил его). |
| `--no-index` | Пропустить индекс (шаг 5). |
| `--index-only` | Только индекс + `STATUS.md`. |
| `--force` | Пересобрать все пакеты, включая актуальные. |
| `--hook` | Режим Git-хука, см. ниже. |

Коды завершения: `0`, если все выполненные шаги успешны; `1`, если `kb_ingest.py` завершился с ошибкой (остальные шаги всё равно выполняются), индекс неполон (repomix недоступен, пакет `FAILED`, некорректный `repomix.config.json`) или другой запуск удерживал блокировку; `2`, если в корне нет `kb.config.yml` — запуск вне базы ничего туда не записывает (`--hook` завершается с 0).

**Один запуск за раз.** Каждый запуск удерживает блокировку `pipeline` (`.kb-state/locks/pipeline.lock`); дочерние скрипты разделяют её. Второй запуск ждёт до 10 минут, затем завершается с кодом 1.

```bash
python3 scripts/kb_reindex.py --index-only            # only stale packs
python3 scripts/kb_reindex.py --index-only --force    # everything
./shell/reindex.sh --quick                            # same flags via the wrapper
```

---

## `STATUS.md`: передача состояния сессии

`scripts/kb_status.py` записывает `<base>/STATUS.md` (`status.file`) в конце каждого запуска `kb_reindex.py`, во всех режимах, включая `--hook`, кроме `status.enabled: false`. Агент читает его в начале сессии (`!status` запускает скрипт). Файл исключён через gitignore и никогда не индексируется.

```markdown
# KB status — 2026-09-24T10:00:00+03:00 (generated by kb_status.py, do not edit)

- review queues: needs-ai-decision 3 (oldest 12d) → !review
- merge queue: 2 (oldest 1d) → !merge
- extraction pending in processed/: 9 (oldest 30d) → !review
- stuck in raw/**/unsorted: 2 (duplicate 1, error 1) → python3 scripts/kb_ingest.py --status
- reflection due (changes 31 ≥ 25) → !reflect
- heal: 4 open (assisted 3, human 1) → !heal
- index: 1 pack OVER ceiling, 0 FAILED → see .repomix/PACKS_STATUS.md
- sessions awaiting meta-review: 5 → !meta-review
- lint: 0 errors, 4 warnings → python3 scripts/kb_lint.py
```

Выводятся лишь ненулевые строки, каждая заканчивается командой для решения. При отсутствии ожидающих действий файл содержит `- all clear`. На источник — не более строки, поэтому файл короче 20 строк:

| Строка | Источник |
|------|-------|
| review queues / merge queue / extraction pending / stuck in unsorted | `kb_ingest.collect_status()` (`kb_ingest.py --status`); `review/needs-merge/` — очередь слияния (обрабатывает `!merge`, `!review` её оставляет), все прочие `review/needs-*`, кроме `needs-heal`, — очереди разбора |
| reflection due | `kb_reflect.check()` — решение `THRESHOLD_MET` |
| heal | комментарий `<!-- heal-summary: … -->` в первой строке `review/needs-heal/HEAL_PLAN.md` (записывает `kb_heal.py`); без комментария — число файлов в `review/needs-heal/`. Эта папка никогда не входит в очереди разбора: её обрабатывает `!heal`, а не `!review` |
| index | `.repomix/manifest.json`: пакеты выше предела, `FAILED`, `STALE` ("not rebuilt"), файлы, исключённые repomix из собранного пакета (`left_out`, "left out by repomix"); `index: not built`, если вся сборка остановлена; в старом режиме — `index: legacy output.xml FAILED` / `not rebuilt (repomix unavailable)` / `OVER ceiling` |
| sessions awaiting meta-review | `interactions/sessions/**/*.md` без `meta_reviewed: true` во frontmatter |
| lint | `.kb-state/lint-summary.json`, записанный `kb_lint.py` |

Каждый источник необязателен: отсутствие или ошибка чтения убирает только его строку с предупреждением в stderr, но не весь файл.

`status.file` должен находиться внутри базы, а существующий файл перезаписывается, только если пуст или создан `kb_status.py` (первая строка — заголовок выше). В остальных случаях (`AGENTS.md`, `kb.config.yml`, страница знаний) скрипт предупреждает и записывает `STATUS.md`; если и тот чужой, ничего не записывает и завершается с кодом 1. Без `kb.config.yml` в корне завершается с 2.

```bash
python3 scripts/kb_status.py            # write STATUS.md and print it
python3 scripts/kb_status.py --print    # print only, write nothing
python3 scripts/kb_status.py --json     # {generated_at, file, enabled, all_clear, items: [{key, text, command}]}
```

---

## Git-хуки и автозапуск

Полная настройка автоматизации — в `13_AUTORUN.md`:

- Наблюдатель файлов (демон watchdog) — выполняет `kb_reindex.py --no-ingest` после приёма изменения
- Git-хуки (`shell/install-hooks.sh` устанавливает `shell/hooks/post-commit`)
- Cron (периодические lint + переиндексация)

Хук post-commit запускает `python3 scripts/kb_reindex.py --hook` в фоне: только индекс + `STATUS.md`, без приёма, маршрутизации, lint и запроса рефлексии. Он ждёт блокировку пайплайна не более 5 секунд, затем пропускает запуск (следующий наверстает); файловая система без поддержки блокировок тоже вызывает пропуск. Весь вывод идёт в `.kb-state/hooks.log`, а код завершения всегда 0.

---

## Перекрёстные ссылки: соглашение `[[wikilinks]]`

Файлы `knowledge/` ссылаются друг на друга через вики-ссылки:

```markdown
# Example in knowledge/domain/caching.md
We use [[DragonflyDB]] as a Redis-compatible cache (see [[infrastructure-decisions]]).
We dropped [[NATS]] in favor of Redis pub/sub (see [[decisions/2026-03__no-nats]]).
```

### Форматы ссылок

| Формат | Куда ведёт |
|--------|-------------|
| `[[slug]]` | Поиск `slug.md` в любой подпапке `knowledge/` |
| `[[domain/caching]]` | Точный путь: `knowledge/domain/caching.md` |
| `[[decisions/2026-03__no-nats]]` | Точный путь: `knowledge/decisions/2026-03__no-nats.md` |

### Правила

1. Slug = имя файла без `.md`
2. При конфликте slug (одинаковые имена в разных папках) использовать полный путь
3. `kb_lint.py` проверяет каждую вики-ссылку
4. Неработающие ссылки → ошибка lint
5. ИИ-агент **обязан** добавлять вики-ссылки на связанные страницы при создании/обновлении файлов `knowledge/`

### Необязательная автоматизация

Python-помощник может предлагать вики-ссылки:

```python
def suggest_wikilinks(text: str, knowledge_slugs: dict) -> list:
    """Find mentions of entity names from knowledge/ and suggest [[wrapping]]."""
```

---

## Таблицы маршрутизации: навигация для больших баз

Когда в `knowledge/` больше 50 файлов, плоский индекс превращается в свалку контекста. Таблицы маршрутизации дают двухуровневую навигацию.

### `knowledge/routing-table.md` (верхний уровень)

```markdown
# Routing Table

## Domains
- [[rt/infrastructure]] — Docker, Traefik, DB, caching, networking
- [[rt/game-logic]] — clicks, settlements, economy, events, corps
- [[rt/frontend]] — React, PixiJS, HUD, biomes, scenes, i18n
- [[rt/auth]] — providers, sessions, JWT, brute-force, audit
- [[rt/devops]] — CI/CD, monitoring, deployment, backups

## Meta
- [[rt/profile]] — author, expertise, preferences
- [[rt/principles]] — working principles, quality bars
- [[rt/decisions-log]] — chronology of key decisions
```

### `knowledge/routing/rt-infrastructure.md` (второй уровень)

```markdown
# Infrastructure

## Key pages
- [[domain/docker-swarm]] — why Swarm, not K8s
- [[domain/caching]] — DragonflyDB, caching patterns
- [[domain/database]] — PostgreSQL 16, migrations, indexes

## Adjacent areas
- → [[rt/devops]] for CI/CD and monitoring
- → [[rt/auth]] for authentication infrastructure
```

### Навигация агента

1. Читает `routing-table.md` (~20 строк)
2. Выбирает тему → переходит на страницу маршрутизации
3. Находит конкретные страницы → читает их
4. **3 перехода** вместо чтения всего индекса

Каждая переиндексация (шаг 2, `kb_route.py`) обновляет `knowledge/routing/<section>.md` для каждого непустого раздела и автоматически управляемый блок (`<!-- AUTO-ROUTING:BEGIN -->` … `END`) в `routing-table.md`; всё вне блока поддерживает ИИ-агент. Lint проверяет все ссылки таблицы маршрутизации.
