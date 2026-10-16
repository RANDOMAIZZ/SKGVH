---
name: research-rules
description: Research-then-plan workflow for Durak rule changes. Use when a game rule needs verification against official sources, before writing any code. Searches web sources, then produces a plan.
metadata:
  opencode/slash: "true"
---

# Research Rules

Перед любым изменением игровых правил — сначала исследование, потом план, потом код.

## Когда использовать

- Изменение логики в `src/game.js` (`canAttack`, `canThrowIn`, `canDefend`, `canTransfer`, `take`)
- Новый договорняк / настройка-пиюля в лобби
- Спор «как правильно по правилам»

## Процесс

1. **Источники.** Ищи официальные правила через websearch/webfetch. Приоритет:
   - pagat.com (John McLeod) — главный авторитет по Дураку
   - en.wikipedia.org/wiki/Durak
   - ru.wikipedia.org (карточная игра Дурак)
   - durakgames.ru, stavchess.ru, minigames.mail.ru (русскоязычные нюанты)
2. **Сверка.** Выпиши, что говорит каждый источник. Если источники противоречат — это **договорняк**, не «баг». Решение: делать настройкой (пиюля в лобби), а не молча выбирать сторону.
3. **Проверка кода.** Прочитай текущую реализацию в `src/game.js` и все места, где логика продублирована на клиенте (`gameLogic.js`, `HandArea.jsx`, `ActionButtons.jsx`, `useCardDrag.js`). Меняются всегда все сразу.
4. **План.** Только после шагов 1–3: что меняешь, в каких файлах, какие тесты добавишь (`test-throw.mjs` — юнит, `test-full.cjs` — браузер).
5. **Работай** только после одобрения плана пользователем.

## Запрещено

- Менять правила «из головы», без сверки с источником
- Молча выбирать сторону при противоречии источников
