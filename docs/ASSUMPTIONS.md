# Реестр игровых формул и допущений

Все формулы ниже **не подтверждены** для RU-клиента (статус UNKNOWN). Движок читает каждую из них через
`AssumptionSet.get(id)`; список использованных допущений сохраняется в каждом результате (`assumptions_used`).
Критичные допущения не имеют значения по умолчанию: без явного выбора движок выдаёт `AssumptionRequired`.

Сгенерировано из `luna/engine/assumptions.py` (`luna assumptions`).

| ID | Правило | Статус | Значение по умолчанию | Варианты | Критичное |
|---|---|---|---|---|---|
| `order.mode` | Порядок ходов | UNKNOWN | `round_spd_sort` | round_spd_sort (каждый раунд сортировка по текущей СКР) | fixed_position |  |
| `order.tie_break` | Приоритет при равной СКР | UNKNOWN | `['attacker_first', 'position']` | список ключей: attacker_first | defender_first | position | random | base_spd |  |
| `order.resort_mid_round` | Пересортировка очереди при изменении СКР внутри раунда | UNKNOWN | `False` | bool |  |
| `dmg.family` | Формула снижения урона защитой | UNKNOWN | `divisive` | divisive: dmg*k/(k+DEF) | ratio: ATK^2/(ATK+DEF) | subtractive: ATK-DEF*c |  |
| `dmg.k_def` | Константа k для divisive | UNKNOWN | `10000.0` | число > 0 |  |
| `dmg.sub_c` | Коэффициент c для subtractive | UNKNOWN | `1.0` | число |  |
| `dmg.min_fraction` | Минимальная доля урона после защиты | UNKNOWN | `0.05` | 0..1 |  |
| `dmg.magic_def_stat` | Какая защита режет магический урон | UNKNOWN | `DEF` | DEF | MDEF | none |  |
| `dmg.bonus_stacking` | Сложение бонусов урона | UNKNOWN | `additive` | additive | multiplicative |  |
| `dmg.variance` | Случайный разброс урона (±доля) | UNKNOWN | `0.0` | 0..0.2 |  |
| `dmg.base_crit_dmg` | Множитель крита, если CRIT_DMG не задан | UNKNOWN | `1.5` | число |  |
| `dmg.crit_formula` | Шанс крита | UNKNOWN | `crit_minus_crit_res` | crit_minus_crit_res | crit_only |  |
| `dmg.hit_formula` | Попадание/уклонение | UNKNOWN | `dodge_minus_acc` | dodge_minus_acc: P(miss)=max(0,DODGE-ACC) | none |  |
| `dmg.true_can_miss` | Истинный урон может промахнуться | UNKNOWN | `False` | bool |  |
| `dmg.true_can_crit` | Истинный урон может критовать | UNKNOWN | `False` | bool |  |
| `dmg.dr_cap` | Максимальное снижение урона | UNKNOWN | `0.8` | 0..1 |  |
| `dmg.ignore_def_formula` | Игнорирование защиты | UNKNOWN | `def_times_one_minus` | DEF_eff = DEF*(1-IGNORE_DEF) |  |
| `shield.absorbs_true` | Щит поглощает истинный/фиксированный урон | UNKNOWN | `True` | bool |  |
| `reflect.dtype` | Тип отражённого урона | UNKNOWN | `true` | true | same |  |
| `reflect.triggers_on_hit` | Отражённый урон вызывает реакции | UNKNOWN | `False` | bool |  |
| `ctrl.formula` | Шанс наложения контроля | UNKNOWN | `chance_times_hit_minus_res` | P = base*(1+CTRL_HIT-CTRL_RES), clamp 0..1 |  |
| `ctrl.controlled_can_react` | Контролируемая героиня может контратаковать/реагировать | UNKNOWN | `False` | bool |  |
| `heal.formula` | Формула лечения | UNKNOWN | `bonus_times_recv` | heal*(1+HEAL_BONUS)*(1+HEAL_RECV) |  |
| `stat.aggregation` | Сложение характеристик | UNKNOWN | `base_plus_flat_times_pct` | (base+Σflat)*(1+Σpct) |  |
| `stat.panel_includes_team` | Панельные статы уже включают командные/глобальные бонусы | UNKNOWN | — (задать явно) | True | False | да |
| `stack.duplicate_effect` | Одинаковые таланты/эффекты на одной героине | UNKNOWN | — (задать явно) | stack | unique | да |
| `stack.same_status_default` | Повторное наложение того же статуса | UNKNOWN | `refresh` | refresh | stack | independent |  |
| `extra.timing` | Когда выполняется дополнительный ход/атака вне очереди | UNKNOWN | — (задать явно) | immediate (сразу после текущего действия) | end_of_round | да |
| `extra.combo_chain_max` | Сколько раз комбо может вызвать ещё одно комбо | UNKNOWN | — (задать явно) | целое >= 0 | да |
| `extra.per_unit_per_round_max` | Лимит доп. действий героини за раунд | UNKNOWN | `5` | целое |  |
| `cooldown.tick` | Семантика перезарядки | UNKNOWN | `owner_turn_end` | N = способность недоступна N собственных ходов; счётчик уменьшается в конце хода владелицы (не в ход применения); командный источник - в начале раунда |  |
| `react.max_depth` | Максимальная глубина цепочки реакций | UNKNOWN | `2` | целое |  |
| `status.tick` | Когда уменьшается длительность статусов | UNKNOWN | `owner_turn_end` | owner_turn_end | round_end |  |
| `dot.timing` | Когда срабатывают периодические эффекты | UNKNOWN | `round_end` | round_end | owner_turn_start |  |
| `dot.snapshot` | Периодический урон фиксирует статы в момент наложения | UNKNOWN | `False` | bool |  |
| `death.trigger_order` | Порядок эффектов при смерти | UNKNOWN | `kill_effects_first` | kill_effects_first (эффекты убийцы раньше) | death_effects_first (эффекты погибшей раньше) | by_priority |  |
| `revive.can_act_same_round` | Воскрешённая героиня может ходить в том же раунде | UNKNOWN | `True` | bool |  |
| `death.clear_statuses` | Статусы снимаются при смерти (кроме persist_on_death) | UNKNOWN | `True` | bool |  |
| `revive.timing` | Воскрешение срабатывает | UNKNOWN | `immediate` | immediate |  |
| `revive.cleanse_on_revive` | Снимать статусы при воскрешении | UNKNOWN | `True` | bool |  |
| `battle.max_rounds` | Лимит раундов | UNKNOWN | `15` | целое |  |
| `battle.draw_result` | Итог при лимите раундов | UNKNOWN | `draw` | draw | defender_wins | hp_percent |  |
| `formation.front` | Позиции первого ряда | UNKNOWN | `[0, 1, 2]` | список индексов |  |
| `target.default_single` | Цель одиночной атаки по умолчанию | UNKNOWN | `front_first_lowest_pos` | front_first_lowest_pos | front_first_random | random | lowest_hp |  |
| `pet.timing` | Фаза срабатывания питомцев | UNKNOWN | `round_end` | round_start | round_end |  |
| `team_source.stats` | Чьи статы использует командный источник (руны/оружие принцессы/реликты) | UNKNOWN | `team_max_atk` | team_max_atk | team_avg |  |
| `resonance.rule` | Условие резонанса оружия принцессы | UNKNOWN | `as_declared` | as_declared |  |

## Пресеты

Пресеты — это явные наборы критичных решений для воспроизводимости, а не утверждения об игре.

```json
{
 "exploratory_v1": {
  "stat.panel_includes_team": true,
  "stack.duplicate_effect": "unique",
  "extra.timing": "immediate",
  "extra.combo_chain_max": 0
 },
 "exploratory_v1_alt": {
  "stat.panel_includes_team": false,
  "stack.duplicate_effect": "stack",
  "extra.timing": "end_of_round",
  "extra.combo_chain_max": 1
 }
}
```

## Как уточнять

1. Собрать реальные бои с полными составами (`luna validate import report.json`).
2. `luna validate calibrate --grid grid.json` — подбор на обучающей части (хронологически ранние бои),
   оценка на проверочной части. Калибровка по < 10 боям запрещена.
3. Подтверждённое значение переносится в `REGISTRY` со статусом `CONFIRMED` и ссылкой на источник.
