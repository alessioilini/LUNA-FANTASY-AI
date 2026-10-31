---
name: luna-team-optimizer
description: >-
  Searches for the best team from the user's roster against a pool of opponents with luna optimize and
  luna.optimize.search: genetic algorithm over composition, formation, rune order and princess weapon
  (with NSGA-II Pareto ranking for several objectives), beam search, exhaustive rune order, CP-SAT
  equipment assignment under inventory and slot constraints, and simulated annealing over builds.
  Evaluation uses Monte Carlo with common random numbers and racing; results are model estimates. Use
  it when the user asks for the best team, best anti-meta or counter team, a no-donation team, the
  best rune order or how to distribute limbs and decorations. Russian triggers: "лучшая команда",
  "оптимизируй состав", "собери пачку", "антимета", "без доната", "порядок рун", "распредели лимбы",
  "оптимальный билд", "Парето".
---

# Luna Team Optimizer

## Назначение
Находить сильные составы и билды в пространстве «состав + формация + билды + порядок рун + оружие
принцессы» (`luna/optimize/search.py`, `luna/optimize/pareto.py`, режимы — `luna.matchup.MODES`),
сохраняя прослеживаемость: целевые функции, n боёв, сиды, допущения.

## Когда использовать
- «Собери лучшую команду из моих героинь против текущей меты».
- Нужна устойчивая (anti-meta), контр-, бездонатная или PvE-команда.
- Подобрать порядок 4 рун, распределение лимбов/украшений, таланты.

## Требуемые входные данные
- `roster.json` (формат `Roster`: `heroes` — список `HeroBuild`, `inventory` `{"limbs:id": n}`,
  `rune_pool`, `pw_pool`, `region`, `balance_version`, `status`). Без подтверждения пользователя
  `status` = `hypothetical`; «Команда A/B» брифа — не его ростер.
- Пул соперников (`--opponents a.json b.json ...`) — популярные команды из luna-meta-tracker.
- Режим: `best_overall`, `anti_meta`, `counter`, `no_donation`, `with_resources`, `pve_boss`.

## Алгоритм работы
1. Валидировать ростер/соперников (`luna validate-team enemy.json`), проверить регион/версию.
2. GA по составу: `luna optimize --roster roster.json --opponents e1.json e2.json --mode anti_meta
   --generations 8 --pop 16 -n 40 --n-final 300 --save reports/best_team.json --out reports/opt.json`.
   Отбор: элита + турнир(2), кроссовер с уникальностью героинь, мутации; в конце racing — топ-4
   перепроверяются на `--n-final` боях.
3. Многокритериально: `--pareto win_rate robust_wr speed` → `pareto_front` (цели в `OBJECTIVES`:
   `win_rate`, `robust_wr`, `speed`, `survival`, `cost`).
4. Быстрый жадный вариант: `luna optimize --roster roster.json --opponents e1.json --algo beam -n 40`.
5. Узкие пространства в Python (`Evaluator(opponents, cat, asm, n=100)`):
   - `best_rune_order(team, ev)` — полный перебор 4! = 24 порядков;
   - `cp_sat_equipment(team, cat, inventory)` — CP-SAT: лимбы по позициям и украшения по инвентарю
     (эвристический линейный скор, затем проверка Монте-Карло);
   - `simulated_annealing_builds(team, options, ev, iters=60)` — таланты/лимбы/питомцы/сигилы из
     заранее валидных альтернатив.
6. Проверить победителя: `luna validate-team reports/best_team.json --inventory inv.json`, затем
   `luna compare current.json reports/best_team.json --opponents e1.json e2.json -n 1000`
   и повтор на `--preset exploratory_v1_alt`.
7. Методология: настройка GA — genetic-algorithms; SA — simulated-annealing; CP-SAT —
   constraint-programming; честное сравнение алгоритмов/сидов — algorithm-benchmarking-statistics.

## Ограничения
- Модельный WR — не реальный; «лучшая команда» = лучшая по модели при названных допущениях.
- Режим `with_resources` оставляет только то, что есть в `inventory` ростера (`section:id` > 0; героини
  фильтруются, если в инвентаре есть ключи `heroes:`); финал всё равно проверяйте `luna validate-team --inventory`.
  `no_donation` фильтрует только по флагу
  `donation_only` из каталога (флаг должен иметь источник).
- `pve_boss` требует команду-босса в `--opponents`; иначе оценивать нечего.
- Нельзя добавлять героинь JP/EN/SEA, не подтверждённых в RU, и предметы без `provenance`.
- Глобальные статы — в `team.global_stats` один раз; не «оптимизировать» их в личных билдах.
- Малые `-n` на скрининге шумные: решения только по `--n-final` и парному `compare`.

## Формат результата
Таблица финалистов `героини | формация | руны | win_rate | robust_wr | speed | n`, Парето-фронт (если
был), история поколений (`history`), число оценок/боёв, путь к сохранённой команде, итог валидации и
пометка «модельная оценка».

## Проверки качества
- Победитель проходит `luna validate-team` без ERROR.
- Превосходство над текущей командой подтверждено `luna compare` (`significant: true`).
- Результат устойчив к смене сида GA и пресета допущений (≥ 2 прогона).
- Указаны режим, веса целей, `n`, `n_final`, сиды.

## Примеры запросов
- «Собери лучшую команду из моего ростера против трёх популярных команд меты.»
- «Нужна команда без доната, устойчивая против всех — покажи Парето по WR и скорости.»
- «Какой порядок моих четырёх рун лучший?»
- «Распредели лимбы и украшения по героиням с учётом того, что у меня реально есть.»
