"""v2 mechanics needed by real kits: resources, casts, barrier, link, fatal save, drain, detonate, stealth,
block, freeze, immunities, while_dead, per-subject limits, execute, class selectors, new damage modifiers."""
import pytest

from helpers import U, basic, fight, run_round, events


def P(aid, on, effects, **trig):
    return {"id": aid, "kind": "passive", "trigger": dict({"on": on}, **trig), "effects": effects}


def st(key, **kw):
    return dict({"key": key}, **kw)


def test_resource_gain_condition_and_consume():
    gain = P("g", "battle_start", [{"op": "res", "target": "self", "name": "mark", "add": 4, "cap": 9}])
    spend = {"id": "nuke", "kind": "active", "priority": 9, "trigger": {"on": "turn", "res_ge": {"mark": 3}},
             "effects": [{"op": "damage", "target": "enemy_single", "coef": 5.0},
                         {"op": "res", "target": "self", "name": "mark", "add": -3}]}
    b, r = fight([U("A0", {}, [basic(), gain, spend])], [U("B0", {"HP": 1e9}, [])], **{"battle.max_rounds": 2})
    assert [e["ab"] for e in events(r, "cast") if e["src"] == "A0" and e["ab"] != "g"] == ["nuke", "basic"]
    assert b.units[0].res["mark"] == 1


def test_effect_level_conditions_and_target_conditions():
    ab = {"id": "x", "kind": "basic", "effects": [
        {"op": "damage", "target": "enemy_all", "coef": 1.0, "tcond": {"hp_ge": 0.5}},
        {"op": "damage", "target": "enemy_all", "coef": 1.0, "cond": {"self_has": "rage"}}]}
    b2 = U("B1", {}, [])
    b2.hp = 100
    b, r = run_round([U("A0", {}, [ab])], [U("B0", {}, []), b2])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100) and r.unit("B1")["dmg_taken_hp"] == 0


def test_every_n_casts_triggers_other_skill():
    big = {"id": "love", "kind": "active", "priority": -1, "trigger": {"on": "never"},
           "effects": [{"op": "damage", "target": "enemy_single", "dtype": "fixed", "amount": 1000}]}
    every = P("every2", "cast", [{"op": "cast", "ability": "love", "ignore_control": True}], ability_id="basic", every_n_casts=2)
    b, r = fight([U("A0", {}, [basic(), big, every])], [U("B0", {"HP": 1e9}, [])], **{"battle.max_rounds": 4})
    assert len([e for e in events(r, "cast") if e["ab"] == "love"]) == 2


def test_team_barrier_absorbs_share_and_collapses():
    bar = P("bar", "battle_start", [{"op": "barrier", "pct_max_hp": 0.1, "share": 0.5,
                                     "collapse": {"pct_of_total": 1.0, "target": "enemy_first:1", "dtype": "true"}}])
    b, r = run_round([U("A0", {"ATK": 400})], [U("B0", {"HP": 1000}, [bar, basic(coef=0)])])
    # barrier = 100; hit 400 -> 200 absorbed (capped at 100) -> 300 to HP; barrier collapses -> 100 true dmg to A0
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(300)
    assert r.unit("A0")["dmg_taken_hp"] == pytest.approx(100)


def test_life_link_splits_damage():
    link = P("ln", "battle_start", [{"op": "link", "target": "ally_link"}])
    b, r = run_round([U("A0", {"ATK": 300})], [U("B0", {}, [link]), U("B1", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(150) and r.unit("B1")["dmg_taken_hp"] == pytest.approx(150)


def test_fatal_save_once():
    save = P("save", "fatal", [{"op": "heal", "target": "self", "pct_max_hp": 0.4}], per_battle=1)
    b, r = fight([U("A0", {"ATK": 2000})], [U("B0", {"HP": 1000}, [save])], **{"battle.max_rounds": 2})
    u = r.unit("B0")
    assert u["deaths"] == 1 and len(events(r, "fatal_save")) == 1


def test_drain_cap_and_overflow_shield():
    dr = {"id": "dr", "kind": "basic", "effects": [{"op": "drain", "target": "enemy_all", "pct_cur_hp": 0.5, "cap_atk_mult": 2.0,
                                                    "heal_target": "ally_lowest_hp:1", "overflow_shield": "crimson"}]}
    b, r = run_round([U("A0", {"ATK": 100}, [dr])], [U("B0", {"HP": 1000}, []), U("B1", {"HP": 1000}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(200)      # 500 capped at 2xATK per target
    assert any(s.key == "crimson" for s in b.units[0].statuses)   # A0 at full HP -> all heal overflows to shield


def test_detonate_dot_and_dot_cap():
    psn = {"id": "p", "kind": "basic", "effects": [
        {"op": "status", "target": "enemy_single", "status": st("poison", dot={"pct_max_hp": 0.05, "cap_src_atk_mult": 1.0, "dtype": "true"},
                                                                  duration=2, stacking="stack", max_stacks=5)},
        {"op": "detonate", "target": "same", "keys": ["poison"], "factor": 1.0}]}
    b, r = run_round([U("A0", {"ATK": 10}, [psn])], [U("B0", {"HP": 1e6}, [])])
    # 5% of 1e6 = 50000, capped at 1x ATK = 10 ; detonation 10 + round-end tick 10
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(20)


def test_stealth_prevents_single_target_but_not_aoe():
    hide = P("hide", "battle_start", [{"op": "status", "target": "self", "status": st("stealth", kind="buff", stealth=True, duration=2)}])
    b, r = run_round([U("A0")], [U("B0", {}, [hide]), U("B1", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == 0 and r.unit("B1")["dmg_taken_hp"] > 0
    b, r = run_round([U("A0", {}, [basic(target="enemy_all")])], [U("B0", {}, [hide]), U("B1", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] > 0


def test_block_hits_status():
    sh = P("parry", "battle_start", [{"op": "status", "target": "self", "status": st("parry", kind="buff", block_hits=1)}])
    b, r = fight([U("A0")], [U("B0", {"HP": 1e9}, [sh])], **{"battle.max_rounds": 2})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100)        # first hit blocked, second lands


def test_freeze_breaks_after_two_hits():
    frz = {"id": "f", "kind": "active", "priority": 9, "trigger": {"on": "turn", "cooldown": 9},
           "effects": [{"op": "status", "target": "enemy_single", "status": st("freeze", control="stun", duration=3, freeze_break_hits=2)}]}
    b, r = fight([U("A0", {"SPD": 300}, [frz, basic()]), U("A1", {"SPD": 200})], [U("B0", {"HP": 1e9}, [basic()])],
                 **{"battle.max_rounds": 2})
    # round 1: frozen (1 hit) -> turn skipped; round 2: second hit breaks the freeze -> B0 acts again
    assert r.unit("B0")["skipped_turns"] == 1 and len(events(r, "freeze_broken")) == 1
    assert events(r, "freeze_broken")[0]["r"] == 2 and r.unit("A0")["dmg_taken_hp"] > 0


def test_immunity_to_debuffs_and_control():
    imm = P("imm", "battle_start", [{"op": "status", "target": "self", "status": st("aegis", kind="buff", immune_debuff=True, immune_control=True)}])
    dbf = {"id": "d", "kind": "basic", "effects": [{"op": "status", "target": "enemy_single", "status": st("weak", mods=[{"stat": "ATK", "value": -50}])},
                                                   {"op": "status", "target": "enemy_single", "status": st("stun", control="stun", duration=1)}]}
    b, r = run_round([U("A0", {"SPD": 300}, [dbf])], [U("B0", {}, [imm, basic()])])
    assert len(events(r, "immune")) >= 1 and r.unit("B0")["skipped_turns"] == 0


def test_while_dead_listener_and_per_subject_limit():
    heal = P("ice", "damaged", [{"op": "heal", "target": "event_target", "flat": 10}], relation="ally_or_self",
             per_subject_per_round=2, while_dead=True)
    a0 = U("A0", {"HP": 1}, [heal])
    a1 = U("A1", {"HP": 1e9}, [])
    a1.hp = 1e9 - 100
    b, r = run_round([a0, a1], [U("B0", {"ATK": 10, "SPD": 300}, [basic(target="enemy_all")])])
    # A0 dies on the first AoE but still heals A1 (max 2 per subject per round)
    assert r.unit("A0")["heal_effective"] > 0


def test_execute_threshold_and_kill_mode():
    ex = {"id": "ex", "kind": "basic", "effects": [{"op": "execute", "target": "enemy_single", "thr": 0.25, "mode": "kill",
                                                     "on_kill_status": [st("soul", kind="debuff", revive_ban=True)]}]}
    t = U("B0", {}, [])
    t.hp = 200
    b, r = run_round([U("A0", {}, [ex])], [t, U("B1", {}, [P("rev", "ally_death", [{"op": "revive", "target": "dead_ally_random"}])])])
    assert r.unit("B0")["deaths"] == 1 and r.unit("B0")["revive_blocked"] == 1


def test_revive_ignoring_ban_and_grants():
    selfrev = P("rise", "self_death", [{"op": "revive", "target": "self", "hp_pct": 0.4, "ignore_revive_ban": True,
                                        "grant": [st("guard", kind="buff", block_hits=1)]}], per_battle=1)
    ban = P("ban", "kill", [{"op": "status", "target": "event_target", "status": st("rb", kind="debuff", revive_ban=True)}])
    b, r = run_round([U("A0", {}, [basic(), ban])], [U("B0", {"HP": 50}, [selfrev])])
    assert r.unit("B0")["alive"] and any(s.key == "guard" for s in b.units[1].statuses)


def test_ally_class_selector():
    buff = P("oath", "battle_start", [{"op": "status", "target": "ally_class:mage", "status": st("mage_buff", kind="buff", mods=[{"stat": "DMG_BONUS", "value": 0.2}])}])
    a0, a1 = U("A0", {}, [buff], tags=["class:mage"]), U("A1", {}, [], tags=["class:warrior"])
    b, r = run_round([a0, a1], [U("B0", {"HP": 1e9}, [])])
    assert a0.has_status("mage_buff") and not a1.has_status("mage_buff")


def test_new_damage_modifiers():
    vul = P("v", "battle_start", [{"op": "status", "target": "enemy_all", "status": st("vul", mods=[{"stat": "DMG_TAKEN", "value": 0.5}])}])
    b, r = run_round([U("A0", {}, [basic(), vul])], [U("B0", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(150)
    mark = P("m", "battle_start", [{"op": "res", "target": "self", "name": "mark", "add": 5}])
    ab = basic(ignore_def_per_res={"name": "mark", "per": 0.1})
    b, r = run_round([U("A0", {}, [ab, mark])], [U("B0", {"DEF": 10000}, [])], **{"dmg.k_def": 10000.0})
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(100 * 10000 / 15000)
    ab2 = basic(bonus_per_debuff={"per": 0.1, "cap": 0.2})
    deb = P("d", "battle_start", [{"op": "status", "target": "enemy_all", "status": st(f"d{i}")} for i in range(3)] and
            [{"op": "status", "target": "enemy_all", "status": st(f"d{i}")} for i in range(3)])
    b, r = run_round([U("A0", {}, [ab2, deb])], [U("B0", {}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(120)
    cap = basic(pct_max_hp=0.5, pct_max_hp_cap_atk=1.5, coef=0, dtype="true")
    b, r = run_round([U("A0", {}, [cap])], [U("B0", {"HP": 1e6}, [])])
    assert r.unit("B0")["dmg_taken_hp"] == pytest.approx(150)
