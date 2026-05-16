---
translation_of: quick-start/INIT_GUIDE.md
source_commit: 63ec5652913793e80cf7a899c691d34d88285f8a
source_version: 0.9.3
translated_at: 2026-05-17
translator: human
---

# Repomix — Универсальный гайд инициализации для AI-агента

> **Назначение:** Этот документ — инструкция для AI-агента. Прочитай его и выполни шаги для быстрой интеграции Repomix в любой проект пользователя.
>
> **Что делает Repomix:** пакует кодовую базу в один XML/Markdown файл, оптимизированный для LLM. Это позволяет агенту получить полную карту проекта за один `view_file` вместо сканирования сотен файлов по одному, экономя токены и время.

---

## Фаза 0: Предварительный анализ

Перед инициализацией **задай пользователю уточняющие вопросы** (если ответы не очевидны из структуры проекта):

### Обязательные вопросы:
1. **Тип проекта?** (frontend / backend / fullstack / monorepo / non-code knowledge base)
2. **Стек?** (языки, фреймворки — определяет include-паттерны)
3. **Есть ли Git?** (определяет git hook vs standalone скрипт)
4. **Есть ли легаси/архивные папки**, которые нужно исключить из основного индекса?
5. **Приоритет: экономия токенов или полнота информации?**
   - Максимальная экономия → `compress: true`, `removeComments: true`, `removeEmptyLines: true`
   - Полнота (нужны комментарии для понимания) → `compress: false`, `removeComments: false`

### Автоматический анализ (выполни сам):
```bash
# Структура проекта
find . -maxdepth 3 -type d ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/target/*' ! -path '*/dist/*' ! -path '*/__pycache__/*' ! -path '*/venv/*' | sort

# Количество файлов по типам
find . -type f ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/target/*' ! -path '*/dist/*' | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -20

# Наличие Git
git rev-parse --is-inside-work-tree 2>/dev/null && echo "GIT: YES" || echo "GIT: NO"

# Наличие husky / git hooks
ls -la .husky/ 2>/dev/null || ls -la .git/hooks/ 2>/dev/null

# Наличие AGENTS.md
test -f AGENTS.md && echo "AGENTS.md: EXISTS" || echo "AGENTS.md: MISSING"

# Общий размер исходников (без бинарных)
find . -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.jsx' -o -name '*.py' -o -name '*.rs' -o -name '*.go' -o -name '*.java' -o -name '*.kt' -o -name '*.swift' -o -name '*.css' -o -name '*.html' -o -name '*.md' -o -name '*.sql' -o -name '*.sh' -o -name '*.yml' -o -name '*.yaml' -o -name '*.toml' -o -name '*.json' \) ! -path '*/node_modules/*' ! -path '*/.git/*' ! -path '*/target/*' ! -path '*/dist/*' | wc -l
```

---

## Фаза 1: Установка

### Проверить наличие:
```bash
command -v repomix && repomix --version
```

### Установить глобально (если отсутствует):
```bash
npm install -g repomix
```

> Альтернатива без глобальной установки: `npx repomix` (каждый раз скачивает).

---

## Фаза 2: Конфигурация

Создай `repomix.config.json` в корне проекта, используя шаблон ниже. Адаптируй `include` и `ignore.customPatterns` под конкретный стек.

### Базовый шаблон:
```json
{
  "$schema": "https://repomix.com/schemas/latest/schema.json",
  "output": {
    "filePath": ".repomix/output.xml",
    "style": "xml",
    "compress": true,
    "removeComments": true,
    "removeEmptyLines": true,
    "showLineNumbers": false,
    "fileSummary": true,
    "directoryStructure": true,
    "topFilesLength": 10,
    "headerText": "<PROJECT_NAME> — <SHORT_DESCRIPTION>. See AGENTS.md for architecture.",
    "git": {
      "sortByChanges": true,
      "sortByChangesMaxCommits": 50
    }
  },
  "include": [],
  "ignore": {
    "useGitignore": true,
    "useDefaultPatterns": true,
    "customPatterns": []
  },
  "security": {
    "enableSecurityCheck": true
  },
  "tokenCount": {
    "encoding": "o200k_base"
  }
}
```

### Include-паттерны по стеку:

#### Frontend (React / Vue / Angular / Svelte)
```json
"include": [
  "src/**/*.ts", "src/**/*.tsx", "src/**/*.js", "src/**/*.jsx",
  "src/**/*.vue", "src/**/*.svelte",
  "src/**/*.css", "src/**/*.scss", "src/**/*.less",
  "*.json", "*.html", "*.md",
  "vite.config.*", "next.config.*", "nuxt.config.*",
  "tsconfig*.json", "tailwind.config.*"
]
```

#### Backend Node.js / Bun / Deno
```json
"include": [
  "src/**/*.ts", "src/**/*.js", "src/**/*.mts",
  "*.json", "*.md", "*.yml", "*.yaml",
  "Dockerfile", "docker-compose*.yml",
  "prisma/**/*.prisma", "drizzle/**/*.ts"
]
```

#### Backend Rust
```json
"include": [
  "**/*.rs", "**/*.toml", "**/*.sql",
  "*.md", "Dockerfile",
  "migrations/**/*.sql"
]
```

#### Backend Python (Django / FastAPI / Flask)
```json
"include": [
  "**/*.py", "**/*.pyi",
  "*.md", "*.yml", "*.yaml", "*.toml", "*.cfg", "*.ini",
  "requirements*.txt", "pyproject.toml", "Pipfile",
  "Dockerfile", "docker-compose*.yml",
  "alembic/**/*.py", "migrations/**/*.py"
]
```

#### Backend Go
```json
"include": [
  "**/*.go", "go.mod", "go.sum",
  "**/*.sql", "*.md", "*.yml", "*.yaml",
  "Dockerfile", "Makefile"
]
```

#### Fullstack / Monorepo
Комбинируй паттерны из нескольких стеков. Рекомендуй пользователю исключить legacy/архивные папки.

#### Non-code Knowledge Base (маркетинг, стратегия, документация)
```json
"include": [
  "**/*.md", "**/*.txt", "**/*.csv", "**/*.json", "**/*.yml", "**/*.yaml"
]
```
> Бинарные форматы (docx, pdf, pptx, изображения, видео) Repomix НЕ парсит. Конвертируй их в Markdown перед индексацией — см. раздел «Knowledge Base проекты» ниже.

### Универсальные ignore-паттерны (добавь всегда):
```json
"customPatterns": [
  "**/node_modules/**", "**/target/**", "**/dist/**",
  "**/__pycache__/**", "**/venv/**", "**/.venv/**",
  "**/coverage/**", "**/test-results/**",
  "**/.git/**", "**/.idea/**", "**/.vscode/**",
  "**/.proxyai/**", "**/.qoder/**", "**/.kiro/**",

  "pnpm-lock.yaml", "package-lock.json", "yarn.lock",
  "Cargo.lock", "bun.lockb", "poetry.lock", "Pipfile.lock",

  "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp",
  "**/*.gif", "**/*.svg", "**/*.ico",
  "**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.eot",
  "**/*.mp3", "**/*.wav", "**/*.mp4", "**/*.webm",
  "**/*.zip", "**/*.tar.gz", "**/*.rar",
  "**/*.pdf", "**/*.docx", "**/*.pptx", "**/*.xlsx",

  ".repomix/**"
]
```

---

## Фаза 3: Инфраструктура

### Создать выходную папку:
```bash
mkdir -p .repomix
```

### Добавить в .gitignore (если Git есть):
```
# Repomix (AI context index, regenerated locally)
.repomix/
```

---

## Фаза 4: Первая генерация и оценка

```bash
repomix
```

Проанализируй вывод:
- **Total Files** — сколько файлов попало в индекс
- **Total Tokens** — бюджет токенов (ориентиры ниже)
- **Security** — если обнаружены секреты, предупреди пользователя

### Ориентиры по размеру:
| Токены | Оценка | Действие |
|--------|--------|----------|
| < 100K | Отлично | Без изменений |
| 100K–500K | Нормально | Оптимизации опциональны |
| 500K–1M | Много | Рекомендуй включить `compress`, убрать docs/tests |
| > 1M | Слишком много | Разбей на профили по подсистемам |

### Если индекс слишком большой — стратегии уменьшения:
1. **Включить compress** (Tree-sitter): снижает на 50-70%
2. **removeComments**: ещё -10-20%
3. **removeEmptyLines**: ещё -5-10%
4. **Исключить тесты**: `"**/*.test.*"`, `"**/*.spec.*"`, `"**/tests/**"`, `"**/__tests__/**"`
5. **Исключить docs**: `"docs/**"` если документация объёмная
6. **Разбить на профили** (см. Фаза 6)

---

## Фаза 5: Автообновление

### Вариант A: Git-проект с Husky

Создай `.husky/post-commit`:
```bash
#!/bin/sh

# Regenerate Repomix context index (background, non-blocking)
if command -v repomix > /dev/null 2>&1; then
  echo "📦 Repomix: updating context index..."
  repomix --quiet 2>/dev/null &
fi
```

```bash
chmod +x .husky/post-commit
```

> Если `.husky/post-commit` уже существует — добавь блок repomix в конец файла, не заменяй существующие хуки.

### Вариант B: Git-проект без Husky

Создай `.git/hooks/post-commit`:
```bash
#!/bin/sh
if command -v repomix > /dev/null 2>&1; then
  repomix --quiet 2>/dev/null &
fi
```

```bash
chmod +x .git/hooks/post-commit
```

### Вариант C: Проект без Git

Создай скрипт переиндексации в корне проекта:

**Linux/macOS** — `reindex.sh`:
```bash
#!/bin/bash
echo "📦 Regenerating Repomix index..."
cd "$(dirname "$0")"
if command -v repomix > /dev/null 2>&1; then
  repomix
  echo "✅ Index updated: .repomix/output.xml"
else
  echo "❌ Repomix not found. Install: npm install -g repomix"
  exit 1
fi
```

**Windows** — `reindex.bat`:
```batch
@echo off
echo 📦 Regenerating Repomix index...
cd /d "%~dp0"
where repomix >nul 2>nul
if %errorlevel% equ 0 (
    repomix
    echo ✅ Index updated: .repomix\output.xml
) else (
    echo ❌ Repomix not found. Install: npm install -g repomix
    exit /b 1
)
```

```bash
chmod +x reindex.sh  # Linux/macOS only
```

---

## Фаза 6: Профили (опционально)

Для крупных проектов — создай отдельные конфиги для подсистем:

```bash
# Только бэкенд
repomix --include "server/**" -o .repomix/backend.xml

# Только фронтенд
repomix --include "frontend/**" -o .repomix/frontend.xml

# Только инфраструктура
repomix --include "start/**" --include "configs/**" --include "Dockerfile" --include "docker-compose*" -o .repomix/infra.xml
```

Агент выбирает нужный профиль в зависимости от задачи.

---

## Фаза 7: Обновление AGENTS.md

Добавь в AGENTS.md проекта секцию (адаптируй под конкретный проект):

```markdown
## Context Engineering: Repomix

### Project Context Index
- **File:** `.repomix/output.xml` — compressed, token-optimized snapshot of the codebase (~XXXK tokens)
- **Config:** `repomix.config.json` — include/exclude patterns, compression settings
- **Auto-update:** Regenerated on every `git commit` via post-commit hook
- **Manual update:** Run `repomix` in project root

### When to Use the Index
- **DO read `.repomix/output.xml`** before large tasks, architecture decisions, or when you need a full project overview
- **DO NOT** rely on it for precise line-level editing — always read specific files directly before modifying them
- The index is compressed (Tree-sitter structural extraction), so it preserves code semantics but not formatting

### What's Included
- <list included directories/patterns>

### What's Excluded
- <list excluded directories and why>
```

---

## Чеклист инициализации (быстрая справка)

```
[ ] repomix установлен глобально (npm install -g repomix)
[ ] repomix.config.json создан в корне с адаптированными include/ignore
[ ] .repomix/ добавлена в .gitignore
[ ] Первая генерация выполнена, размер оценён
[ ] Автообновление настроено (git hook / скрипт)
[ ] AGENTS.md обновлён секцией Context Engineering
```

---

## Knowledge Base проекты (не-код)

Repomix работает только с **текстовыми** форматами. Для проектов, содержащих бинарные документы (docx, pdf, pptx, изображения, видео), используй стратегию **"Markdown-First Knowledge Base"**:

### Структура:
```
project/
├── AGENTS.md                  # Главный контекст для AI
├── repomix.config.json
├── .repomix/output.xml        # Индекс
│
├── strategy/                  # Стратегия и планы
│   ├── vision.md
│   ├── okrs-q2-2026.md
│   └── competitive-analysis.md
│
├── marketing/                 # Маркетинг
│   ├── brand-guidelines.md
│   ├── campaigns/
│   │   ├── launch-campaign.md
│   │   └── retention-plan.md
│   └── metrics/
│       └── kpi-dashboard.md
│
├── research/                  # Исследования
│   ├── user-interviews.md
│   ├── market-sizing.md
│   └── competitor-matrix.md
│
├── assets/                    # Бинарные оригиналы (исключены из индекса)
│   ├── presentations/         # .pptx
│   ├── documents/             # .docx, .pdf
│   └── media/                 # Изображения, видео
│
└── assets-index/              # Описания бинарных файлов (включены в индекс)
    ├── presentations.md       # Краткое содержание каждой презентации
    ├── documents.md           # Краткое содержание каждого документа
    └── media.md               # Описания изображений и видео
```

### Правила:
1. Основной контент — всегда в `.md` файлах
2. Бинарные оригиналы лежат в `assets/` и исключены из repomix
3. Для каждого бинарного файла создай описание в `assets-index/*.md`
4. AI конвертирует docx/pdf → md при первичной загрузке (ручной или автоматический этап)

### Конвертация бинарных файлов в Markdown:
```bash
# DOCX → Markdown (pandoc)
pandoc document.docx -t markdown -o document.md

# PDF → Markdown (marker — AI-based, высокое качество)
pip install marker-pdf
marker_single input.pdf output/

# PDF → текст (простой fallback)
pdftotext input.pdf output.txt
```

### Include для knowledge base:
```json
"include": ["**/*.md", "**/*.txt", "**/*.csv", "**/*.json", "**/*.yml"]
```

### Рекомендация по размеру:
Knowledge base проекты обычно компактнее кода. Для них `compress: false` часто предпочтительнее — сохраняет полную структуру текста, что важнее для стратегических документов, чем для кода.
