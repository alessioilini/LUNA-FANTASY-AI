---
name: luna-combat-engine
description: >-
  Explains, extends and debugs the event-driven 6x6 combat engine (luna/engine/battle.py,
  resolve.py, state.py, assumptions.py): turn order, damage formula families, crits, dodge, shields,
  control, DoT/HoT, revives, reactions, extra attacks and combo chains, runes with nested runes, and
  the registry of named assumptions for every unconfirmed formula. Use it when the user asks how a
  mechanic is modelled, wants to encode a heroine skill as abilities/effects, add a new op, selector,
  trigger or assumption, or investigate a strange battle log. Russian triggers: "движок боя",
  "формула урона", "как работает комбо", "доп. атака", "воскрешение", "контроль", "порядок ходов",
  "допущение", "закодируй навык", "механика".
---

# Luna Combat Engine

## Назначение
Поддерживать боевой движок как прозрачную модель: каждое неподтверждённое правило — именованное
допущение в `luna/engine/assumptions.py` (`REGISTRY`), которое читается через `AssumptionSet.get(id)` и
попадает в `assumptions_used` результата. Навыки описываются данными (abilities/effects), а не кодом.

## Когда использовать
- Закодировать навык героини/руны/питомца как ability.
- Объяснить, почему в логе боя случилось событие (комбо, отражение, запрет воскрешения).
- Добавить новый op/селектор/триггер или новое допущение.
- Сравнить семейства формул урона (`dmg.family`).

## Требуемые входные данные
- Текст навыка с источником (RU-клиент/гайд) или явная пометка «what-if».
- Для отладки: команды и сид (`luna battle ... --seed N --log log.json`).

## Алгоритм работы
1. Прочитать реестр: `luna assumptions` (таблица ID/статус/варианты + пресеты).
   Критичные без умолчания: `stat.panel_includes_team`, `stack.duplicate_effect`, `extra.timing`,
   `extra.combo_chain_max` — задаются пресетом `exploratory_v1`/`exploratory_v1_alt` или `--set`.
2. Поток боя (докстринг `battle.py`): `battle_start` → раунд: `round_start`, фаза питомцев,
   порядок (`order.mode`, `order.tie_break`) → ходы; после каждого действия очередь реакций
   (глубина `react.max_depth`) → `round_end`: DoT/HoT, питомцы, триггеры, доп. действия `end_of_round`, тики статусов.
3. Ability: `{"id", "kind": basic|active|passive, "priority", "trigger": {"on": ..., ...}, "effects": [...], "tags"}`.
   - События `on`: `turn`, `battle_start`, `round_start`, `round_end`, `pet_phase`, `action`, `after_attack`,
     `damaged`, `dodged`, `healed`, `controlled`, `revived`, `crit`, `kill`, `self_death`, `ally_death`,
     `enemy_death`, `shield_broken`, `status_applied`; `relation`: self|ally|ally_or_self|enemy|any.
   - Условия: `cooldown`, `initial_cooldown`, `round`, `round_ge`, `first_n_rounds`, `every_n_rounds`,
     `hp_below`, `ally_hp_below`, `dead_ally_ge`, `ability_tag`, `dtype`, `per_round`, `per_battle`, `chance`.
   - Ops: `damage` (`coef`, `stat`, `flat`, `pct_max_hp`, `pct_cur_hp`, `amount`, `hits`, `dtype`
     physical|magic|true|fixed, `ignore_def`, `bonus`, `bonus_vs_status`, `can_dodge`, `can_crit`),
     `heal`, `shield`, `status` (`key`, `kind`, `duration`, `control`, `dot`, `hot`, `mods`, `revive_ban`,
     `reflect`, `max_stacks`, `stacking`), `cleanse`, `dispel`, `revive` (`hp_pct`, `count`),
     `extra_attack`, `extra_action`, `cooldown` (`delta`).
   - Селекторы: `self`, `same`, `hit`, `attacker`, `actor`, `event_target`, `dead_allies`, `dead_ally_random`,
     `enemy_single`, `enemy_all`, `enemy_front`, `enemy_back`, `enemy_random:N`, `enemy_lowest_hp:N`,
     `enemy_highest_atk:N`, `enemy_highest_spd:N`, `enemy_role:<role>`, `ally_all`, `ally_others`,
     `ally_lowest_hp:N`, `ally_random:N`, `ally_highest_atk:N`, `ally_front`, `ally_back`.
4. Руны/оружие принцессы/реликты исполняет невидимый «источник команды» (`uid` `AT`/`BT`, статы по
   `team_source.stats`); руны идут в порядке `rune_order`, `nested` катаются независимо после родителя.
5. Отладка: `luna battle a.json b.json --seed 7 --log reports/log.json --out reports/battle.json`;
   события лога `cast`, `miss`, `status`, `ctrl_resist`, `revive`, `revive_blocked`, `extra_scheduled`,
   `combo_chain_cap`, `depth_cap`, `nested_rune`.
6. Новое правило: `_a("id", "Название", default, "варианты", critical=...)` в `assumptions.py`, чтение
   только через `self.asm.get("id")`, тест в `tests/test_engine_mechanics.py` (хелперы `tests/helpers.py`:
   `U`, `basic`, `fight`, `run_round`, `events`).
7. Прогнать: `python -m pytest -q tests/test_engine_mechanics.py`.

## Ограничения
- Не придумывать коэффициенты навыков: без источника — `abilities_override` только в what-if с
  пометкой; числа в `luna/scenarios.py` и синтетическом каталоге — не данные игры.
- Неизвестная формула = новое допущение в `REGISTRY` со статусом `UNKNOWN`, а не «разумное» число в коде.
- Критичные допущения нельзя давать умолчанием — `AssumptionSet.get` бросает `AssumptionRequired`.
- Глобальные статы применяются один раз (командный слой), см. luna-build-analyzer.
- Дизайн/баланс формул в целом (TTK, EHP) — навык gamedev-combat-designer; этот навык — про модель проекта.

## Формат результата
- JSON ability с комментариями источника; либо дифф кода + новый тест.
- Для объяснения лога: цепочка событий `раунд → актор → ability → цели → реакции` и список
  допущений, которые повлияли на исход.

## Проверки качества
- Все тесты движка зелёные; новый механизм покрыт тестом с синтетическими числами.
- Новый `id` допущения виден в `luna assumptions` и в `assumptions_used` результата.
- Результат воспроизводим при одинаковом `--seed`.
- Навык героини помечен источником и уверенностью в `provenance` каталога.

## Примеры запросов
- «Закодируй навык: после атаки 30% шанс доп. атаки, не чаще раза за раунд.»
- «Почему в этом логе комбо сработало дважды? extra.combo_chain_max же 0.»
- «Добавь допущение, режет ли щит отражённый урон.»
- «Как в движке работают вложенные руны и порядок активации рун?»
