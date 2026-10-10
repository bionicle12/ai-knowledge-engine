---
translation_of: knowledge-base/13_AUTORUN.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 13 — Автозапуск: автоматическая обработка изменений

> База знаний должна обновляться **автоматически** при поступлении данных. Три механизма: наблюдатель файлов (демон), Git-хук, cron; плюс консолидация при каждой полной переиндексации.
>
> **Эталонные реализации** (поставляются с базой; модуль описывает поведение, точный код — в скриптах): `scripts/kb_watch.py`, `scripts/kb_reindex.py`, `scripts/kb_reflect.py`, `scripts/kb_nlp_batch.py`, `shell/watcher.sh`, `shell/reindex.sh`, `shell/install-hooks.sh`, `shell/hooks/post-commit`.

---

## Зачем

Ручной `./shell/reindex.sh` после каждого изменения создаёт трение, из-за которого база устаревает. Автоматизация убирает этот барьер.

---

## Способ 1: наблюдатель файлов (рекомендуется при активной работе)

### Зависимости

`watchdog` (в `requirements.txt`). Без него `kb_watch.py` опрашивает файлы раз в 2 секунды: медленнее, поведение то же.

### Что делает `scripts/kb_watch.py`

Наблюдает папки из `autorun.watch_dirs` (по умолчанию `raw/*/unsorted/` и `knowledge/`). Записи внутри `raw/` — входящие папки приёма; `raw/*/unsorted/` включает общую `raw/unsorted/`. В остальных отслеживаются изменения `.md`.

| Событие | Ожидание | Действие |
|-------|------|--------|
| Новый файл во входящей папке, включая вложенные | файл не меняется `debounce_raw_seconds` (5) | готовые файлы принимаются вместе: `kb_ingest.py` с максимум 100 путями за вызов (`--no-nlp` при `auto_nlp: false`), затем один `kb_reindex.py --no-ingest` |
| Создание, изменение, перемещение или удаление страницы `.md` в `knowledge/` | `debounce_knowledge_seconds` (2) без изменений | `kb_lint.py --quick` (`auto_lint_on_change`), затем `kb_reindex.py --no-ingest` (`auto_reindex_on_change`) |
| Запуск наблюдателя | — | уже ожидающие во входящих папках файлы ставятся в очередь как новые |

- **Никогда не передаются на приём:** имена из `ingest.ignore_globs` (`.DS_Store`, `~$*`, `*.part`, `*.tmp`, …).
- **Игнорируются как изменения:** `knowledge/routing/` и `knowledge/routing-table.md`. `kb_reindex.py` обновляет их через `kb_route.py`, который переписывает страницу только при изменении содержимого (иначе даты и счётчики доступа остаются прежними), поэтому наблюдатель не реагирует на свою переиндексацию.
- `--no-reindex` — никогда не запускать `kb_reindex.py`; `--verbose` — выводить каждую команду.
- **Один наблюдатель на базу:** удерживает `.kb-state/locks/watch.lock`; второй завершается с кодом 1.
- `--root` может быть относительным (сначала приводится к абсолютному); папка без `kb.config.yml` отклоняется (код 2).
- `autorun.watch_enabled: false` — `kb_watch.py` выводит пояснение и завершается с 0.
- **Остановка:** по SIGTERM (`./shell/watcher.sh --stop`, systemd) наблюдатель завершает текущий шаг (приём или переиндексация не обрываются), затем выходит. Ctrl+C в терминале достигает и процесса текущего шага, прерывая его.

### Запуск через `shell/watcher.sh`

```bash
./shell/watcher.sh                  # foreground (Ctrl+C to stop); options go to kb_watch.py
./shell/watcher.sh --verbose        # e.g. foreground with every command printed
./shell/watcher.sh --daemon         # background: pidfile .watcher.pid, log .watcher.log
./shell/watcher.sh --status         # is the background watcher running?
./shell/watcher.sh --stop           # stop it and wait until it has exited
```

- Интерпретатор выбирает `shell/_kbpy.sh`: `$KB_PYTHON`, иначе `.venv/bin/python`, иначе `python3`.
- `--daemon` сообщает об ошибке и показывает хвост журнала, если наблюдатель сразу завершился, например при `watch_enabled: false` или уже работающем наблюдателе.
- `--stop` отправляет SIGTERM и ждёт завершения до 30 секунд; сообщает "stopped" только после выхода. Сначала проверяет, что PID из `.watcher.pid` всё ещё принадлежит наблюдателю: устаревший pidfile после перезагрузки или повторного использования PID никогда не завершает чужую программу.
- Лаунчеры двойного щелчка: `watcher-start.command` (macOS, Linux) и `watcher-start.bat` (Windows) запускают наблюдатель на переднем плане своего терминала (Ctrl+C или закрытие окна останавливают его); `watcher-stop.command` выполняет `./shell/watcher.sh --stop` для наблюдателя `--daemon`.

### Служба systemd (Linux)

```ini
# ~/.config/systemd/user/kb-watch.service
[Unit]
Description=Knowledge Base File Watcher

[Service]
Type=simple
WorkingDirectory=/path/to/knowledge-base
ExecStart=/path/to/knowledge-base/.venv/bin/python scripts/kb_watch.py --root /path/to/knowledge-base
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now kb-watch
systemctl --user status kb-watch
```

Не запускайте службу systemd и `./shell/watcher.sh --daemon` для одной базы: второй наблюдатель завершится с кодом 1, а systemd будет бесконечно перезапускать его.

---

## Способ 2: Git-хук

Для баз под управлением Git.

```bash
bash shell/install-hooks.sh   # once per clone: .git/hooks/ is not versioned
```

`install-hooks.sh` (обычный POSIX sh; работает и `sh shell/install-hooks.sh`) устанавливает `shell/hooks/post-commit` в папку хуков репозитория (`git rev-parse --git-path hooks`) и предупреждает, если `core.hooksPath` указывает в другое место. Существующий `post-commit`, отличающийся от поставляемого (чужой хук, старая или изменённая наша копия), сначала перемещается в `post-commit.backup-<timestamp>`, никогда не удаляется. База в подпапке рабочего дерева записывается в `git config kb.root`. Хук запускает `kb_reindex.py --hook` в фоне и сразу возвращается:

- **Поиск базы:** папка `kb.root`, иначе корень рабочего дерева (например после уплощения проекта через `finalize.sh`). Нет базы — хук ничего не делает.
- **Облегчённый режим:** только индекс + `STATUS.md`, без приёма и запроса рефлексии. Остальное делает наблюдатель или ручная переиндексация.
- Захватывает блокировку пайплайна с коротким ожиданием и тихо выходит, если она занята.
- Вывод идёт в `.kb-state/hooks.log` (никогда в `/dev/null`: проглоченные ошибки незаметно разрушают актуальность индекса); после 1 MB журнал перемещается в `hooks.log.1`.
- Код завершения всегда 0: хук никогда не блокирует коммит.
- Следующий запуск `install-hooks.sh` заменяет установленную копию. Для сочетания со своими post-commit-командами оставьте собственный хук и вызывайте из него `sh <base>/shell/hooks/post-commit` вместо установщика.

Правила хуков, выработанные практикой (каждое связано с реальным производственным сбоем), если пишете собственный:

1. `post-commit` не срабатывает на `git pull`, merge, rebase. После них запускайте `./shell/reindex.sh` или самостоятельно установите тот же хук как `post-merge` / `post-rewrite`.
2. Git GUI и IDE запускают хуки с минимальным `PATH`: передавайте работу `kb_reindex.py`, который *сообщает* об отсутствии repomix вместо молчаливого пропуска.
3. Обычный фоновый `... &` завершается от SIGHUP при выходе хука: используйте `nohup` и перенаправление вывода в журнал.
4. Хуки никогда не должны блокировать Git: всегда `exit 0`.
5. Храните исходники хуков в репозитории (`shell/hooks/`) и документируйте установку одной командой после клонирования.

**Необязательная проверка pre-commit:** `python3 scripts/kb_lint.py --quick --only frontmatter` возвращает ненулевой код при ошибках frontmatter; вызовите её из `.git/hooks/pre-commit`, чтобы блокировать такие коммиты.

---

## Способ 3: cron (периодические задачи)

```bash
# crontab -e — a full reindex (with consolidation) every night at 03:00
0 3 * * * cd /path/to/knowledge-base && mkdir -p .kb-state && .venv/bin/python scripts/kb_reindex.py >> .kb-state/cron.log 2>&1
```

Никогда не добавляйте вывод инструментов в `log.md`: у него строгий формат, а скрипты пишут собственные записи.

> **Важно:** компьютер может быть выключен; cron не гарантирует выполнение. Поэтому консолидация встроена в каждую полную переиндексацию (ниже), а не в cron.

---

## Консолидация при каждой переиндексации

Проблема: задачи cron не запускаются на выключенном компьютере. Решение: каждый полный запуск `kb_reindex.py` (`./shell/reindex.sh` — тонкая обёртка) проверяет, пора ли выполнять консолидацию.

- **Когда:** `.last_consolidation` старше `autorun.consolidation_interval_hours` (24) или отсутствует. Не при `--quick`, `--index-only`, `--hook`.
- **Что:** полный отчёт lint (`lint-report.md`), `kb_nlp_batch.py --incremental`, затем при `autorun.consolidation_on_reindex` равном true (по умолчанию) проверка `kb_reflect.py --check-threshold`. При `THRESHOLD_MET` выполняется `kb_reflect.py --generate`, добавляющий `reflect-request` в `log.md`.
- **Затем:** каждая переиндексация, с консолидацией или без неё, заканчивается перезаписью `STATUS.md` (кроме `status.enabled: false`) — краткой передачей состояния, которую агент читает в начале сессии ("reflection due … → !reflect").

Точные шаги: `scripts/kb_reindex.py` и `kb-docs/05_INDEX.md`.

Ни один скрипт не обрабатывает очереди разбора и не запускает lint уровня 2 с ИИ. Настройки `mode_profiles.*.lint` (`level2_trigger`, `review_auto_process`) — политика агента; см. `kb-docs/07_INTERACTION_LOOP.md` и `kb-docs/09_LINT.md`.

### Триггер рефлексии (`scripts/kb_reflect.py`)

Скрипт лишь принимает решение; сама рефлексия — работа ИИ (`!reflect`, ~15K токенов).

| Решение | Значение |
|----------|---------|
| `THRESHOLD_MET` | Пора проводить рефлексию: оценка изменений с последней достигла порога |
| `STAGNANT` | Пора, но две последние записанные рефлексии нашли 0 инсайтов, и с тех пор не было приёма; плановая рефлексия подавляется, а `!reflect` владельца всё равно выполняется |
| `SKIP` | Делать нечего |

- **Оценка изменений** с последней рефлексии: каждая запись `ingest` в `log.md` имеет вес важности из метаданных приёма или `default_ingest_importance` (1) при её отсутствии; каждая изменённая страница `knowledge/` — вес `importance` (3, если не задан). Сгенерированные страницы (`generated_by`) и `_archive/` не учитываются.
- **Изменённая страница:** `--record-result` сохраняет дайджест каждой страницы в `.kb-state/reflection-pages.json`, и страница учитывается, если содержимое отличается. Отслеживание доступа (`last_accessed`, `access_count`) не считается изменением, как и touch, checkout или восстановление без изменения содержимого. Без снимка свидетельства слабее. Если последняя рефлексия определяется локальным `.last_reflection` (база до 0.16, до первого `--record-result`), решает mtime файла. Если известна только запись `reflect` в `log.md` (свежее клонирование или рефлексия с другой машины), mtime ничего не говорит: клонирование сбрасывает его везде; страница учитывается, только если её `extracted_at`, `last_verified` или `valid_from` приходится на день этой рефлексии или позже.
- **Порог:** `mode_profiles.<mode>.reflection.importance_threshold` активного режима (`knowledge_base.mode`). В недельных профилях (`trigger: "threshold+weekly"`) после `min_interval_days` порог падает до 1: любое изменение требует рефлексии (0 при `require_changes: false`).
- **Последняя рефлексия:** более новая из `.last_reflection` и последней записи `reflect` в `log.md`, поэтому свежий клон без исключённого через gitignore маркера не пересчитывает старый приём. Записи после неё определяются по позиции в `log.md`: приём в ту же секунду, что `--record-result`, тоже учитывается. База без рефлексий отсчитывает `min_interval_days` от развёртывания: более ранней из `deployed_at` в `kb.config.yml` и первой записи `log.md`. Поэтому первый приём сам по себе не требует рефлексии; `elapsed_days` в `--json` тогда означает дни с развёртывания.
- **Кто что записывает:** только `--record-result N` записывает состояние — `.last_reflection`, снимок страниц и журнал `reflect | insights: N` (0 инсайтов — допустимый ожидаемый результат). `--generate` добавляет один `reflect-request` только при `THRESHOLD_MET`, не повторяя его, пока запрос ожидает; при `SKIP` / `STAGNANT` не пишет. Остальные вызовы только читают: без флагов, `--json`, `--check-threshold [--json]`, `--count-changes`. `--dry-run` принимается, но устарел (остальные вызовы и так не записывают).
- `--check-threshold --json` выводит `{decision, changes, threshold, mode, count, trigger, reason}`: `changes` — взвешенная оценка для сравнения с `threshold`, `count` — число изменённых элементов, `trigger` — `importance` или `weekly`.
- `--json` (без `--check-threshold`) добавляет задание агенту: `max_insights_per_run` (верхний предел, не квота), `meta_insight_allowed` (новый приём с последней рефлексии), `stagnation`, `exploration` — до двух пар страниц из несвязанных компонентов графа (перекрытие `< 0.8`), которые агент может использовать как вопросы рефлексии. Пустой список допустим. Парам нужен весь граф страниц, поэтому строят его только `--json` и записываемый запрос.

### Умное расписание рефлексии (режим default)

```
Days without reflection:  1  2  3  4  5  6  7  8  9  10  ...
Were there changes?       -  -  -  -  -  -  -  -  ✓  -   ...
                                                    ↑
                                          Due! (≥7 days + changes)
```

- **< 7 дней** с последней рефлексии или развёртывания, если рефлексий ещё нет → только при достижении `importance_threshold` (25)
- **≥ 7 дней**, без изменений → не требуется; отсчёт продолжается
- **≥ 7 дней** и есть изменения → требуется
- агент завершает `--record-result N`, сбрасывающим счётчик

### Гарантии

- Консолидация выполняется **не чаще раза в `consolidation_interval_hours`** (маркер `.last_consolidation`).
- Срабатывает при **любой** полной переиндексации: вручную, лаунчером (`reindex.command` / `reindex.bat`), наблюдателем.
- Если компьютер был выключен 3 дня, первая полная переиндексация наверстает пропущенное.
- Lint и проверка рефлексии выполняются **до** пересборки индекса.

---

## Таблица триггеров

| Событие | Действие | Источник |
|-------|--------|--------|
| `!view` | Запустить или снова открыть локальный просмотрщик графа только для чтения | `python3 scripts/kb_view.py --background` |
| `!status` | Показать, что требует внимания | `python3 scripts/kb_status.py --print` |
| Новый файл в `raw/*/unsorted/` или `raw/unsorted/` | Приём (+ NLP) → переиндексация | `./shell/watcher.sh` |
| Изменение в `knowledge/` | Быстрый lint + переиндексация | `./shell/watcher.sh` |
| Git-коммит | Индекс + `STATUS.md` (`kb_reindex.py --hook`) | Git-хук |
| `!save` в ИИ-сессии | Сохранение сессии с обогащением → переиндексация | ИИ-агент |
| `!reflect` | Рефлексия: генерация инсайтов (~15K токенов), затем `kb_reflect.py --record-result N` | ИИ-агент |
| `!audit` | Разбор L2 по пакетам из `.repomix/audit/<pack>__request.md` | ИИ-агент |
| `!profile-review` | Интервью по `knowledge/profile/` (по 3 вопроса) | ИИ-агент |
| `!quiz` | Пять вопросов о содержимом базы; сначала самые дорогие ошибки | ИИ-агент |
| `!heal` | Приведение базы в актуальное состояние после обновления (`kb_heal.py --plan` / `--apply auto`) | ИИ-агент |
| `!refactor` | Двухэтапное сокращение инструкций (`kb-docs/17_REFACTOR.md`) | ИИ-агент |
| `kb_lint.py --fix` изменил страницы | Быстрый lint + переиндексация (видны как изменения `knowledge/`) | `./shell/watcher.sh` |
| ИИ выполнил query-writeback | Запись страницы → переиндексация | ИИ-агент |
| Ночью (необязательно) | Полная переиндексация с консолидацией | cron |
| Полная переиндексация, консолидация просрочена (> 24h) | Отчёт lint + пакетная NLP-обработка + проверка рефлексии; `reflect-request` при `THRESHOLD_MET` | `kb_reindex.py` |

---

## Настройки в `kb.config.yml`

```yaml
autorun:
  watch_enabled: true               # false: kb_watch.py exits at once
  watch_dirs:                       # raw/… entries = ingest inboxes; others = .md edits
    - "raw/*/unsorted/"
    - "knowledge/"
  debounce_raw_seconds: 5           # a new file must stay unchanged this long
  debounce_knowledge_seconds: 2     # quiet time after knowledge/ edits
  auto_nlp: true                    # false: the watcher ingests with --no-nlp
  auto_lint_on_change: true         # quick lint on knowledge/ edits
  auto_reindex_on_change: true      # reindex on knowledge/ edits
  consolidation_interval_hours: 24  # min interval between consolidations
  consolidation_on_reindex: true    # consolidation requests a reflection when due
  # complexity_auto_threshold: deprecated — nlp.complexity_threshold is the only threshold

mode_profiles:
  default:
    reflection:
      trigger: "threshold+weekly"
      importance_threshold: 25
      min_interval_days: 7
      require_changes: true
      max_insights_per_run: 3
      # default_ingest_importance: 1  # weight of an ingest without importance
```

Каждый ключ имеет значение по умолчанию в коде: старый `kb.config.yml` без них продолжает работать.

---

## Интеграция

- **03_PIPELINE:** наблюдатель принимает новые файлы входящих папок пакетами
- **05_INDEX:** наблюдатель и Git-хук запускают `kb_reindex.py`; каждая переиндексация заканчивается `STATUS.md`
- **07_INTERACTION_LOOP:** `kb_reflect.py` решает, пора ли проводить рефлексию; `!reflect` заканчивается `--record-result N`
- **09_LINT:** наблюдатель → быстрый lint; консолидация → полный отчёт lint
- **10_LOG:** скрипты добавляют собственные записи (`ingest`, `reflect-request`, `reflect`, …) в `log.md`
- **12_NLP:** наблюдатель запускает NLP при приёме (`auto_nlp`); консолидация — `kb_nlp_batch.py --incremental`
