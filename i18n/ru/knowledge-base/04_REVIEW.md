---
translation_of: knowledge-base/04_REVIEW.md
source_commit: 6aa3cf8185ced124e010747a4238fd8f6097a76f
source_version: 0.7.0
translated_at: 2026-05-16
translator: human
---

# 04 — AI Review Queue

> Workflow обработки материалов, которые Python-скрипт не смог автоматически превратить в знания.

---

## Очереди

| Папка | Когда попадает | Кто обрабатывает |
|-------|---------------|------------------|
| `review/needs-classification/` | Скрипт не определил тип/место | AI-агент |
| `review/needs-ai-decision/` | Нужен смысловой анализ | AI-агент в IDE |
| `review/needs-redaction/` | Обнаружены чувствительные данные | AI-агент + человек |
| `review/excluded-sensitive/` | Нельзя использовать | Никто (архив) |

Весь `review/` исключён из Repomix-индекса.

---

## Формат review-пакета

Python-скрипт создаёт пакет для каждого материала в `review/needs-ai-decision/`:

```markdown
# AI Review: q2-growth-strategy.pdf

## Источник

- Оригинал: assets/documents/2026-05-06__q2-growth-strategy.pdf
- Конвертация: processed/markdown/2026-05-06__q2-growth-strategy.md
- Определённый тип: стратегия / исследование / презентация
- Уверенность: средняя

## Почему нужен AI-ревью

Материал содержит стратегические решения, инсайты об аудитории и потенциально переиспользуемые фреймворки.

## Предполагаемые цели извлечения

- knowledge/domain/
- knowledge/projects/
- knowledge/decisions/
- knowledge/playbooks/
- assets-index/documents.md

## Вопросы для AI-агента

- Какие устойчивые знания извлечь?
- Какие решения, принципы или фреймворки здесь есть?
- Что временное и не должно стать глобальным знанием?
- Есть ли противоречия с существующими файлами в knowledge/?
- Нужна ли редакция перед индексацией?
```

---

## Промпт для AI-агента при обработке review

```markdown
Ты работаешь с локальной non-code knowledge base.

Сначала прочитай:
- AGENTS.md
- KNOWLEDGE_STRUCTURE.md
- kb.config.yml
- Выбранный файл из review/needs-ai-decision/

Твоя задача: превратить материал в чистые знания для Repomix-индекса.

Правила:
1. Извлеки durable knowledge: факты, принципы, решения, инсайты, фреймворки, стиль
2. Не тащи сырой шум, временные детали и чувствительные данные
3. Обнови релевантные файлы в knowledge/ (не создавай дубли)
4. Добавь frontmatter: source, extracted_at, tags
5. Обнови assets-index/ если описываешь бинарный ассет
6. Если нужна очистка → review/needs-redaction/ с объяснением
7. Если не хватает контекста → knowledge/open-questions/
8. Сообщи, какие файлы обновлены и почему

Запрещено:
- Индексировать raw/ и review/ напрямую
- Копировать длинные фрагменты чатов
- Добавлять персональные данные третьих лиц
- Создавать новые папки в knowledge/ без уточнения у пользователя
```

---

## Workflow обработки

```text
1. Открыть review/needs-ai-decision/ в IDE
2. Выбрать review-пакет
3. Прочитать связанный файл из processed/
4. Извлечь знания → обновить knowledge/
5. Удалить обработанный пакет из review/
6. Запустить ./reindex.sh
```
