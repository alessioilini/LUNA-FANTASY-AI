"""Registry of game formulas whose internal form is NOT confirmed (status UNKNOWN).

Every place in the engine that depends on an unknown formula reads it through
AssumptionSet.get(id); the id is recorded in BattleResult.assumptions_used, so every
simulated number can be traced to the exact set of assumptions behind it.

`critical=True` assumptions (duplicate talents, out-of-queue actions, combo chains, panel
stats) have NO silent default: AssumptionSet raises AssumptionRequired unless the caller
set them explicitly (directly or through a named preset).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field


class AssumptionRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class Assumption:
    id: str
    title_ru: str
    status: str            # UNKNOWN | ASSUMED | CONFIRMED
    default: object
    options: str
    critical: bool = False
    note: str = ""


REGISTRY: dict[str, Assumption] = {}


def _a(id, title_ru, default, options, critical=False, status="UNKNOWN", note=""):
    REGISTRY[id] = Assumption(id, title_ru, status, default, options, critical, note)


# ---- turn order
_a("order.mode", "Порядок ходов", "round_spd_sort",
   "round_spd_sort (каждый раунд сортировка по текущей СКР) | fixed_position")
_a("order.tie_break", "Приоритет при равной СКР", ["attacker_first", "position"],
   "список ключей: attacker_first | defender_first | position | random | base_spd")
_a("order.resort_mid_round", "Пересортировка очереди при изменении СКР внутри раунда", False, "bool")
# ---- damage
_a("dmg.family", "Формула снижения урона защитой", "divisive",
   "divisive: dmg*k/(k+DEF) | ratio: ATK^2/(ATK+DEF) | subtractive: ATK-DEF*c")
_a("dmg.k_def", "Константа k для divisive", 10000.0, "число > 0")
_a("dmg.sub_c", "Коэффициент c для subtractive", 1.0, "число")
_a("dmg.min_fraction", "Минимальная доля урона после защиты", 0.05, "0..1")
_a("dmg.magic_def_stat", "Какая защита режет магический урон", "DEF", "DEF | MDEF | none")
_a("dmg.bonus_stacking", "Сложение бонусов урона", "additive", "additive | multiplicative")
_a("dmg.variance", "Случайный разброс урона (±доля)", 0.0, "0..0.2")
_a("dmg.base_crit_dmg", "Множитель крита, если CRIT_DMG не задан", 1.5, "число")
_a("dmg.crit_formula", "Шанс крита", "crit_minus_crit_res", "crit_minus_crit_res | crit_only")
_a("dmg.hit_formula", "Попадание/уклонение", "dodge_minus_acc", "dodge_minus_acc: P(miss)=max(0,DODGE-ACC) | none")
_a("dmg.true_can_miss", "Истинный урон может промахнуться", False, "bool")
_a("dmg.true_can_crit", "Истинный урон может критовать", False, "bool")
_a("dmg.dr_cap", "Максимальное снижение урона", 0.8, "0..1")
_a("dmg.ignore_def_formula", "Игнорирование защиты", "def_times_one_minus", "DEF_eff = DEF*(1-IGNORE_DEF)")
_a("shield.absorbs_true", "Щит поглощает истинный/фиксированный урон", True, "bool")
_a("reflect.dtype", "Тип отражённого урона", "true", "true | same")
_a("reflect.triggers_on_hit", "Отражённый урон вызывает реакции", False, "bool")
# ---- control / heal / stats
_a("ctrl.formula", "Шанс наложения контроля", "chance_times_hit_minus_res",
   "P = base*(1+CTRL_HIT-CTRL_RES), clamp 0..1")
_a("ctrl.controlled_can_react", "Контролируемая героиня может контратаковать/реагировать", False, "bool")
_a("heal.formula", "Формула лечения", "bonus_times_recv", "heal*(1+HEAL_BONUS)*(1+HEAL_RECV)")
_a("stat.aggregation", "Сложение характеристик", "base_plus_flat_times_pct", "(base+Σflat)*(1+Σpct)")
_a("stat.panel_includes_team", "Панельные статы уже включают командные/глобальные бонусы", None,
   "True | False", critical=True,
   note="Если True - глобальные статы не добавляются к героине в режиме panel; иначе добавляются один раз.")
# ---- stacking / duplicates
_a("stack.duplicate_effect", "Одинаковые таланты/эффекты на одной героине", None,
   "stack | unique", critical=True, note="Можно переопределить по effect_key: stacking={key: policy}")
_a("stack.same_status_default", "Повторное наложение того же статуса", "refresh", "refresh | stack | independent")
# ---- extra actions / combo
_a("extra.timing", "Когда выполняется дополнительный ход/атака вне очереди", None,
   "immediate (сразу после текущего действия) | end_of_round", critical=True)
_a("extra.combo_chain_max", "Сколько раз комбо может вызвать ещё одно комбо", None,
   "целое >= 0", critical=True)
_a("extra.per_unit_per_round_max", "Лимит доп. действий героини за раунд", 5, "целое")
_a("cooldown.tick", "Семантика перезарядки", "owner_turn_end",
   "N = способность недоступна N собственных ходов; счётчик уменьшается в конце хода владелицы (не в ход применения); командный источник - в начале раунда")
_a("react.max_depth", "Максимальная глубина цепочки реакций", 2, "целое")
# ---- statuses / death / revive
_a("status.tick", "Когда уменьшается длительность статусов", "owner_turn_end", "owner_turn_end | round_end")
_a("dot.timing", "Когда срабатывают периодические эффекты", "round_end", "round_end | owner_turn_start")
_a("dot.snapshot", "Периодический урон фиксирует статы в момент наложения", False, "bool")
_a("death.trigger_order", "Порядок эффектов при смерти", "kill_effects_first",
   "kill_effects_first (эффекты убийцы раньше) | death_effects_first (эффекты погибшей раньше) | by_priority")
_a("revive.can_act_same_round", "Воскрешённая героиня может ходить в том же раунде", True, "bool")
_a("death.clear_statuses", "Статусы снимаются при смерти (кроме persist_on_death)", True, "bool")
_a("revive.timing", "Воскрешение срабатывает", "immediate", "immediate")
_a("revive.cleanse_on_revive", "Снимать статусы при воскрешении", True, "bool")
# ---- battle frame
_a("battle.max_rounds", "Лимит раундов", 15, "целое")
_a("battle.draw_result", "Итог при лимите раундов", "draw", "draw | defender_wins | hp_percent")
_a("formation.front", "Позиции первого ряда", [0, 1, 2], "список индексов")
_a("target.default_single", "Цель одиночной атаки по умолчанию", "front_first_lowest_pos",
   "front_first_lowest_pos | front_first_random | random | lowest_hp")
_a("pet.timing", "Фаза срабатывания питомцев", "round_end", "round_start | round_end")
_a("team_source.stats", "Чьи статы использует командный источник (руны/оружие принцессы/реликты)", "team_max_atk",
   "team_max_atk | team_avg")
_a("resonance.rule", "Условие резонанса оружия принцессы", "as_declared", "as_declared")


PRESETS: dict[str, dict] = {
    # Exploratory preset: every critical choice is written out so results can be reproduced
    # and re-run with the alternatives. It is NOT a claim about the real game.
    "exploratory_v1": {
        "stat.panel_includes_team": True,
        "stack.duplicate_effect": "unique",
        "extra.timing": "immediate",
        "extra.combo_chain_max": 0,
    },
    "exploratory_v1_alt": {
        "stat.panel_includes_team": False,
        "stack.duplicate_effect": "stack",
        "extra.timing": "end_of_round",
        "extra.combo_chain_max": 1,
    },
}


@dataclass
class AssumptionSet:
    values: dict = field(default_factory=dict)
    stacking: dict = field(default_factory=dict)   # effect_key -> stack|unique
    name: str = "custom"
    used: set = field(default_factory=set)

    @classmethod
    def preset(cls, name: str, **overrides) -> "AssumptionSet":
        vals = copy.deepcopy(PRESETS[name])
        stacking = overrides.pop("stacking", {})
        vals.update(overrides)
        return cls(values=vals, stacking=stacking, name=name)

    def get(self, key: str):
        a = REGISTRY[key]
        self.used.add(key)
        if key in self.values:
            return self.values[key]
        if a.critical:
            raise AssumptionRequired(
                f"Критическое допущение '{key}' ({a.title_ru}) не задано явно. Варианты: {a.options}. "
                f"Используйте пресет (например exploratory_v1) или задайте значение.")
        return a.default

    def stacking_for(self, effect_key: str) -> str:
        if effect_key in self.stacking:
            self.used.add(f"stacking:{effect_key}")
            return self.stacking[effect_key]
        return self.get("stack.duplicate_effect")

    def fingerprint(self) -> dict:
        out = {}
        for k in sorted(REGISTRY):
            out[k] = self.values.get(k, REGISTRY[k].default)
        out["stacking"] = dict(sorted(self.stacking.items()))
        return out

    def copy(self, **overrides) -> "AssumptionSet":
        vals = copy.deepcopy(self.values)
        vals.update(overrides)
        return AssumptionSet(values=vals, stacking=dict(self.stacking), name=self.name + "*" if overrides else self.name)


def registry_markdown() -> str:
    lines = ["| ID | Правило | Статус | Значение по умолчанию | Варианты | Критичное |", "|---|---|---|---|---|---|"]
    for a in REGISTRY.values():
        d = "— (задать явно)" if a.critical else f"`{a.default}`"
        lines.append(f"| `{a.id}` | {a.title_ru} | {a.status} | {d} | {a.options} | {'да' if a.critical else ''} |")
    return "\n".join(lines)
