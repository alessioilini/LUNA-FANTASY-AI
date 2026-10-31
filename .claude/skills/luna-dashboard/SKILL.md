---
name: luna-dashboard
description: >-
  Starts and uses the local Luna Fantasy AI web dashboard (`luna dashboard --port 8765`, package
  luna/dashboard): a standard-library HTTP server that is a thin JSON layer over the existing modules
  (catalogs, KB status and hero cards, glossary, assumptions, meta, validation status, saved teams,
  team validation, battle, Monte Carlo, compare, matchup, matrix, CP-SAT equipment, resource plan,
  export) plus `luna export` for static HTML/XLSX/CSV reports. It never computes game numbers itself and
  repeats every "MODEL" label. Use it when the user wants a visual interface, to build teams in a
  browser, see results as charts or tables, or export a report. Russian triggers: "дашборд",
  "открой панель", "веб-интерфейс", "покажи графики", "отчёт в html", "выгрузи в excel", "экспорт",
  "собрать команду в браузере".
---

# Luna Dashboard

## Назначение
Дать пользователю локальный интерфейс к проекту: `luna dashboard` запускает
`luna.dashboard.server.serve(host, port)` (`http.server`, статика `luna/dashboard/static/`). Сервер —
тонкий JSON-слой над модулями `luna.*`: числа считают те же функции, что и CLI, с теми же метками
`MODEL ...`. Статические отчёты для пересылки — `luna export` (`luna/export.py`).

## Когда использовать
- «Открой дашборд», «хочу собрать команду и прогнать бой в браузере».
- Посмотреть покрытие базы, карточки героинь, допущения, мету, статус валидации.
- Нужен HTML/Excel/CSV-отчёт, чтобы поделиться им.
- Объяснить, почему в интерфейсе стат показан как UNKNOWN или WR помечен как модельный.

## Требуемые входные данные
- Свободный порт (по умолчанию 8765) и хост (по умолчанию `127.0.0.1`).
- Команды пользователя (сохраняются в `data/user/teams/`), портреты — `data/user/portraits/`
  (`.png/.jpg/.jpeg/.webp`).
- Для what-if каталога со статами UNKNOWN — априоры обязательны (сервер их требует).

## Алгоритм работы
1. Запустить в фоне: `luna dashboard --port 8765`; открыть `http://127.0.0.1:8765/`.
   Остановка — Ctrl+C. `luna dashboard --host 0.0.0.0 --port 8765` — только по явной просьбе:
   сервер без аутентификации и печатает предупреждение.
2. Чтение (GET): `/api/catalogs`, `/api/catalog`, `/api/schema`, `/api/kb/status`, `/api/kb/hero`,
   `/api/glossary`, `/api/assumptions`, `/api/portraits`, `/api/teams`, `/api/teams/<id>`, `/api/meta`,
   `/api/meta/forecast`, `/api/validation`.
3. Расчёты (POST, JSON-тело): `/api/teams` (сохранить), `/api/validate`, `/api/battle`, `/api/sim`,
   `/api/compare`, `/api/matchup`, `/api/matrix`, `/api/optimize/equipment` (CP-SAT),
   `/api/resources/plan`, `/api/export` (`report`, `fmt`: xlsx/csv/html/json, `name`); удалить команду —
   DELETE `/api/teams/<id>`.
4. Проверка API без браузера (пример): `curl -s http://127.0.0.1:8765/api/kb/status | head`.
5. Статический отчёт из CLI: прогнать команду с `--out reports/sim.json` (например
   `luna sim my.json enemy.json -n 1000 --out reports/sim.json`), затем
   `luna export reports/sim.json reports/sim.html` (или `.xlsx`, или `--fmt csv`).
6. Проверить на экране: метка «модельный результат», `n`, CI95, пресет и `assumptions_used`, регион
   и `balance_version`, статус `luna validate status` (`simulator_validated`).
7. Ошибки 4xx обычно означают: id нет в выбранном каталоге, стат UNKNOWN без априоров, смешение
   регионов/версий — исправлять данные, а не подставлять числа.

## Ограничения
- Дашборд не должен «досчитывать» или сглаживать числа: только результаты модулей `luna.*`.
- Модельный WR нигде не подаётся как реальный; метка обязательна на каждом виде с WR.
- UNKNOWN не превращается в 0; синтетические данные (`SYNTHETIC`) и what-if шаблоны помечены.
- Регионы и версии баланса не смешиваются в одном расчёте или графике.
- «Команда A/B» из брифа — тестовые составы, не подтверждённый ростер пользователя.
- Не публиковать сервер наружу без согласия пользователя; аутентификации нет.
- Метрики/события аналитики — навык gamedev-analytics-engineer.

## Формат результата
Ссылка `http://127.0.0.1:8765/` (или путь к HTML/XLSX), что именно открыто/посчитано, и
предупреждения: что модельное, что UNKNOWN, какие допущения, регион и версия баланса.

## Проверки качества
- Сервер отвечает на выбранном порту, `/api/kb/status` возвращает JSON.
- Каждый результат с WR несёт метку модели, `n` и CI95.
- Сохранённая команда проходит `luna validate-team data/user/teams/<файл>.json`.
- Экспорт открывается (XLSX — лист `summary` и таблицы отчёта).

## Примеры запросов
- «Запусти дашборд, хочу собрать команду и прогнать симуляцию в браузере.»
- «Сделай HTML-отчёт по матчапу, чтобы отправить другу.»
- «Выгрузи результаты оптимизатора в Excel.»
- «Почему на дашборде у Верафиэль скорость UNKNOWN и симуляция не запускается?»
