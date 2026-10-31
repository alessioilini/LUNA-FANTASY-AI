---
name: luna-battle-simulator
description: >-
  Runs single battles and Monte Carlo series between two 6-heroine teams with the project simulator
  (luna battle, luna sim, luna compare, luna scenario): reproducible seeds, Wilson confidence
  intervals, paired comparisons with common random numbers, explicit priors for UNKNOWN stats and
  sensitivity to assumption presets. Every number is a MODEL win rate until validated. Use it when the
  user asks who wins, what the win chance is, to simulate N battles, compare two versions of a team, or
  test a what-if hypothesis. Russian triggers: "симуляция", "просимулируй", "кто победит", "шанс
  победы", "винрейт", "1000 боёв", "Монте-Карло", "сравни две команды", "что если", "гипотеза".
---

# Luna Battle Simulator

## Назначение
Оценивать исход боёв 6×6 через `luna/sim/montecarlo.py` (`run_battle`, `battle_report`, `simulate`,
`compare`) с полной прослеживаемостью: сид, пресет допущений, априоры, `assumptions_used`.
Все результаты помечены `MODEL WIN RATE - not a real win rate until validated`.

## Когда использовать
- «Кто победит: моя команда против этой?», «просимулируй 1000/10000 боёв».
- Сравнить две версии своей команды против пула соперников.
- Проверить гипотезу («+10% СКР», «запрет воскрешения») устойчиво к допущениям.

## Требуемые входные данные
- `my.json`, `enemy.json` (формат `Team`), каталог того же региона/версии (`--catalog`).
- Пресет допущений (`--preset exploratory_v1` по умолчанию) и/или `--set key=value`.
- Для статов `UNKNOWN` — файл априоров `--priors priors.json`:
  `{"label": "...", "priors": {"*|ATK": [lo, hi], "verafiel|SPD": [lo, hi]}}` (явное допущение).

## Алгоритм работы
1. Проверить команды: `luna validate-team my.json` (см. luna-build-analyzer).
2. Один бой с полным отчётом и логом:
   `luna battle my.json enemy.json --seed 1 --log reports/log.json --out reports/battle.json`
   (ходы, комбо, урон/лечение/щиты, контроль, воскрешения, смерти, `first_round`).
3. Серия: `luna sim my.json enemy.json -n 1000 --key verafiel --out reports/sim.xlsx`;
   для 10k+ — `-n 10000 --workers 8`. В ответе: `model_win_rate`, `ci95` (Уилсон), `draws`,
   `avg_rounds`, `heroes`, `first_death`, `key_hero_death_prob`, `assumptions_used`.
4. Размер выборки: `from luna.sim.stats import n_for_margin; n_for_margin(0.02)` → боёв для ±2 п.п.
5. Чувствительность: повторить с `--preset exploratory_v1_alt` и с ключевыми `--set`, например
   `--set dmg.family=ratio`, `--set extra.timing=end_of_round`, `--set "order.tie_break=[\"position\"]"`.
   Вывод устойчив только если знак эффекта одинаков во всех вариантах.
6. Парное сравнение (CRN): `luna compare my.json my_v2.json --opponents enemy1.json enemy2.json -n 500`
   → `per_opponent`, `overall.delta`, `ci`, `significant`.
7. Готовые what-if сценарии брифа: `luna scenario hypotheses -n 400 --workers 4 --out reports/hyp.json`,
   `luna scenario scenario3 --out reports/scen3.json` (шаблоны ролей + симметричные априоры).
8. Демонстрация без реальных данных: `--catalog data/fixtures/synthetic_catalog.json` и команды с
   `"region": "SYNTHETIC"`.

## Ограничения
- Модельный WR ≠ реальный WR, пока `luna validate status` не показывает `simulator_validated: true`
  (≥ 20 тестовых боёв, хронологический сплит, Brier < 0.25; см. luna-battle-validator).
- Не подставлять «типичные» статы вместо `UNKNOWN`: только `--priors` с меткой `label`.
- Критичные допущения (`stat.panel_includes_team`, `stack.duplicate_effect`, `extra.timing`,
  `extra.combo_chain_max`) всегда явно заданы — пресет называется в ответе.
- Нельзя смешивать регионы/версии каталога и команд (`MixedBalanceError`).
- «Команда A/B» из `luna/scenarios.py` — тестовые составы брифа, не ростер пользователя.
- Методология симуляций и детерминизма — gamedev-simulation-designer; статистика сравнения —
  algorithm-benchmarking-statistics.

## Формат результата
Таблица: `матчап | n | model_win_rate | ci95 | ничьи | ср. раунды | пресет | сид | априоры`,
затем ключевые героини (доля урона, выживаемость, P(смерть)), первые смерти и `assumptions_used`.
Крупно: «МОДЕЛЬНЫЙ результат, не реальный процент побед».

## Проверки качества
- Указаны `n`, `seed`, пресет, `--set`-переопределения и `priors.label`.
- CI95 приведён; разница двух команд — только через `compare`/парный тест, не «на глаз».
- Повторный запуск с тем же сидом даёт тот же результат.
- Вывод проверен минимум на двух пресетах допущений.

## Примеры запросов
- «Просимулируй 1000 боёв моей команды против команды с Люцифером и Виньеттой.»
- «Какой шанс победы, если Верафиэль поставить во второй ряд? Сравни с текущей расстановкой.»
- «Проверь гипотезу: +10% скорости всей команде — это реально помогает или зависит от допущений?»
- «Сколько боёв нужно, чтобы погрешность винрейта была ±2%?»
