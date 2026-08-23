---
translation_of: knowledge-base/14_INITIAL_POPULATION.md
source_commit: e630f31fd065e0e360416d60c166232da2494398
source_version: 0.15.0
translated_at: 2026-08-23
translator: ai-assisted
---

# 14 — Initial Population Helper

> После завершения `02_INIT` агент **обязан** сгенерировать персонализированный `DATA_PLACEMENT_EXAMPLES.md` для выбранной роли. Это устраняет «эффект пустых папок»: пользователь смотрит на `raw/work/unsorted/` и не понимает, что туда класть.
>
> **Reference template:** `knowledge-base/templates/DATA_PLACEMENT_EXAMPLES.md.template` — стартовый скелет.
> **Reference role template (для кастомных ролей):** `knowledge-base/templates/role.yml.template`.
> **Reference generator (предпочтительный путь):** `scripts/kb_populate.py` — yaml → markdown без LLM-токенов.
> **Эскизы структуры (до папок):** `scripts/kb_structure.py` — четыре варианта + список слепых зон из того же YAML (`02_INIT.md`).
> **Источник примеров:** секция `placement_examples:` внутри `examples/<role>.yml`.
>
> ⚠️ **Замечание о путях:** во время развёртывания база живёт в `<project-root>/knowledge-base/`, поэтому на этапе сборки правильный аргумент — `--kb-root knowledge-base`. После `setup/shell/finalize.sh` база лежит плоско в корне проекта, и повторные запуски используют `--kb-root .` (или вовсе без флага, так как cwd — корень). Примеры ниже предполагают путь этапа развёртывания.

---

## Два пути

У агента есть два способа получить `DATA_PLACEMENT_EXAMPLES.md`:

| Путь | Когда | Стоимость |
|------|-------|-----------|
| **A. Встроенная роль** — пользователь выбрал существующий шаблон | Запустить `kb_populate.py --role <role>`, затем опциональное ревью | ~50 токенов (только на вызов скрипта) |
| **B. Кастомная роль** — пользователь придумал новую роль | Собрать `examples/<slug>.yml` из `role.yml.template`, сохранить, затем путь A | ~3-8K токенов (написание yaml) + вызов скрипта |

Оба пути заканчиваются **одним и тем же опциональным шагом ревью**, на котором агент читает сгенерированный файл и добавляет project-specific заметки, которые YAML не мог охватить.

---

## Путь A: встроенная роль

1. Пользователь выбирает (или агент предлагает) роль из `examples/`:
   `programmer-senior`, `marketing-director`, `creative-hybrid`, `product-manager`, `researcher`, `founder`, `content-creator`, `fiction-writer`.
2. Агент запускает (во время развёртывания, до `finalize.sh`):
   ```bash
   python3 knowledge-base/scripts/kb_populate.py --role <role> --kb-root knowledge-base
   ```
   Или, если cwd агента уже внутри `knowledge-base/`:
   ```bash
   python3 scripts/kb_populate.py --role <role> --kb-root .
   ```
3. (Опционально) Флаг `--create-samples` дополнительно создаёт placeholder-файлы в `raw/_samples/`.
4. Агент **читает** сгенерированный `DATA_PLACEMENT_EXAMPLES.md` и переходит к шагу ревью (ниже).

Этот путь тратит **0 LLM-токенов** на саму генерацию — `kb_populate.py` — это чистый templating.

---

## Путь B: кастомная роль (придуманная на лету)

Когда пользователь описывает роль, которой нет в `examples/`, агент **обязан сначала создать YAML** — до любой генерации.

### B.1. Создать YAML роли

1. Скопировать `templates/role.yml.template` в `knowledge-base/examples/<slug>.yml` (в развёрнутой базе, пока она ещё живёт в `<project>/knowledge-base/`).
2. Агент заполняет плейсхолдеры, **интервьюируя пользователя**:
   - `{{ROLE_TITLE}}` — короткое название
   - `{{ROLE_DESCRIPTION}}` — 2-3 предложения
   - `entities:` — 3-5 записей с `why` и `knowledge_paths`
   - `raw_data_examples:` — 5-10 типичных типов артефактов
   - `ai_assistant_tasks:` — 5-7 задач, в которых ассистент должен быть полезен
   - **`placement_examples:`** — часть, которую потребляет `kb_populate.py`:
     - `intro` — 1-2 параграфа от лица пользователя
     - `by_artifact` — 5-9 конкретных записей об артефактах
     - `quickstart` — 3-5 шагов для первого знакомства
     - `do_not_drop` — 3-5 role-specific исключений

3. Проверить, что файл парсится:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('knowledge-base/examples/<slug>.yml'))"
   ```

### B.2. Затем запустить kb_populate

Как только YAML на диске, workflow идентичен пути A:

```bash
python3 knowledge-base/scripts/kb_populate.py --role <slug> --kb-root knowledge-base
```

> **Почему сначала сохранить YAML, а не генерировать напрямую?** Две причины:
> 1. YAML становится переиспользуемым артефактом — повторный запуск `kb_populate.py` после правок дёшев и детерминирован.
> 2. Пользователь может уточнять роль со временем (добавлять entities, править placement) без повторного обращения к LLM.

---

## Опциональный шаг: AI-ревью

После того как `kb_populate.py` записал файл, агенту **следует** прочитать его и поискать улучшения:

| Цель | Примеры дополнений |
|------|--------------------|
| Project-specific заметки | «Сначала положи README своего highway-clicker — там большая часть контекста» |
| Стек инструментов | «Твой стек — Rust + React, добавь `Cargo.toml` и `package.json` в ранний ingest» |
| Озвученные предпочтения пользователя | «Пользователь сказал, что не выносит шум slack-экспортов — подчеркнуть `review/needs-redaction/`» |
| Заострение quickstart | Выбрать *тот единственный* файл в окружении пользователя, который быстрее всего продемонстрирует ценность |

Агент дописывает секцию `## Project notes` в конец сгенерированного файла (**не** изменять авто-сгенерированные секции — они будут перезаписаны при повторном запуске; только дописывать ниже footer-а).

Этот проход обычно стоит ~1-2K токенов и действительно ценен. Если у пользователя жёсткий бюджет — пропустить и идти дальше.

---

## Опциональный шаг: `raw/_samples/`

Если пользователь хочет примеры форматов (или был передан `--create-samples`):

```bash
python3 knowledge-base/scripts/kb_populate.py --role <role> --create-samples --kb-root knowledge-base
```

Это записывает `raw/_samples/<artifact-slug>.example.md` для каждого артефакта из `placement_examples.by_artifact`. Папка исключается из ingest (имя начинается с `_`).

---

## Когда перегенерировать

| Триггер | Действие |
|---------|----------|
| Пользователь правит `examples/<role>.yml` | Повторно запустить `kb_populate.py` — файл чисто перезаписывается |
| Пользователь хочет другой набор артефактов | Правка YAML → повторный запуск скрипта |
| Команда пользователя `!populate` | Повторный запуск скрипта + AI-ревью |
| Новая роль обнаружена после развёртывания | Создать новый YAML (путь B), затем запустить скрипт |

> ⚠️ Project notes, добавленные агентом в `## Project notes`, выживают только если агент дописал их ниже авто-сгенерированного footer-а. Скрипт перезаписывает всё, что выше.

---

## Точки запуска

| Когда | Действие |
|-------|----------|
| Конец `02_INIT` (deployment) | Сгенерировать первичный `DATA_PLACEMENT_EXAMPLES.md` |
| Команда пользователя `!populate` | Перегенерировать с актуальным состоянием YAML |
| Изменение `kb.config.yml` (новые entities) | Опциональная регенерация при следующей сессии |

---

## Чек-лист для агента

При завершении развёртывания:

- [ ] Определено, подходит ли встроенная роль (путь A) или нужна кастомная (путь B)
- [ ] (Только путь B) Создан `examples/<slug>.yml` из `templates/role.yml.template`, YAML проверен на парсинг
- [ ] Запущен `python3 knowledge-base/scripts/kb_populate.py --role <role> --kb-root knowledge-base`
- [ ] Проверено, что `DATA_PLACEMENT_EXAMPLES.md` записан
- [ ] (Рекомендуется) Прочитан сгенерированный файл и дописана секция `## Project notes` с user-specific советами
- [ ] (Опционально) Повторный запуск с `--create-samples`, если пользователь хочет примеры форматов
- [ ] **Сгенерирован `START_HERE.md`** из `templates/START_HERE.md.template` (параметризовать `{{KB_NAME}}` и `{{PRIMARY_ROLE}}`)
- [ ] **Записан `eval/QUESTIONS.md`** по трём типовым вопросам (обязательный вопрос 6 в `02_INIT.md`); `eval/results/` существует и пуст
- [ ] Запущен `python3 knowledge-base/scripts/kb_doctor.py --root knowledge-base` для подтверждения установки
- [ ] Запущен `bash setup/shell/finalize.sh` — поднимает базу в корень проекта, удаляет `setup/` и пустую `knowledge-base/`
- [ ] Пользователю показано summary на 3-5 строк в чате. **Обязательно включает**:
  - «Сначала прочитай `START_HERE.md`.»
  - «Каждая новая чат-сессия: начинай словами *«Используй AGENTS.md как основную инструкцию»*.»
  - OS-специфичный лаунчер watcher-а (`watcher-start.command` для macOS, `./shell/watcher.sh` для Linux, `watcher-start.bat` для Windows)
- [ ] Операция записана в `log.md` (автоматически, если интеграция настроена)

---

## Интеграция

- **02_INIT:** в финале фазы 1 («Создание структуры») агент переходит к этому модулю
- **03_PIPELINE:** `raw/_samples/` не попадает в pipeline (имя начинается с `_`)
- **05_INDEX:** `raw/_samples/` исключён ignore-паттерном `raw/**`
- **10_LOG:** generation записывается в `log.md` как `populate | DATA_PLACEMENT_EXAMPLES generated`

---

## Будущие улучшения (Фаза 4+)

- [x] `scripts/kb_populate.py` — автоматическая генерация yaml → markdown
- [x] `--create-samples` — placeholder-файлы форматов
- [x] `templates/role.yml.template` — для кастомных ролей
- [ ] Версионирование сгенерированного файла (`generated_at`, `from_template_version`)
- [ ] Автоматическая регенерация при изменении entities в `kb.config.yml`
- [ ] Перевод секций под основной язык базы (использование `language` из конфига)
- [ ] A/B тесты разных формулировок quickstart на основе фидбэка пользователей
