---
starter_for: viral-short-form-veo
suggested_destination: raw/work/unsorted/
knowledge_target: knowledge/projects/veo3-runs/
---

# Veo 3 — цепочка промптов: [название ролика] / Shot [01]

> Скопируй в `raw/work/unsorted/`. Один файл на shot или на весь ролик — как удобнее.

## Мета

| Поле | Значение |
|------|----------|
| Shot | 01 — HOOK (0:00–0:01) |
| Раскадровка | ссылка на storyboard-… |
| Дата прогона | |
| Модель / настройки Veo | Veo 3, … |

## Intent (что должен получиться)

- Настроение: …
- Должен считываться за 1 сек: …
- Ошибки, которых избегаем: лишние пальцы, морфинг лица, …

## Prompt v1 (основной)

```
Vertical 9:16, [UGC-style / cinematic], [duration intent 1 second feel].

Subject: [who — age, look, clothing, no celebrity names].
Action: [single clear action in present tense].
Camera: [handheld close-up / static medium / slow push-in].
Lighting: [natural window light / soft ring light].
Background: [kitchen blur / street / minimal].
Style: TikTok ad, authentic, not stock footage.

Avoid: text overlays, logos, watermarks, distorted hands.
```

## Negative / constraints (если поддерживается)

```
no subtitles, no brand logos, no extra people, no shaky morphing
```

## Варианты (A/B)

**Prompt v1a — более агрессивный хук:**  
```
…
```

**Prompt v1b — мягче / доверие:**  
```
…
```

## Результаты прогонов

| Run | Prompt | Оценка 1–5 | Проблема | Что менять |
|-----|--------|------------|----------|------------|
| 1 | v1 | 2 | руки | упростить действие |
| 2 | v1a | 4 | чуть тёмно | + soft lighting |
| 3 | | | | |

## Выбранный клип

- Run #: 
- Файл / ссылка: 
- Почему выбрал: 

## Урок для базы (reusable rule)

> Например: «Close-up + одно действие работает лучше, чем “person shows product and talks” в одном промпте»

## Следующий shot

→ Shot 02: …
