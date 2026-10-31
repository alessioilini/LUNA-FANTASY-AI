---
name: luna-resource-planner
description: >-
  Plans how to spend in-game resources on upgrades with luna resources: a CP-SAT multi-currency
  knapsack that maximises the model win-rate gain under a budget and prerequisites, and a long-term
  schedule that projects when each upgrade becomes affordable from daily income. Costs must be
  sourced; UNKNOWN costs are reported and never guessed, and gains are model ΔWR from the simulator.
  Use it when the user asks what to upgrade first, how to spend gold, shards or other currencies,
  how many days an upgrade takes, or wants a 30/90-day plan. Russian triggers: "на что потратить",
  "что качать первым", "план прокачки", "ресурсы", "бюджет", "сколько дней копить", "приоритет
  улучшений", "долгосрочный план".
---

# Luna Resource Planner

## Назначение
Выбирать набор улучшений под бюджет и строить долгосрочный график прокачки (`luna/resources.py`:
`plan`, `days_to_afford`, `long_term`), опираясь на модельный прирост WR и сорсированные стоимости.

## Когда использовать
- «Что прокачать первым при таком запасе ресурсов?»
- «Сколько дней копить на сет лимбов при моём доходе?»
- «Составь план на 90 дней.»
- После luna-matchup-analyzer/luna-team-optimizer — чтобы превратить рекомендации в очередь покупок.

## Требуемые входные данные
Файл `plan.json`:
```json
{"upgrades": [{"id": "verafiel_limbs_set4", "desc": "...", "cost": {"gold": 120000, "limb_mats": "UNKNOWN"},
               "gain": 0.03, "requires": []}],
 "budget": {"gold": 500000, "shards": 40},
 "have": {"gold": 200000}, "income_per_day": {"gold": 30000, "shards": 2}, "horizon_days": 90}
```
- `cost` — из источника (RU-клиент/гайд) или `"UNKNOWN"`; `gain` — модельный ΔWR.
- `requires` — id улучшений-предпосылок.

## Алгоритм работы
1. Получить `gain` для каждого улучшения из модели, а не на глаз: парное сравнение
   `luna compare current.json upgraded.json --opponents e1.json e2.json -n 1000` → `overall.delta`,
   либо `delta` из `luna matchup my.json enemy.json --suggest` / вклад из `--ablation`.
2. Проверить стоимости по KB/источникам; неизвестные оставить `"UNKNOWN"`.
3. Бюджетный план: `luna resources plan plan.json --out reports/plan.xlsx` → `status`
   (`OPTIMAL`/`FEASIBLE`), `chosen`, `expected_gain_model`, `spent`, `left`, `cost_unknown`.
   Модель CP-SAT: булева переменная на улучшение, `Σ cost ≤ budget` по каждой валюте, импликации
   `requires`, максимизация суммы `gain` (масштаб 1e5).
4. Долгосрочный график: `luna resources long-term plan.json` → `[{"id", "day", "gain_model"}]`
   (жадно по `gain/Σcost`, пропускает улучшения с `UNKNOWN`-стоимостью и не укладывающиеся в горизонт).
5. Точечно: `from luna.resources import days_to_afford; days_to_afford(cost, have, income_per_day)`.
6. Отдельно перечислить `cost_unknown` и что нужно, чтобы их узнать (скриншот магазина/прокачки).
7. Дизайн экономики/прогрессии в целом — gamedev-meta-progression-designer; модели CP-SAT —
   constraint-programming.

## Ограничения
- Не придумывать стоимости, доход и курсы обмена валют; неизвестное → `UNKNOWN` → в `cost_unknown`.
- `gain` суммируется линейно — это приближение: взаимодействия улучшений не учитываются; для
  финального набора перепроверить комбинированную команду через `luna compare`.
- `gain` = модельный ΔWR (метка `label`), не реальный прирост побед, пока симулятор не валидирован.
- Долгосрочный план — прозрачная эвристика, не оптимум.
- Предметы/героини, недоступные в RU или в инвентаре, не планируются.

## Формат результата
1) Таблица выбранного `улучшение | стоимость | gain (модель) | предпосылки`; 2) потрачено/остаток по
валютам; 3) график по дням; 4) список `cost_unknown`; 5) пометка «модельный прирост».

## Проверки качества
- Остаток по каждой валюте ≥ 0; все `requires` выбранных улучшений тоже выбраны.
- У каждого `gain` указан источник (команда compare/matchup и её `n`).
- Ни одна `UNKNOWN`-стоимость не превратилась в число.
- Итоговый набор перепроверен одним комбинированным `luna compare`.

## Примеры запросов
- «У меня 500к золота и 40 осколков — что прокачать, чтобы сильнее всего вырос винрейт?»
- «Сколько дней копить на 4-й предмет сета лимбов при доходе 30к золота в день?»
- «Сделай план прокачки на 90 дней по результатам оптимизатора.»
