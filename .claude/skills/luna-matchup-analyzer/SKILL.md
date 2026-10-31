---
name: luna-matchup-analyzer
description: >-
  Analyses a specific matchup (my team vs an enemy team) with luna.matchup.MatchupAnalyzer: model
  win rate, first-round tempo, key heroines on both sides, strengths and weaknesses, loss causes, the
  enemy's most dangerous damage sources and combos, and counterpick suggestions (hero swaps, formation
  swaps, rune order, build alternatives) each evaluated by paired Monte Carlo with a significance flag
  and a mechanism-based reason. Use it when the user asks why they lose to a team, how to counter it,
  who to swap, or how to rearrange the formation. Russian triggers: "почему я проигрываю", "как
  контрить", "контрпик", "против этой команды", "разбор матчапа", "кого заменить", "расстановка",
  "порядок рун", "сильные и слабые стороны".
---

# Luna Matchup Analyzer

## Назначение
Объяснять конкретный матчап через измеримые механизмы (урон 1-го раунда, воскрешения соперника,
контроль, смерти поддержки), а не мнения, и предлагать изменения, проверенные парным Монте-Карло
(одинаковые сиды для базы и кандидата, `luna.sim.stats.paired_diff`).

## Когда использовать
- «Почему моя команда проигрывает этой?», «чем законтрить команду с Виньеттой?»
- «Кого из моих героинь заменить на этот бой?», «как переставить формацию?»
- «Какой порядок рун лучше против этого соперника?»
- «Какой предмет/сет реально тянет мою команду в этом матчапе?» (абляция)

## Требуемые входные данные
- `my.json` (мой состав; `status: my_roster_confirmed`, если подтверждён) и `enemy.json`
  (`status: observed_opponent`, если составлен по реальному бою).
- Для замен героинь — `roster.json` (формат `Roster`: `heroes[]` с билдами, `inventory`,
  `rune_pool`, `pw_pool`, `region`, `balance_version`, `status`).
- Каталог, пресет допущений, при `UNKNOWN`-статах — `--priors`.

## Алгоритм работы
1. Валидировать обе команды: `luna validate-team my.json`, `luna validate-team enemy.json`.
2. Базовый разбор: `luna matchup my.json enemy.json -n 300 --key verafiel --out reports/matchup.json`.
   Поля: `summary` (`model_win_rate`, `ci95`, `avg_rounds`, `draws`), `metrics`, `first_round`
   (сколько моих ходят до первой героини соперника, P(смерть в 1-м раунде)), `key_heroes`,
   `strengths_weaknesses`, `loss_causes` (`top_killers`, `first_to_die`), `dangerous_interactions`,
   `assumptions_used`.
3. Контрпики: `luna matchup my.json enemy.json --suggest --roster roster.json -n 300`
   → `suggestions.improvements`: `kind` (замена героини / формация / порядок рун), `change`,
   `wr_before`, `wr_after`, `delta`, `ci95`, `significant`, `reason` (метрики, которые сдвинулись сильнее всего).
4. Вклад компонентов: добавить `--ablation` (снятие лимбов/сигилов/питомцев/рун/оружия принцессы по одному).
5. Альтернативы билдов и лучшая формация — в Python:
   ```python
   from luna.matchup import MatchupAnalyzer
   from luna.engine.assumptions import AssumptionSet
   ma = MatchupAnalyzer(cat, AssumptionSet.preset("exploratory_v1"), n=300)
   ma.suggest(my, enemy, build_options={"verafiel": {"limbs": [[...4 id...], [...]]}})
   ma.best_formation(my, enemy)   # попарные перестановки (720 расстановок слишком много)
   ```
6. Подтвердить лучшие 1–3 изменения: перепрогнать с большим `-n` и на `--preset exploratory_v1_alt`;
   для финала — `luna compare my.json my_fixed.json --opponents enemy.json -n 1000`.
7. Если нужен поиск по всему ростеру против пула — передать в luna-team-optimizer (`--mode counter`).

## Ограничения
- Рекомендация без `significant: true` подаётся как «нет значимого эффекта», а не как совет.
- Все WR модельные; реальная проверка — luna-battle-validator.
- Причины («reason») — это сдвиги метрик модели, а не подтверждённые механики игры.
- Не предлагать героинь/предметы, которых нет в ростере/инвентаре пользователя или нет в RU.
- Состав соперника из брифа (Команда A/B) — тестовый; ростер пользователя не подтверждён, пока он сам
  его не дал.
- Числа навыков, неизвестные в RU, не дорисовываются — только допущения/априоры с меткой.

## Формат результата
1) Итог: модельный WR ± CI95, пресет, n; 2) «Почему проигрываем»: 3–5 пунктов с метриками;
3) таблица изменений `изменение | ΔWR | CI95 | значимо | причина`; 4) риски и допущения
(`assumptions_used`), от которых вывод зависит.

## Проверки качества
- Все сравнения парные (одинаковые сиды), указан `n`.
- Топ-изменения перепроверены на альтернативном пресете; знак эффекта совпал.
- Предложенные составы проходят `luna validate-team`.
- В отчёте нет «реального винрейта».

## Примеры запросов
- «Почему я постоянно проигрываю команде с Люцифером и Виньеттой? Вот оба состава.»
- «Кого заменить из моей шестёрки против этой команды? Мой ростер в roster.json.»
- «Какая расстановка лучше против быстрого соперника, который убивает поддержку в первом раунде?»
- «Покажи, что в моей команде реально даёт вклад — руны, лимбы или оружие принцессы.»
