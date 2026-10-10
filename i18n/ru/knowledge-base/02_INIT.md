---
translation_of: knowledge-base/02_INIT.md
source_commit: 6efb2d083c3a372d1bc37a4cd9ab32bd356117b3
source_version: 0.16.0
translated_at: 2026-10-11
translator: ai-assisted
---

# 02 — Инициализация базы знаний

> Модуль описывает фазу уточнения (вопросы пользователю), создание структуры проекта и — после модулей 03–18 — завершение: doctor, `finalize.sh`, git hook.
>
> **Рабочий каталог:** корень проекта (папка с `setup/` и `.venv/`), с активным venv из `01_PREREQUISITES.md`. Пока в фазе 1 не скопирован движок, запускайте скрипты набора как `python3 setup/scripts/…`; затем — как `python3 knowledge-base/scripts/…` с `--root knowledge-base` / `--kb-root knowledge-base` (или выполните `cd knowledge-base` и уберите флаг).
> **Эталонные шаблоны:** `setup/templates/kb.config.yml.template`, `KNOWLEDGE_STRUCTURE.md.template`, `DATA_PLACEMENT_EXAMPLES.md.template`, `START_HERE.md.template`, `.gitignore.template`, `.gitattributes.template`. Агент копирует их в корень развёрнутой базы и подставляет параметры.
> **Язык:** пишите тексты для владельца (START_HERE.md, описания KNOWLEDGE_STRUCTURE.md, заметки проекта, вопросы eval) на языке владельца (`knowledge_base.language`). Имена файлов и папок, ключи frontmatter, конфигурации и `!commands` остаются на английском.
> **Помощник развёртывания:** `setup/shell/finalize.sh` запускается **в самом конце** (после кода выхода 0 от `kb_doctor`) и переносит содержимое `knowledge-base/` в корень проекта — см. «Завершение развёртывания».

---

## Схема развёртывания (что где окажется)

Пользователь копирует исходную папку `knowledge-base/` (модули `00_OVERVIEW.md` … `18_HEAL.md`, `README.md`, `scripts/`, `shell/`, `templates/`, `examples/`) в корень своего проекта, **переименовав в `setup/`**, чтобы отделить её от базы, которую строит агент. Агент сначала читает `setup/00_OVERVIEW.md`, затем проходит модули и **строит базу внутри `<project-root>/knowledge-base/`**, оставляя venv из `01` в корне проекта. В конце `finalize.sh` поднимает всё в корень проекта, заполняет `kb-docs/`, поднимает launchers для двойного клика и удаляет `setup/` и пустую `knowledge-base/` («Завершение развёртывания» ниже). `00_OVERVIEW.md` показывает оба расположения (до и после finalize).

Если пользователь хочет оставить базу в подпапке, пропустите finalize: в `knowledge-base/` уже есть `kb-docs/` и всё остальное. Тогда создайте venv внутри неё (`01_PREREQUISITES.md`, «База остаётся в подпапке»). Рекомендуемый путь по умолчанию — **плоско в корне проекта после финализации**.

---

## Фаза 0: уточнение намерений

Перед созданием базы AI-агент **обязан** задать вопросы. Если ответы очевидны, предложите разумные значения по умолчанию.

### Если пользователь НЕ указал роль

Когда пользователь говорит «разверни базу», не называя роль, агент:

1. Перечисляет **каждый** `setup/examples/*.yml` — его `role:` и суть `description:` — как нумерованное меню, добавляя последним пунктом «Своя роль — опишите её, и я подготовлю конфигурацию»:
   ```
   Доступные шаблоны ролей:
    1. 📊 Директор по маркетингу — стратегия, бренд, аудитория, кампании
    2. 💻 Senior Software Engineer — архитектура, код, отладка, технологии
    3. 🎯 Продакт-менеджер — приоритизация, метрики, исследования пользователей
   …
   17. Своя роль — опишите её, и я подготовлю конфигурацию
   ```
   Не представляйте роль как «отсутствующую в шаблонах», если для неё есть файл.
2. Пользователь выбирает номер или описывает свою роль

### Если пользователь указал роль

AI-агент находит подходящий шаблон в `setup/examples/` и переходит к **адаптации** (ниже). Нет совпадения → своя роль.

### Адаптация после выбора роли

Выбрав шаблон, агент **не просто копирует yml**, а задаёт уточняющие вопросы:

1. **Посмотрите сущности шаблона — всё подходит, или что-то лишнее/не хватает?**
   - Покажите список сущностей с описаниями
   - Пользователь может убрать ненужные или добавить свои

2. **Какие конкретные инструменты/технологии/подходы вы используете?**
   - Программисту: «Какой стек? Rust, TypeScript, Python?»
   - Музыканту: «Какие DAW/инструменты? Suno, стемы через Demucs?»
   - Маркетологу: «Какие каналы и инструменты аналитики?»

3. **Есть ли что-то особенное в вашем подходе?**
   - «Я не читаю ноты, но делаю музыку с AI»
   - «Я работаю один, без команды»
   - «У меня есть побочный игровой проект»

4. **Хотите что-то добавить или оставить как есть?**
   - «Как есть» → всё равно пройдите слепые зоны и четыре эскиза структуры; не переходите сразу к созданию папок
   - Есть дополнения → AI вносит их в конфигурацию, затем продолжает

### Слепые зоны (до любой структуры)

**Пока не предлагайте папки `knowledge/`.** Люди с этой ролью обычно забывают то, из-за чего позже приходится перестраивать расположение. Сначала интервью.

1. Выполните `python3 setup/scripts/kb_structure.py --role <slug> --blind-spots`. Если в YAML есть `blind_spots:`, используйте этот список; иначе скрипт выводит значения по умолчанию из сущностей и артефактов. **Своя роль:** сначала совместно с пользователем создайте `knowledge-base/examples/<slug>.yml` из `setup/templates/role.yml.template` (заполните и `blind_spots:`), затем здесь и на следующем шаге передавайте `--from knowledge-base/examples/<slug>.yml` вместо `--role <slug>`.
2. Спрашивайте **в напечатанном порядке**. Первые пункты меняют расположение `knowledge/` (где хранить заброшенную работу, заслуживают ли артефакты отдельных папок, как искать старое, что остаётся неизменяемым). Пробелы содержания идут после.
3. Запишите ответы в рабочие заметки. Они станут основой четырёх эскизов.

Не изобретайте пятую анкету о папках. Следующий шаг — эскизы, а не дополнительные поля формы.

### Четыре варианта структуры (реагировать, не выбирать номер)

1. Выполните `python3 setup/scripts/kb_structure.py --role <slug> --write --kb-root knowledge-base` (создаёт `knowledge-base/`, если её ещё нет).
2. Команда записывает `knowledge-base/interactions/init/STRUCTURE_VARIANTS.md` — четыре эскиза из одного YAML роли: **по проектам / по типам артефактов / по времени / по решениям**. Покажите их в чате. Владелец **реагирует** (нравится, не нравится, «это плюс датированные решения», «гибрид»), а не выбирает 1–4 из формы.
3. Эскизов четыре, не десять. Материал — YAML ролей из `examples/` и ответы о слепых зонах.
4. **Гибрид по умолчанию:** если реакция «всего понемногу» или «как есть», используйте стандартное дерево из 12 папок в `KNOWLEDGE_STRUCTURE.md.template`. `kb_ingest.py --init-dirs` всё равно создаёт стандартные папки как пустые полки совместимости; добавьте папки, которых требует реакция.

### Обязательные вопросы (после реакции на структуру)

1. **Какие сырые данные будут загружаться?**
   - Документы, презентации, чаты, код, аудио, видео, заметки, статьи

2. **Что запрещено индексировать?**
   - Секреты, токены, чужие приватные данные, медицинские/юридические данные

3. **Нужен ли личный контекст?**
   - Стиль мышления, творческие интересы, профессиональная история, предпочтения

4. **Есть ли Git?**
   - Если да — после finalize установите post-commit hook через `bash shell/install-hooks.sh` («Завершение развёртывания», шаг 5)

5. **Какой агент основной?** По ответу задайте `index.primary_agent` и `index.window_profile` в `kb.config.yml`:
   - **Codex** → `primary_agent: codex`, `window_profile: 400k`
   - **Cursor** → `primary_agent: cursor`, `window_profile: 256k`
   - **Claude Code** → `primary_agent: claude-code`; `window_profile: 1m`, если используется модель с окном 1M, иначе `256k`. Тогда `finalize.sh` без вопросов записывает однострочный `CLAUDE.md` (`@AGENTS.md`) — Claude Code сам не читает `AGENTS.md`.

6. **Какие три вопроса вы будете задавать этой базе чаще всего?** Создайте `eval/QUESTIONS.md` из `templates/eval/QUESTIONS.md.template`. Для каждого вопроса запишите текст, термины, которые ответ обязан упомянуть, и отвергнутый вариант, который он НЕ должен предлагать. Страница, на которую ответ должен сослаться, обычно ещё не существует: укажите планируемый путь (например, `knowledge/decisions/…`) или `TBD` и заполните после создания страницы при начальном наполнении. Создайте пустой `eval/results/`. Это пробы «до/после» для будущих правок инструкций — не индексируются.

---

## Фаза 1: копирование движка и создание структуры

После слепых зон и реакции владельца на четыре эскиза скопируйте движок в базу — один раз, без изменений — и создайте папки.

### Копирование файлов движка

```bash
mkdir -p knowledge-base/kb-docs
cp -R setup/scripts setup/shell setup/templates setup/examples knowledge-base/
rm -rf knowledge-base/scripts/tests                  # engine tests, not part of a base
find knowledge-base -name __pycache__ -type d -prune -exec rm -rf {} +
cp setup/[0-9][0-9]_*.md setup/README.md knowledge-base/kb-docs/
cp setup/templates/requirements*.txt knowledge-base/
cp setup/templates/.gitignore.template knowledge-base/.gitignore
cp setup/templates/.gitattributes.template knowledge-base/.gitattributes
```

(PowerShell: то же через `Copy-Item -Recurse` / `Remove-Item -Recurse`.)

- `kb-docs/` содержит модули инструкций, на которые ссылаются развёрнутый `AGENTS.md` и сообщения скриптов (`kb-docs/NN_NAME.md`); `setup/` в конце исчезает.
- `.gitignore` по умолчанию исключает из git приватные материалы: `raw/`, `assets/`, `processed/`, `review/`, `interactions/` (а также состояние конкретной машины). Чтобы версионировать одну из папок, удалите её строку — и никогда не отправляйте такой репозиторий в публичное место.
- `.gitattributes` закрепляет окончания строк (LF для shell-скриптов и hook, CRLF для `.bat`), чтобы checkout в Windows не ломал обёртки.
- Создайте оба файла в `knowledge-base/`, даже если в корне проекта уже есть свои: шаблоны (`/raw/`, `shell/hooks/*`) отсчитываются от папки файла, поэтому корневые копии не покрывают `knowledge-base/raw/`. Затем `finalize.sh` добавляет недостающие правила в начало корневых файлов, сохраняя приоритет собственных правил проекта (ничего не удаляется; общее `* text=auto` не добавляется в существующий `.gitattributes`).

### Создание папок

```bash
python3 knowledge-base/scripts/kb_ingest.py --init-dirs --root knowledge-base
```

Дерево ниже — **гибрид по умолчанию**. Если реакция выбрала одну ось (проекты / артефакты / время / решения), следуйте тому эскизу, сохраняя неиспользуемые стандартные папки только как пустые полки.

```text
knowledge-base/
├── AGENTS.md                   # Инструкции AI-агента (из шаблона 06)
├── KNOWLEDGE_STRUCTURE.md      # Описание каждой папки и правил
├── DATA_PLACEMENT_EXAMPLES.md  # «Есть PDF → положи сюда»
├── START_HERE.md               # Точка входа владельца (пишется при завершении)
├── kb.config.yml               # Роль, сущности, правила
├── repomix.config.json         # Конфигурация индексатора
├── requirements*.txt           # Зависимости Python (см. 01)
├── .gitignore, .gitattributes
├── kb-docs/                    # Модули инструкций 00 … 18 + README.md
├── shell/                      # Обёртки Linux / CLI, git hook, launchers
│   ├── reindex.sh, watcher.sh, lint.sh, doctor.sh, export.sh, import.sh
│   ├── install-hooks.sh, hooks/post-commit, _kbpy.sh
│   ├── reindex.command, watcher-start.command, watcher-stop.command, export.command, import.command
│   └── reindex.bat, watcher-start.bat, export.bat, import.bat   # поднимаются в корень через finalize.sh
│
├── scripts/                    # Python-конвейер (kb_ingest.py, kb_lint.py, …)
│
├── raw/                        # Сырые данные (НЕ индексируются); непонятное → raw/unsorted/
│   └── documents/, work/, chats/, media/, personal-context/, reference/   # в каждой есть unsorted/
├── processed/                  # Конвертированные артефакты (НЕ индексируются)
│   └── markdown/, transcripts/, ocr/, tables/, extracted-metadata/, nlp-meta/
│
├── knowledge/                  # ✅ Чистые знания → ИНДЕКСИРУЮТСЯ
│   ├── profile/                # Профиль, экспертиза, сильные стороны
│   ├── principles/             # Принципы работы, критерии качества
│   ├── domain/                 # Предметная область, рынок, знания (≈ сеть знаний о мире)
│   ├── projects/               # Проекты, кейсы, результаты
│   ├── decisions/              # Решения: что, почему, результат
│   ├── voice/                  # Стиль речи, письма, объяснения
│   ├── timelines/              # Хронология, этапы развития
│   ├── playbooks/              # Повторяемые процессы (≈ сеть опыта)
│   ├── insights/               # Синтезированные выводы более высокого уровня
│   ├── opinions/               # Субъективные оценки с уверенностью и датой
│   ├── routing/                # Таблицы маршрутизации для масштабирования навигации
│   ├── open-questions/         # Вопросы, на которые база не отвечает
│   └── _archive/               # Устаревшие страницы с пометкой (никогда не stale)
│
├── assets/                     # Бинарные оригиналы (НЕ индексируются)
│   └── documents/, presentations/, media/, images/, archives/
├── assets-index/               # ✅ MD-описания файлов → ИНДЕКСИРУЮТСЯ
│   └── documents.md, presentations.md, media.md, images.md, archives.md
│
├── review/                     # Очереди проверки (НЕ индексируются)
│   ├── needs-classification/
│   ├── needs-ai-decision/
│   ├── needs-redaction/
│   ├── needs-merge/            # Пакеты слияния между базами (см. 16_MERGE.md)
│   ├── needs-heal/             # Догоняющее исправление после обновления (см. 18_HEAL.md)
│   └── excluded-sensitive/
│
├── interactions/               # Цикл обратной связи (напрямую НЕ индексируется)
│   ├── sessions/               # Папки диалогов с временными метками
│   ├── insights/               # Извлечённые закономерности
│   ├── meta-reviews/           # Периодический анализ
│   ├── init/                   # STRUCTURE_VARIANTS.md (E2) — не индексируется
│   └── quiz/                   # Листы ответов !quiz — не индексируются
│
├── eval/                       # Ручные пробы инструкций (НЕ индексируются)
│   ├── QUESTIONS.md            # Три типовых вопроса (02_INIT Q6)
│   └── results/                # Ответы до/после — сохранять, не добавлять в gitignore
│
├── sync/                       # Импорт/экспорт между базами (НЕ индексируется; 16_MERGE.md)
│   └── inbox/, outbox/, applied/, backups/, reports/
│
└── .repomix/                   # Пакеты индекса, записывает kb_reindex.py (см. 05_INDEX.md)
```

У базы нет собственного `README.md`: точка входа владельца — `START_HERE.md`, а README проекта в корне остаётся README проекта.

---

## Фаза 2: `kb.config.yml`

Скопируйте `setup/templates/kb.config.yml.template` в `knowledge-base/kb.config.yml` и редактируйте **только значения** — заголовок и комментарии разделов называют модуль `kb-docs/`, документирующий каждый ключ; позже скрипты редактируют файл построчно. Плейсхолдеры:

- `{{KB_INSTRUCTIONS_VERSION}}` — вывод `python3 setup/scripts/kb_common.py --version` (в наборе нет `VERSION`)
- `{{DEPLOYED_AT}}` — сегодня, дата ISO
- `{{KB_NAME}}`, `{{PRIMARY_LANGUAGE}}`, `{{PRIMARY_ROLE}}` — из интервью; `{{PRIMARY_ROLE}}` — название из `role:` (или имя файла) выбранного `examples/<slug>.yml`: `!populate` находит по нему YAML
- `{{SPACY_MODEL}}` — модель spaCy для `knowledge_base.language`, например `ru_core_news_md` или `en_core_web_md` — установленная в `01_PREREQUISITES.md` (см. `12_NLP_PREPROCESS.md`)
- `{{KB_LABEL}}` — ниже
- `entities: {}` — выполните `python3 knowledge-base/scripts/kb_populate.py --entities-from <slug> --kb-root knowledge-base` (копирует mapping `entities:` роли в конфигурацию, пока она пустая; `--dry-run` показывает план; своя роль в `knowledge-base/examples/` тоже находится), затем удалите не подтверждённые владельцем сущности и добавьте запрошенные

### Пример значений для гибридной роли (программист + хобби)

Показаны только изменяемые ключи; настоящий файл сохраняет все разделы и комментарии шаблона.

```yaml
knowledge_base:
  name: "personal-professional-kb"
  mode: "default"            # default | super — the only place the mode lives
  language: "en"
  index_policy: "clean-knowledge-only"

  roles:
    primary: "Senior Software Engineer"
    hobbies:
      - "AI-assisted music production"
      - "Indie game development"

privacy:
  raw_indexing_allowed: false
  review_indexing_allowed: false
  interactions_indexing_allowed: false
  external_ai_allowed: false
  require_redaction_for_chats: true

language_policy:
  primary: "en"
  extraction_rule: "extract in primary language; preserve original terms / brand names verbatim"
  metadata_language: "en"  # for slugs, filenames, frontmatter keys

entities:
  # copied from examples/<slug>.yml, trimmed to what the owner confirmed

sync:
  # Only matters if the user runs this base on more than one machine.
  label: "work-laptop"          # {{KB_LABEL}} — how this base identifies itself
  export:
    sections: ["knowledge", "assets-index", "interactions", "meta", "config", "log"]
    with_assets: false
  import:
    strategy: "safe"
    similarity_threshold: 0.85
    backup: true
    move_applied: true
```

> **`{{KB_LABEL}}`** — спрашивайте только если пользователь работает с нескольких машин (например, студийного и рабочего ноутбука). Значение должно быть **разным в каждом развёртывании**: оно записывается на каждую импортированную страницу как `merged_from:` и позволяет проследить слияние. Для одной машины задайте то же значение, что у `knowledge_base.name`. См. `16_MERGE.md`.

---

## Правила исключения

НЕ добавляйте в `knowledge/` и НЕ индексируйте:

- пароли, токены, API-ключи, seed-фразы, приватные ключи
- банковские реквизиты, паспортные данные, чужие документы
- чужие приватные чаты без разрешения на обработку
- чужие медицинские данные
- личные конфликты, сплетни, интимный контекст
- необезличенные исходные экспорты чатов

Материал полезен, но чувствителен → `review/needs-redaction/`.
Его нельзя безопасно использовать → `review/excluded-sensitive/`.

`kb_ingest.py` сам выполняет первичную сортировку: пока `privacy.require_redaction_for_chats` равен true (по умолчанию), файлы из папок `privacy.redact_categories` (по умолчанию `raw/chats/`, `raw/personal-context/`) направляются в `review/needs-redaction/`; при включённом `privacy.secret_scan` (по умолчанию включён) туда же идут файлы с признаками токенов, паролей или приватных ключей (см. `03_PIPELINE.md`).

---

## Метаданные frontmatter

Каждый файл в `knowledge/` должен начинаться YAML-блоком между `---`:

```markdown
---
source: "assets/documents/2026-05-06__q2-strategy.pdf"
extracted_at: 2026-05-06
last_verified: 2026-05-06
confidence: high
importance: 6                # 1-10, set by the agent at extraction (11_PROVENANCE.md)
lifecycle: evolving          # permanent | evolving | temporal
tags: [strategy, growth, q2-2026]
supersedes: null
---

# Q2 growth strategy

...content...
```

`source`, `extracted_at`, `tags` и `lifecycle` обязательны (`kb_lint.py` сообщает о странице без них). Это позволяет AI-агенту:

- видеть, **откуда** пришли знания, и проверять источник
- оценивать **свежесть** (когда извлечены, когда проверены, устаревают ли вообще)
- фильтровать по тегам
- понимать цепочку замены (`supersedes`)

---

## Фаза 3: модули 03–18

Продолжайте `03_PIPELINE.md` … `18_HEAL.md` **по порядку**, настраивая всё необходимое для каждого. Не переходите к завершению до модуля 18.

Целиком прочитайте модули, настраивающие базу сейчас: 03, 05, 06, 09, 10, 11, 12, 13, 14. Остальные описывают работу, запускаемую позже из `kb-docs/`, и их значения по умолчанию не требуют шагов развёртывания. Прочитайте только начальное резюме, а весь модуль — когда владелец хочет выполнить эту работу сейчас или запускается соответствующая команда:

- 04 — `!review`
- 07 — команды, режимы, `!save` (`AGENTS.md` уже содержит таблицу команд)
- 08 — использование базы из других проектов
- 15 — аудио, видео, сканы, архивы (прочитайте целиком, если владелец назвал такие файлы в фазе 0)
- 16 — несколько машин (`{{KB_LABEL}}` задан в фазе 2)
- 17 — `!refactor`
- 18 — `!heal`

Модулю 14 (начальное наполнение) нужны в следующем порядке:

1. YAML роли на диске. `knowledge-base/examples/<slug>.yml` своей роли создаётся в фазе 0 (создайте сейчас, если ещё отсутствует); скрипты базы находят его через `--role <slug>`.
2. `interactions/init/STRUCTURE_VARIANTS.md` — если нет, выполните `python3 knowledge-base/scripts/kb_structure.py --role <slug> --write --kb-root knowledge-base` (детерминированно; без LLM).
3. `python3 knowledge-base/scripts/kb_populate.py --role <slug> --kb-root knowledge-base` — детерминированная генерация `DATA_PLACEMENT_EXAMPLES.md`, без токенов LLM. Если YAML роли не содержит `placement_examples:`, `kb_populate.py` завершается с ошибкой; добавьте раздел в YAML и повторите.
4. (Рекомендуется) Прочитайте созданный файл и добавьте раздел `## Project notes` с советами для проекта, которые не помещаются в YAML (~1-2K токенов).

---

## Завершение развёртывания (после модуля 18)

1. **Создайте `START_HERE.md`**, скопировав `templates/START_HERE.md.template` и подставив `{{KB_NAME}}` и `{{PRIMARY_ROLE}}`. Это **первый файл**, который читает пользователь после развёртывания.
2. **Создайте `eval/QUESTIONS.md`** из `templates/eval/QUESTIONS.md.template` по трём типовым вопросам обязательного Q6. Оставьте `eval/results/` пустой.
3. **Запустите doctor:** `python3 knowledge-base/scripts/kb_doctor.py --root knowledge-base`. Проверка **пройдена при коде выхода 0** — предупреждения допустимы (прочитайте и исправьте недорогое), ошибки — нет. Исправляйте и повторяйте до кода 0.
4. **Выполните `bash setup/shell/finalize.sh`** (Windows: из Git Bash) — копию из набора; собственный `shell/finalize.sh` базы отказывается запускаться, поскольку finalize удаляет содержащую его папку. Скрипт:
   1. Проверяет развёрнутую базу (`AGENTS.md`, `kb.config.yml`, `scripts/kb_ingest.py`) и отказывается (код 1, ничего не изменено), если элемент `knowledge-base/` уже существует в корне проекта — кроме режима `--force`, который сначала переносит эти корневые элементы в `.kb-finalize-backup/<timestamp>/` (ничего не удаляется)
   2. **Поднимает** все элементы `knowledge-base/` в корень проекта, кроме `.git` и virtualenv: их никогда не перемещает и не удаляет (`knowledge-base/.venv` остаётся с предупреждением — venv должен быть в корне проекта, см. 01). Существующий в корне `.gitignore` / `.gitattributes` не считается конфликтом: недостающие правила базы добавляются в начало (правила проекта сохраняют приоритет)
   3. Копирует модули инструкций из `setup/` в `kb-docs/` (существующие файлы сохраняются)
   4. Удаляет пустую `knowledge-base/`, поднимает launchers `*.command` / `*.bat` из `shell/` в корень проекта, обновляет executable-биты
   5. Записывает однострочный `CLAUDE.md` (`@AGENTS.md`), если `index.primary_agent` равен `claude-code` или указан `--claude-md`; иначе спрашивает (нет ответа = нет; `--no-claude-md` пропускает вопрос)
   6. Последней удаляет `setup/` (`--keep-setup` сохраняет её)

   Коды выхода: `0` завершено · `1` отказ до изменений · `2` остановка в процессе. При `2` запуск записан в `.kb-finalize.journal`: устраните указанную проблему (права, место на диске…) и выполните `bash setup/shell/finalize.sh --resume`, чтобы продолжить с параметрами первого запуска (повреждённый журнал отклоняется: тогда проверьте уже перемещённое, удалите журнал и завершите вручную или повторите запуск). `--dry-run` печатает план.
   Если `finalize.sh` отказывается, НЕ добавляйте `--force` без согласия пользователя — сначала выясните причину.
5. **Git (обязательный Q4 = да):** из корня проекта (теперь плоского) выполните `bash shell/install-hooks.sh`. Команда устанавливает `shell/hooks/post-commit`, который фоново обновляет пакеты индекса и `STATUS.md` после каждого коммита (подробности: `kb-docs/13_AUTORUN.md`). Уже существующий отличающийся hook (владельца или изменённая копия нашего) переносится в `post-commit.backup-<timestamp>`. Чтобы сохранить команды владельца, восстановите его hook и вызывайте из него `shell/hooks/post-commit`.
6. Покажите пользователю в чате памятку на 3–5 строк, которая:
   - **Явно сообщает**: *«Сначала прочитайте `START_HERE.md`, а каждый новый чат начинайте словами: “Используй AGENTS.md как основную инструкцию”»* — на языке владельца (пользователи Claude Code с `CLAUDE.md` могут пропустить фразу)
   - Перечисляет самые полезные действия быстрого старта
   - Указывает launcher watcher для ОС пользователя
