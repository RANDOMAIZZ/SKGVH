---
name: regress
description: Full regression for Durak after any fix. Builds frontend, runs unit tests and browser tests, rolls back on failure. Use after every code change before reporting done.
metadata:
  opencode/slash: "true"
---

# Regress

После каждого фикса — полный регресс. Без зелёного регресса задача не закрыта.

## Процесс

1. **Синтаксис сервера:** `node --check src/game.js`, `node --check src/room.js`
2. **Билд:** `npm run build --prefix frontend` (из корня `Durak/`). Должен пройти без ошибок.
3. **Юнит-тесты:** `node test-throw.mjs` — все PASS.
4. **Браузерные тесты:**
   - Поднять dev-сервер: `npx wrangler dev --local --port 8787` (ждать 20–25 с, лог `dev-test.log`)
   - `node test-full.cjs` — все PASS
   - Остановить dev-сервер после прогона
5. **Если что-то падает:** чинить, НЕ подгонять тесты под баг. Исключение — тест проверял старое поведение после осознанной смены флоу (тогда переписать ассерт явно, с комментарием).
6. **Откат:** если фикс ломает регресс и быстро не чинится — откатить фикс, сообщить пользователю.

## Запрещено

- Объявлять «готово» без прогона `test-full.cjs`
- Глушить падающие ассерты вместо фикса причины
- Оставлять висящий `wrangler dev` после себя
