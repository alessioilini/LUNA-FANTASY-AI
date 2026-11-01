"""Skill activation / cooldown timing over 15 rounds. Both models are TEST MODES - neither is confirmed.

Model A_cycle: 'activation K / CT N' -> rounds K, K+N, K+2N, ...
Model B_gap  : 'activation K / CT N' -> rounds K, K+N+1, K+2(N+1), ...
"""
import pytest

from helpers import U, basic, fight
from luna.engine.assumptions import AssumptionSet, AssumptionRequired
from luna.engine.battle import Battle

R = 15


def skill(first, ct, aid="sk", prio=5):
    return {"id": aid, "kind": "active", "priority": prio, "trigger": {"on": "turn", "first": first, "ct": ct},
            "effects": [{"op": "damage", "target": "enemy_single", "coef": 0.0, "dtype": "fixed", "amount": 1}]}


def rounds_cast(r, aid, uid="A0"):
    return [e["r"] for e in r.log if e["t"] == "cast" and e["ab"] == aid and e["src"] == uid]


def run(abilities, model, enemy=None, **over):
    b, r = fight([U("A0", {"SPD": 200}, [basic(coef=0)] + abilities)], enemy or [U("B0", {"HP": 1e12}, [basic(coef=0)])],
                 **dict({"battle.max_rounds": R, "cd.model": model}, **over))
    return b, r


EXPECTED = {
    # (first, ct): {model: rounds}
    (1, 2): {"A_cycle": [1, 3, 5, 7, 9, 11, 13, 15], "B_gap": [1, 4, 7, 10, 13]},
    (2, 4): {"A_cycle": [2, 6, 10, 14], "B_gap": [2, 7, 12]},
    (1, 3): {"A_cycle": [1, 4, 7, 10, 13], "B_gap": [1, 5, 9, 13]},
    (3, 5): {"A_cycle": [3, 8, 13], "B_gap": [3, 9, 15]},
}


@pytest.mark.parametrize("first,ct", list(EXPECTED))
@pytest.mark.parametrize("model", ["A_cycle", "B_gap"])
def test_activation_schedule_15_rounds(first, ct, model):
    b, r = run([skill(first, ct)], model)
    assert rounds_cast(r, "sk") == EXPECTED[(first, ct)][model]


@pytest.mark.parametrize("model", ["A_cycle", "B_gap"])
def test_round_clock_equals_own_turn_clock_when_acting_every_round(model):
    _, r1 = run([skill(1, 2)], model, **{"cd.clock": "own_turn"})
    _, r2 = run([skill(1, 2)], model, **{"cd.clock": "round"})
    assert rounds_cast(r1, "sk") == rounds_cast(r2, "sk")


def test_cd_model_is_critical_without_default():
    a = AssumptionSet.preset("exploratory_v1")
    a.values.pop("cd.model")
    with pytest.raises(AssumptionRequired):
        Battle([U("A0", {}, [skill(1, 2)])], [U("B0")], a, seed=1)


def control_case(model, tick):
    # A0 casts in round 1; stunned in round 2 (inside its cooldown window)
    stunner = {"id": "st", "kind": "passive", "trigger": {"on": "round_start", "round": 2},
               "effects": [{"op": "status", "target": "enemy_single", "status": {"key": "stun", "control": "stun", "duration": 1}}]}
    b, r = run([skill(1, 2)], model, enemy=[U("B0", {"HP": 1e12}, [stunner])], **{"cd.tick_while_controlled": tick,
                                                                                    "battle.max_rounds": 8})
    return rounds_cast(r, "sk")


@pytest.mark.parametrize("model,tick,expected", [
    ("A_cycle", True, [1, 3, 5, 7]),      # CD keeps running while stunned
    ("A_cycle", False, [1, 4, 6, 8]),     # CD frozen while stunned -> shifted by one round
    ("B_gap", True, [1, 4, 7]),
    ("B_gap", False, [1, 5, 8]),
])
def test_control_interrupts_and_cd_while_controlled(model, tick, expected):
    assert control_case(model, tick) == expected


@pytest.mark.parametrize("model", ["A_cycle", "B_gap"])
def test_stun_on_due_round_delays_skill_to_next_turn(model):
    stunner = {"id": "st", "kind": "passive", "trigger": {"on": "round_start", "round": 3},
               "effects": [{"op": "status", "target": "enemy_single", "status": {"key": "stun", "control": "stun", "duration": 1}}]}
    b, r = run([skill(1, 2)], model, enemy=[U("B0", {"HP": 1e12}, [stunner])], **{"battle.max_rounds": 6})
    got = rounds_cast(r, "sk")
    assert 3 not in got and got[1] == (4 if model == "A_cycle" else 4)


def test_silence_blocks_actives_but_not_basic():
    silencer = {"id": "si", "kind": "passive", "trigger": {"on": "round_start", "round": 1},
                "effects": [{"op": "status", "target": "enemy_single", "status": {"key": "sil", "control": "silence", "duration": 1}}]}
    b, r = run([skill(1, 2)], "A_cycle", enemy=[U("B0", {"HP": 1e12}, [silencer])], **{"battle.max_rounds": 3})
    assert rounds_cast(r, "sk") == [2] and rounds_cast(r, "basic") == [1, 3]


@pytest.mark.parametrize("sets_cd,expected", [(False, [1, 3, 5, 7]), (True, [1, 4, 6])])
def test_extra_cast_from_passive_and_cd(sets_cd, expected):
    # a passive re-casts 'sk' once in round 2 (outside the queue)
    extra = {"id": "ex", "kind": "passive", "trigger": {"on": "round_start", "round": 2},
             "effects": [{"op": "cast", "ability": "sk", "ignore_control": True}]}
    b, r = run([skill(1, 2), extra], "A_cycle", **{"cd.extra_cast_sets_cd": sets_cd, "battle.max_rounds": 7})
    turn_casts = [e["r"] for e in r.log if e["t"] == "cast" and e["ab"] == "sk" and e.get("ev") == "turn"]
    assert turn_casts == expected


def test_priority_policy_when_two_actives_ready():
    a = skill(1, 2, aid="small", prio=9)
    b_ = skill(1, 4, aid="big", prio=1)
    _, r1 = run([a, b_], "A_cycle", **{"cd.priority": "declared", "battle.max_rounds": 1})
    _, r2 = run([skill(1, 2, aid="small", prio=9), skill(1, 4, aid="big", prio=1)], "A_cycle",
                **{"cd.priority": "longer_ct_first", "battle.max_rounds": 1})
    assert rounds_cast(r1, "small") == [1] and rounds_cast(r2, "big") == [1]


@pytest.mark.parametrize("policy,expected_cd", [("keep", 1), ("clear", 0), ("reset_to_initial", 1)])
def test_reset_on_revive(policy, expected_cd):
    u = U("A0", {"HP": 10}, [basic(coef=0), skill(2, 3)])
    rev = {"id": "rev", "kind": "passive", "trigger": {"on": "self_death", "per_battle": 1},
           "effects": [{"op": "revive", "target": "self", "hp_pct": 1.0}]}
    u.abilities.append(rev)
    a = AssumptionSet.preset("exploratory_v1")
    a.values.update({"cd.reset_on_revive": policy})
    b = Battle([u], [U("B0", {"ATK": 100, "SPD": 999}, [basic()])], a, seed=1)
    b.round = 1
    u.cooldowns["A0:x"] = 0
    u.cooldowns["sk"] = 1
    b.apply_damage(b.units[1], u, 1000, "fixed", {"id": "t"}, 0)
    b.drain()
    assert u.alive and u.cooldowns.get("sk", 0) == expected_cd


# ---------------------------------------------------------------- Lucifer and Vinette (real kits)
@pytest.fixture(scope="module")
def kits():
    from luna.kits import KITS
    return KITS


def kit_schedule(kits, hero, model, rounds=R):
    from luna.engine.resolve import build_units
    from luna.kits.catalog import build_catalog, team_from
    asm = AssumptionSet.preset("exploratory_v1")
    asm.values.update({"cd.model": model})
    cat = build_catalog({hero: 24}, asm, heroes=[hero])
    ua = build_units(team_from(cat, "A", [hero]), cat, "A", asm)
    dummy = U("B0", {"HP": 1e15, "DEF": 0, "SPD": 1}, [{"id": "noop", "kind": "basic", "effects": []}])
    asm.values.update({"battle.max_rounds": rounds, "battle.draw_result": "draw"})
    b = Battle(ua, [dummy], asm, seed=1)
    r = b.run()
    return {aid: [e["r"] for e in r.log if e["t"] == "cast" and e["ab"] == aid and e.get("ev") == "turn"]
            for aid in {e["ab"] for e in r.log if e["t"] == "cast"}}


@pytest.mark.parametrize("model,deca,love", [
    ("A_cycle", [1, 3, 5, 7, 9, 11, 13, 15], [2, 6, 10, 14]),
    # B_gap: both skills are ready in round 7; 'Любовь и наказание' (higher priority) wins and Декаданс slips to 8
    ("B_gap", [1, 4, 8, 11, 14], [2, 7, 12]),
])
def test_lucifer_regular_schedule(kits, model, deca, love):
    s = kit_schedule(kits, "lucifer", model)
    # regular (own-turn) casts only; extra casts from [Печаль] / every-6th are tracked separately
    assert s["lucifer:yuuda"] == deca
    assert s["lucifer:love"] == love


@pytest.mark.parametrize("model,expected", [("A_cycle", [1, 3, 5, 7, 9, 11, 13, 15]), ("B_gap", [1, 4, 7, 10, 13])])
def test_vinette_weapon_of_love_schedule(kits, model, expected):
    s = kit_schedule(kits, "vinette", model)
    assert s["vinette:love"] == expected
