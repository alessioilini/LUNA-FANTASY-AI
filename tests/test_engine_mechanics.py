"""One test (or more) per combat rule from stage 5. All numbers are synthetic."""
import pytest

from helpers import U, basic, fight, run_round, events, team_source, asm
from luna.engine.assumptions import AssumptionSet, AssumptionRequired
from luna.engine.battle import Battle

NOOP = []  # unit with no abilities: never acts


def passive(aid, on, effects, **trig):
    return {"id": aid, "kind": "passive", "trigger": dict({"on": on}, **trig), "effects": effects}


def status(key, **kw):
    return dict({"key": key}, **kw)


# ------------------------------------------------------------------ turn order
def test_turn_order_by_speed():
    b, r = run_round([U("A0", {"SPD": 100})], [U("B0", {"SPD": 200})])
    assert [x[0] for x in r.first_round["order"]] == ["B0", "A0"]


@pytest.mark.parametrize("ties,first", [
    (["attacker_first", "position"], "A1"),
    (["defender_first", "position"], "B0"),
    (["position", "attacker_first"], "B0"),
])
def test_equal_speed_tie_break(ties, first):
    b, r = run_round([U("A1", NOOP and {}, [])], [U("B0", {}, [])], **{"order.tie_break": ties})
    assert r.first_round["order"][0][0] == first


def test_fixed_position_order_mode():
    b, r = run_round([U("A2", {"SPD": 999}, [])], [U("B0", {"SPD": 1}, [])], **{"order.mode": "fixed_position"})
    assert r.first_round["order"][0][0] == "B0"


def test_speed_buff_resort_mid_round():
    # A0 (fast) buffs ally A2 SPD before the order is re-sorted
    buff = {"id": "haste", "kind": "basic", "effects": [{"op": "status", "target": "ally_others",
            "status": status("haste", kind="buff", mods=[{"stat": "SPD", "value": 500}], duration=2)}]}
    A = [U("A0", {"SPD": 300}, [buff]), U("A2", {"SPD": 10}, [basic()])]
    B = [U("B0", {"SPD": 100, "HP": 1e9}, [basic()])]
    b, r = run_round(A, B, **{"order.resort_mid_round": True})
    casts = [e["src"] for e in events(r, "cast")]
    assert casts.index("A2") < casts.index("B0")
    b, r = run_round([U("A0", {"SPD": 300}, [buff]), U("A2", {"SPD": 10}, [basic()])],
                     [U("B0", {"SPD": 100, "HP": 1e9}, [basic()])], **{"order.resort_mid_round": False})
    casts = [e["src"] for e in events(r, "cast")]
    assert casts.index("A2") > casts.index("B0")


# ------------------------------------------------------------------ battle start / active / passive
def test_battle_start_effect_applies_before_first_action():
    buff = passive("rage", "battle_start", [{"op": "status", "target": "self",
                   "status": status("rage", kind="buff", mods=[{"stat": "ATK", "value": 100}])}])
    b, r = run_round([U("A0", {}, [basic(), buff])], [U("B0", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(200)


def test_active_cooldown_semantics():
    act = {"id": "nuke", "kind": "active", "priority": 9, "trigger": {"on": "turn", "cooldown": 2},
           "effects": [{"op": "damage", "target": "enemy_single", "coef": 5.0}]}
    b, r = fight([U("A0", {}, [basic(), act])], [U("B0", {"HP": 1e9}, [])], **{"battle.max_rounds": 6})
    used = [e["ab"] for e in events(r, "cast") if e["src"] == "A0"]
    assert used == ["nuke", "basic", "basic", "nuke", "basic", "basic"]


def test_initial_cooldown():
    act = {"id": "nuke", "kind": "active", "priority": 9, "trigger": {"on": "turn", "cooldown": 5, "initial_cooldown": 1},
           "effects": [{"op": "damage", "target": "enemy_single", "coef": 5.0}]}
    b, r = fight([U("A0", {}, [basic(), act])], [U("B0", {"HP": 1e9}, [])], **{"battle.max_rounds": 2})
    assert [e["ab"] for e in events(r, "cast")] == ["basic", "nuke"]


# ------------------------------------------------------------------ damage types
def test_physical_damage_divisive_defense():
    b, r = run_round([U("A0")], [U("B0", {"DEF": 10000}, [])], **{"dmg.k_def": 10000.0})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(50)


@pytest.mark.parametrize("family,expected", [("ratio", 100 * 100 / (100 + 100)), ("subtractive", 100 - 100)])
def test_damage_family_is_parametrized(family, expected):
    b, r = run_round([U("A0")], [U("B0", {"DEF": 100}, [])], **{"dmg.family": family, "dmg.min_fraction": 0.0})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(expected)


@pytest.mark.parametrize("def_stat,expected", [("MDEF", 100.0), ("DEF", 50.0), ("none", 100.0)])
def test_magic_damage_uses_configured_defense(def_stat, expected):
    b, r = run_round([U("A0", {}, [basic(dtype="magic")])], [U("B0", {"DEF": 10000, "MDEF": 0}, [])],
                     **{"dmg.magic_def_stat": def_stat})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(expected)


def test_true_damage_ignores_def_and_dr():
    b, r = run_round([U("A0", {}, [basic(dtype="true")])], [U("B0", {"DEF": 10000, "DR": 0.5}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100)


def test_fixed_damage_ignores_all_modifiers():
    ab = {"id": "fx", "kind": "basic", "effects": [{"op": "damage", "dtype": "fixed", "amount": 77, "coef": 0}]}
    b, r = run_round([U("A0", {"CRIT": 1.0, "CRIT_DMG": 3.0, "DMG_BONUS": 1.0}, [ab])], [U("B0", {"DEF": 9999, "DR": 0.5}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(77)


def test_ignore_defense():
    b, r = run_round([U("A0", {"IGNORE_DEF": 0.5})], [U("B0", {"DEF": 10000}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100 * 10000 / 15000)


def test_crit_and_crit_resistance():
    b, r = run_round([U("A0", {"CRIT": 1.0, "CRIT_DMG": 2.0})], [U("B0", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(200)
    b, r = run_round([U("A0", {"CRIT": 1.0, "CRIT_DMG": 2.0})], [U("B0", {"CRIT_RES": 1.0}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100)


def test_dodge_and_accuracy():
    b, r = run_round([U("A0")], [U("B0", {"DODGE": 1.0}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == 0 and r.unit("B0")["dodges"] == 1
    b, r = run_round([U("A0", {"ACC": 1.0})], [U("B0", {"DODGE": 1.0}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100)


def test_damage_reduction_cap_and_bonus_stacking():
    b, r = run_round([U("A0")], [U("B0", {"DR": 0.95}, [])], **{"dmg.dr_cap": 0.8})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(20)
    b, r = run_round([U("A0", {"DMG_BONUS": 0.2, "PHYS_DMG_BONUS": 0.3})], [U("B0", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(150)
    b, r = run_round([U("A0", {"DMG_BONUS": 0.2, "PHYS_DMG_BONUS": 0.3})], [U("B0", {}, [])],
                     **{"dmg.bonus_stacking": "multiplicative"})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(156)


# ------------------------------------------------------------------ combo / extra actions
def combo(chance=1.0, tag="magic"):
    return passive("combo", "after_attack", [{"op": "extra_attack", "ability": "basic"}], chance=chance, ability_tag=tag)


def test_extra_attack_requires_explicit_assumption():
    a = AssumptionSet()   # nothing set
    A = [U("A0", {}, [basic(dtype="magic"), combo()])]
    with pytest.raises(AssumptionRequired):
        Battle(A, [U("B0", {"HP": 1e9}, [])], a, seed=1).run()


@pytest.mark.parametrize("chain_max,extras", [(0, 1), (1, 2), (2, 3)])
def test_combo_chain_limit(chain_max, extras):
    b, r = run_round([U("A0", {}, [basic(dtype="magic"), combo()])], [U("B0", {"HP": 1e9}, [])],
                     **{"extra.combo_chain_max": chain_max})
    assert r.unit("A0")["extra_actions"] == extras
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100 * (1 + extras))


def test_combo_only_from_tagged_ability():
    b, r = run_round([U("A0", {}, [basic(dtype="physical"), combo(tag="magic")])], [U("B0", {"HP": 1e9}, [])])
    assert r.unit("A0")["extra_actions"] == 0


def test_extra_attack_timing_immediate_vs_end_of_round():
    A = lambda: [U("A0", {"SPD": 200}, [basic(dtype="magic"), combo()])]
    B = lambda: [U("B0", {"HP": 1e9, "SPD": 100}, [basic()])]
    b, r = run_round(A(), B(), **{"extra.timing": "immediate"})
    seq = [e["src"] for e in events(r, "cast") if e["ab"] == "basic"]
    assert seq == ["A0", "A0", "B0"]
    b, r = run_round(A(), B(), **{"extra.timing": "end_of_round"})
    seq = [e["src"] for e in events(r, "cast") if e["ab"] == "basic"]
    assert seq == ["A0", "B0", "A0"]


def test_extra_action_per_round_cap():
    b, r = run_round([U("A0", {}, [basic(dtype="magic"), combo()])], [U("B0", {"HP": 1e9}, [])],
                     **{"extra.combo_chain_max": 50, "extra.per_unit_per_round_max": 3})
    assert r.unit("A0")["extra_actions"] == 3


# ------------------------------------------------------------------ shields / reflect
def test_shield_absorbs_before_hp():
    sh = passive("bubble", "battle_start", [{"op": "shield", "target": "self", "flat": 60}])
    b, r = run_round([U("A0")], [U("B0", {}, [sh])])
    u = r.unit("B0")
    assert u["dmg_absorbed_by_own_shield"] == pytest.approx(60) and u["dmg_taken_hp"] == pytest.approx(40)
    assert r.unit("A0")["dmg_to_shield"] == pytest.approx(60)


def test_shield_true_damage_toggle():
    sh = passive("bubble", "battle_start", [{"op": "shield", "target": "self", "flat": 60}])
    b, r = run_round([U("A0", {}, [basic(dtype="true")])], [U("B0", {}, [sh])], **{"shield.absorbs_true": False})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100)


def test_reflect_no_ping_pong():
    refl = lambda: passive("thorns", "battle_start", [{"op": "status", "target": "self",
                           "status": status("thorns", kind="buff", reflect=0.5)}])
    b, r = run_round([U("A0", {"SPD": 200}, [basic(), refl()])], [U("B0", {}, [refl()])])
    assert r.unit("A0")["dmg_taken_hp"] == pytest.approx(50)
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100)


# ------------------------------------------------------------------ healing
def test_heal_and_overheal_with_bonus():
    heal = {"id": "heal", "kind": "basic", "effects": [{"op": "heal", "target": "ally_lowest_hp", "flat": 300}]}
    a1 = U("A1", {}, [])
    a1.hp = 900
    b, r = run_round([U("A0", {"HEAL_BONUS": 0.5}, [heal]), a1], [U("B0", {}, [])])
    u = r.unit("A0")
    assert u["heal_effective"] == pytest.approx(100) and u["overheal"] == pytest.approx(350)


def test_heal_received_modifier():
    heal = {"id": "heal", "kind": "basic", "effects": [{"op": "heal", "target": "ally_lowest_hp", "flat": 100}]}
    a1 = U("A1", {"HEAL_RECV": -0.5}, [])
    a1.hp = 100
    b, r = run_round([U("A0", {}, [heal]), a1], [U("B0", {}, [])])
    assert r.unit("A0")["heal_effective"] == pytest.approx(50)


# ------------------------------------------------------------------ revive / revive ban / death order
def reviver():
    return passive("rev", "ally_death", [{"op": "revive", "target": "dead_ally_random", "count": 1, "hp_pct": 0.5}], per_battle=1)


def banner():
    return passive("ban", "kill", [{"op": "status", "target": "event_target",
                   "status": status("revive_ban", kind="debuff", revive_ban=True, duration=3)}])


def test_revive():
    b, r = run_round([U("A0")], [U("B0", {"HP": 50}, []), U("B1", {}, [reviver()])])
    u = r.unit("B0")
    assert u["deaths"] == 1 and u["revived_times"] == 1 and u["alive"] and u["hp"] == pytest.approx(25)


def test_revive_ban_blocks_revive_when_kill_effects_first():
    b, r = run_round([U("A0", {}, [basic(), banner()])], [U("B0", {"HP": 50}, []), U("B1", {}, [reviver()])],
                     **{"death.trigger_order": "kill_effects_first"})
    u = r.unit("B0")
    assert u["revive_blocked"] == 1 and not u["alive"]


def test_revive_ban_too_late_when_death_effects_first():
    b, r = run_round([U("A0", {}, [basic(), banner()])], [U("B0", {"HP": 50}, []), U("B1", {}, [reviver()])],
                     **{"death.trigger_order": "death_effects_first"})
    assert r.unit("B0")["alive"] and r.unit("B0")["revived_times"] == 1


def test_self_revive_on_self_death_and_battle_not_ended_early():
    selfrev = passive("phoenix", "self_death", [{"op": "revive", "target": "self", "hp_pct": 1.0}], per_battle=1)
    b, r = run_round([U("A0")], [U("B0", {"HP": 50}, [selfrev])])
    assert r.winner == "draw" and r.unit("B0")["alive"]


# ------------------------------------------------------------------ control
def stunner(chance=1.0, cd=None):
    trig = {"on": "turn"}
    if cd:
        trig["cooldown"] = cd
    return {"id": "stun", "kind": "active", "priority": 5, "trigger": trig,
            "effects": [{"op": "status", "target": "enemy_single", "chance": chance,
                         "status": status("stun", control="stun", duration=1)}]}


def test_control_skips_turn():
    b, r = run_round([U("A0", {"SPD": 200}, [stunner()])], [U("B0", {}, [basic()])])
    assert r.unit("B0")["skipped_turns"] == 1 and r.unit("A0")["dmg_taken_hp"] == 0


def test_control_resistance():
    b, r = run_round([U("A0", {"SPD": 200}, [stunner()])], [U("B0", {"CTRL_RES": 1.0}, [basic()])])
    assert r.unit("A0")["ctrl_resisted"] == 1 and r.unit("A0")["dmg_taken_hp"] == pytest.approx(100)


def test_control_duration_one_turn():
    b, r = fight([U("A0", {"SPD": 200}, [basic(coef=0), stunner(cd=10)])], [U("B0", {}, [basic()])],
                 **{"battle.max_rounds": 2})
    assert r.unit("B0")["skipped_turns"] == 1 and r.unit("A0")["dmg_taken_hp"] == pytest.approx(100)


def test_controlled_unit_cannot_counter():
    counter = passive("counter", "damaged", [{"op": "damage", "target": "attacker", "coef": 0.5}])
    stun_first = passive("pre", "battle_start", [{"op": "status", "target": "enemy_all",
                         "status": status("stun", control="stun", duration=5)}])
    b, r = run_round([U("A0", {}, [basic(), stun_first])], [U("B0", {}, [counter])])
    assert r.unit("A0")["dmg_taken_hp"] == 0


# ------------------------------------------------------------------ cleanse / dispel
def test_cleanse_and_dispel():
    curse = passive("curse", "battle_start", [{"op": "status", "target": "enemy_all",
                    "status": status("weak", kind="debuff", mods=[{"stat": "ATK", "value": -50}])}])
    bless = passive("bless", "battle_start", [{"op": "status", "target": "self",
                    "status": status("blessed", kind="buff", mods=[{"stat": "ATK", "value": 50}])}])
    cleanse = {"id": "cl", "kind": "basic", "effects": [{"op": "cleanse", "target": "ally_all", "count": 1}]}
    dispel = {"id": "dp", "kind": "basic", "effects": [{"op": "dispel", "target": "enemy_all", "count": 1}]}
    b, r = run_round([U("A0", {"SPD": 50}, [curse, bless]), U("A1", {"SPD": 300}, [dispel])],
                     [U("B0", {"SPD": 200}, [cleanse])])
    assert r.unit("B0")["cleansed"] == 1 and r.unit("A1")["dispelled"] == 0  # A1 dispels B side: nothing there
    assert not any(s.key == "weak" for s in b.units[2].statuses)


def test_undispellable_status():
    bless = passive("bless", "battle_start", [{"op": "status", "target": "self",
                    "status": status("holy", kind="buff", undispellable=True)}])
    dispel = {"id": "dp", "kind": "basic", "effects": [{"op": "dispel", "target": "enemy_all", "count": 5}]}
    b, r = run_round([U("A0", {}, [dispel])], [U("B0", {}, [bless])])
    assert any(s.key == "holy" for s in b.units[1].statuses)


# ------------------------------------------------------------------ stacking / durations
def _apply(b, src, tgt, st):
    b.apply_status(src, tgt, {"status": st}, {"id": "t"}, 0)


@pytest.mark.parametrize("policy,expected_atk", [("refresh", 150), ("stack", 250), ("independent", 250)])
def test_status_stacking_policies(policy, expected_atk):
    a, t = U("A0"), U("B0")
    b = Battle([a], [t], asm(), seed=1)
    st = status("rage", kind="buff", mods=[{"stat": "ATK", "value": 50}], stacking=policy, max_stacks=3)
    for _ in range(3):
        _apply(b, a, t, st)
    assert t.stat("ATK") == pytest.approx(expected_atk)


def test_stack_cap():
    a, t = U("A0"), U("B0")
    b = Battle([a], [t], asm(), seed=1)
    st = status("rage", kind="buff", mods=[{"stat": "ATK", "value": 10}], stacking="stack", max_stacks=2)
    for _ in range(5):
        _apply(b, a, t, st)
    assert t.stat("ATK") == pytest.approx(120)


def test_status_duration_counts_owner_turns():
    buff = passive("b", "battle_start", [{"op": "status", "target": "self",
                   "status": status("x", kind="buff", duration=2)}])
    b, r = fight([U("A0", {}, [basic(coef=0), buff])], [U("B0", {"HP": 1e9}, [basic(coef=0)])], **{"battle.max_rounds": 3})
    exp = [e for e in events(r, "expire") if e["key"] == "x"]
    assert len(exp) == 1 and exp[0]["r"] == 2


# ------------------------------------------------------------------ death effects / DoT / reactions
def test_death_effect():
    boom = passive("boom", "self_death", [{"op": "damage", "target": "enemy_all", "dtype": "fixed", "amount": 100}])
    b, r = run_round([U("A0")], [U("B0", {"HP": 50}, [boom])])
    assert r.unit("A0")["dmg_taken_hp"] == pytest.approx(100)


def test_dot_ticks_at_round_end_and_credits_source():
    poison = {"id": "poison", "kind": "basic", "effects": [
        {"op": "damage", "target": "enemy_single", "coef": 1.0},
        {"op": "status", "target": "same", "status": status("poison", dot={"coef": 0.1, "stat": "ATK", "dtype": "true"}, duration=2)}]}
    b, r = run_round([U("A0", {}, [poison])], [U("B0", {"HP": 1e9}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(110)
    assert r.unit("A0")["by_ability"]["poison"]["dmg"] == pytest.approx(110)


def test_counterattack_reaction_and_depth_cap():
    counter = lambda: passive("counter", "damaged", [{"op": "damage", "target": "attacker", "coef": 0.5}])
    b, r = run_round([U("A0", {"HP": 1e9}, [basic()])], [U("B0", {"HP": 1e9}, [counter()])])
    assert r.unit("A0")["dmg_taken_hp"] == pytest.approx(50)
    # mutual counters terminate thanks to react.max_depth
    b, r = run_round([U("A0", {"HP": 1e9, "SPD": 200}, [basic(), counter()])], [U("B0", {"HP": 1e9}, [counter()])],
                     **{"react.max_depth": 3})
    assert len(events(r, "depth_cap")) >= 1


# ------------------------------------------------------------------ targeting
def test_default_target_front_row_first():
    b, r = run_round([U("A0")], [U("B3", {}, []), U("B1", {}, [])])
    assert r.unit("B1")["dmg_taken_hp"] > 0 and r.unit("B3")["dmg_taken_hp"] == 0


def test_back_row_targeted_when_front_empty():
    b, r = run_round([U("A0")], [U("B4", {}, []), U("B3", {}, [])])
    assert r.unit("B3")["dmg_taken_hp"] > 0


def test_taunt_overrides_targeting():
    taunt = passive("t", "battle_start", [{"op": "status", "target": "self", "status": status("taunt", kind="buff")}])
    b, r = run_round([U("A0")], [U("B0", {}, []), U("B5", {}, [taunt])])
    assert r.unit("B5")["dmg_taken_hp"] > 0 and r.unit("B0")["dmg_taken_hp"] == 0


# ------------------------------------------------------------------ pets / runes / princess weapon (engine part)
def test_pet_phase_round_end():
    pet = passive("pet", "pet_phase", [{"op": "damage", "target": "enemy_single", "dtype": "fixed", "amount": 100}])
    pet["tags"] = ["pet"]
    b, r = run_round([U("A0", {}, [basic(), pet])], [U("B0", {"HP": 1e9}, [basic()])])
    casts = [e["ab"] for e in events(r, "cast")]
    assert casts == ["basic", "basic", "pet"]


def test_pet_phase_round_start():
    pet = passive("pet", "pet_phase", [{"op": "damage", "target": "enemy_single", "dtype": "fixed", "amount": 100}])
    b, r = run_round([U("A0", {}, [basic(), pet])], [U("B0", {"HP": 1e9}, [basic()])], **{"pet.timing": "round_start"})
    assert [e["ab"] for e in events(r, "cast")][0] == "pet"


def test_rune_activation_order():
    r1 = {"id": "rune:r1", "kind": "rune", "rune_order": 1, "trigger": {"on": "round_start"},
          "effects": [{"op": "damage", "target": "enemy_all", "dtype": "fixed", "amount": 1}]}
    r0 = dict(r1, id="rune:r0", rune_order=0)
    b, r = run_round([U("A0", {}, []), team_source("A", [r1, r0])], [U("B0", {"HP": 1e9}, [])])
    assert [e["ab"] for e in events(r, "cast")] == ["rune:r0", "rune:r1"]


@pytest.mark.parametrize("prob,expect", [(1.0, 1), (0.0, 0)])
def test_nested_rune_probability(prob, expect):
    parent = {"id": "rune:p", "kind": "rune", "trigger": {"on": "round_start"}, "effects": [],
              "nested": [{"id": "child", "prob": prob, "effects": [{"op": "damage", "target": "enemy_all", "dtype": "fixed", "amount": 10}]}]}
    b, r = run_round([U("A0", {}, []), team_source("A", [parent])], [U("B0", {"HP": 1e9}, [])])
    assert len(events(r, "nested_rune")) == expect


def test_nested_rune_frequency_matches_probability():
    hits = 0
    N = 400
    for s in range(N):
        parent = {"id": "rune:p", "kind": "rune", "trigger": {"on": "round_start"}, "effects": [],
                  "nested": [{"id": "c", "prob": 0.3, "effects": []}]}
        b, r = run_round([U("A0", {}, []), team_source("A", [parent])], [U("B0", {}, [])], seed=s)
        hits += len(events(r, "nested_rune"))
    assert abs(hits / N - 0.3) < 0.07


# ------------------------------------------------------------------ battle frame
def test_round_limit_result():
    b, r = fight([U("A0", {}, [basic(coef=0)])], [U("B0", {}, [basic(coef=0)])], **{"battle.max_rounds": 3})
    assert r.winner == "draw" and r.end_reason == "round_limit" and r.rounds == 3
    b, r = fight([U("A0", {}, [basic(coef=0)])], [U("B0", {}, [basic(coef=0)])],
                 **{"battle.max_rounds": 3, "battle.draw_result": "defender_wins"})
    assert r.winner == "B"


def test_determinism_same_seed():
    def mk():
        return ([U("A0", {"CRIT": 0.5, "DODGE": 0.2}), U("A1", {"CRIT": 0.3})],
                [U("B0", {"DODGE": 0.3, "CRIT": 0.4}), U("B1", {"CRIT": 0.2})])
    r1 = fight(*mk(), seed=42)[1]
    r2 = fight(*mk(), seed=42)[1]
    assert r1.log == r2.log and r1.winner == r2.winner
    r3 = fight(*mk(), seed=43)[1]
    assert r3.log != r1.log


def test_assumptions_are_recorded():
    b, r = run_round([U("A0")], [U("B0", {}, [])])
    assert "dmg.family" in r.assumptions_used and "order.tie_break" in r.assumptions_used


def test_death_cause_recorded():
    b, r = run_round([U("A0")], [U("B0", {"HP": 50}, [])])
    d = r.deaths[0]
    assert d["uid"] == "B0" and d["killer"] == "A0" and d["ability"] == "basic" and d["overkill"] == pytest.approx(50)
