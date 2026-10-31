import copy
import json
from pathlib import Path

import pytest

from luna.engine.assumptions import AssumptionSet
from luna.matchup import MatchupAnalyzer, mode_objective, filter_roster_no_donation
from luna.model import Catalog, Team, hero_from_catalog
from luna.optimize.pareto import non_dominated_sort, crowding_distance
from luna.optimize.search import (Evaluator, Roster, best_rune_order, beam_search, cp_sat_equipment, genetic_algorithm,
                                  make_team, simulated_annealing_builds)
from luna.sim.montecarlo import simulate, run_battle, battle_report, compare, ehp_model
from luna.sim.stats import wilson, paired_diff, n_for_margin

ROOT = Path(__file__).resolve().parents[1]
CAT = Catalog.load(ROOT / "data" / "fixtures" / "synthetic_catalog.json")
ASM = AssumptionSet.preset("exploratory_v1")


def team(name, ids, **kw):
    t = Team(name=name, heroes=[hero_from_catalog(CAT, h) for h in ids], formation={h: i for i, h in enumerate(ids)},
             region="SYNTHETIC", balance_version="fixture-1", runes=["rune_0", "rune_1", "rune_2", "rune_3"],
             princess_weapon=["pw_0", "pw_1", "pw_2", "pw_3"])
    for k, v in kw.items():
        setattr(t, k, v)
    return t


A = team("A", ["s_tank", "s_striker", "s_reaper", "s_healer", "s_mage", "s_controller"])
B = team("B", ["s_tank", "s_bruiser", "s_reviver", "s_healer", "s_mage", "s_controller"])


def roster():
    return Roster(heroes={h: hero_from_catalog(CAT, h) for h in CAT.ids("heroes")}, region="SYNTHETIC",
                  balance_version="fixture-1", rune_pool=["rune_0", "rune_1", "rune_2", "rune_3"],
                  pw_pool=["pw_0", "pw_1", "pw_2", "pw_3"])


# ------------------------------------------------------------------ stats
def test_wilson_and_sample_size():
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi and hi - lo < 0.2
    assert n_for_margin(0.03) == 1068


def test_paired_diff():
    d = paired_diff([0, 0, 1, 1], [1, 1, 1, 1])
    assert d["delta"] == 0.5 and d["better"] == 2


# ------------------------------------------------------------------ simulator
def test_simulation_reproducible_and_parallel_equal():
    s1 = simulate(A, B, CAT, ASM, n=60, seed=5, workers=1)
    s2 = simulate(A, B, CAT, ASM, n=60, seed=5, workers=2)
    assert s1["model_win_rate"] == s2["model_win_rate"] and s1["avg_rounds"] == s2["avg_rounds"]
    s3 = simulate(A, B, CAT, ASM, n=60, seed=6, workers=1)
    assert s3["heroes"] != s1["heroes"]


def test_simulation_summary_fields():
    s = simulate(A, B, CAT, ASM, n=40, seed=1, key_heroes=["s_healer"])
    for k in ("model_win_rate", "ci95", "avg_rounds", "avg_damage", "heroes", "first_death", "key_hero_death_prob",
              "assumptions_used", "label"):
        assert k in s
    h = s["heroes"]["A:s_healer"]
    for k in ("survival_rate", "heal_effective", "overheal", "damage_share", "abilities", "death_causes_top"):
        assert k in h
    assert "MODEL" in s["label"]


def test_battle_report_and_log():
    r = run_battle(A, B, CAT, ASM, seed=3)
    rep = battle_report(r)
    assert rep["winner"] in ("A", "B", "draw") and r.log and rep["first_round"]["order"]
    assert all("by_ability" in u for u in rep["units"])


def test_compare_crn():
    A2 = copy.deepcopy(A)
    for h in A2.heroes:
        h.extra_mods.append({"stat": "ATK", "value": 0.5, "mode": "pct", "source_id": f"t:{h.hero_id}"})
    c = compare(A, A2, [B], CAT, ASM, n=80, seed=3)
    assert c["overall"]["delta"] > 0


def test_ehp_model_depends_on_assumption():
    a = AssumptionSet.preset("exploratory_v1")
    assert ehp_model({"HP": 1000, "DEF": 10000}, 100, a) == pytest.approx(2000)
    a.values["dmg.family"] = "ratio"
    assert ehp_model({"HP": 1000, "DEF": 100}, 100, a) == pytest.approx(2000)


# ------------------------------------------------------------------ optimizer
def test_pareto():
    v = [[1, 1], [2, 0], [0, 2], [0.5, 0.5]]
    fr = non_dominated_sort(v)
    assert sorted(fr[0]) == [0, 1, 2] and fr[1] == [3]
    assert crowding_distance([[1, 1], [2, 0], [0, 2]])[0] < float("inf")


def test_rune_order_exhaustive_and_guard():
    ev = Evaluator([B], CAT, ASM, n=10, seed=2)
    r = best_rune_order(A, ev)
    assert r["evaluated"] == 24
    big = copy.deepcopy(A)
    big.runes = ["rune_0", "rune_1", "rune_2", "rune_3", "rune_nest_parent"]
    with pytest.raises(ValueError):
        best_rune_order(big, ev)


def test_cp_sat_respects_inventory_and_positions():
    t = copy.deepcopy(A)
    inv = {"limbs:limb_war_0": 1, "limbs:limb_war_1": 1, "limbs:limb_war_2": 1, "limbs:limb_war_3": 1,
           "limbs:limb_life_0": 2, "decorations:deco_1": 3}
    r = cp_sat_equipment(t, CAT, inv)
    assert r["status"] in ("OPTIMAL", "FEASIBLE")
    used = {}
    for h in r["team"].heroes:
        for i, l in enumerate(h.limbs):
            if l:
                assert CAT.get("limbs", l)["position"] == i
                used[l] = used.get(l, 0) + 1
        for d in h.decorations:
            used[d] = used.get(d, 0) + 1
    for k, n in used.items():
        sec = "limbs" if k.startswith("limb") else "decorations"
        assert n <= inv[f"{sec}:{k}"]


def test_ga_beam_sa_run_and_improve_or_match():
    ev = Evaluator([B], CAT, ASM, n=12, seed=4)
    r = genetic_algorithm(roster(), ev, generations=2, pop_size=6, n_screen=8, n_final=16)
    assert len(r["best"]) == 6 and len(set(r["best"])) == 6 and r["history"]
    rp = genetic_algorithm(roster(), ev, generations=1, pop_size=6, n_screen=8, n_final=10,
                           multi_objective=["win_rate", "survival"])
    assert rp["pareto_front"]
    b = beam_search(roster(), ev, width=2, n_screen=6)
    assert len(b["best"]) == 6
    opts = {"s_striker": {"talents": [[], ["tal_swift", "tal_pierce"]]}}
    s = simulated_annealing_builds(A, opts, ev, iters=4, n=8)
    assert s["objectives"]["win_rate"] >= ev(A, 8)["win_rate"] - 1e-9


def test_mode_objectives():
    for m in ("best_overall", "anti_meta", "counter", "no_donation", "with_resources", "pve_boss"):
        assert mode_objective(m)["description"]
    with pytest.raises(ValueError):
        mode_objective("nope")


def test_no_donation_filter():
    cat = Catalog(CAT.to_dict())
    cat.sections["heroes"]["s_mage"]["donation_only"] = True
    r = filter_roster_no_donation(roster(), cat)
    assert "s_mage" not in r.heroes


# ------------------------------------------------------------------ matchup
def test_matchup_analysis_and_suggestions():
    ma = MatchupAnalyzer(CAT, ASM, n=30, seed=3)
    rep = ma.analyze(A, B, key_heroes=["s_healer"])
    for k in ("summary", "first_round", "key_heroes", "strengths_weaknesses", "loss_causes", "dangerous_interactions"):
        assert k in rep
    sug = ma.suggest(A, B, roster=roster(), max_changes=8)
    assert sug["evaluated"] == 8
    assert all("reason" in r and "ci95" in r for r in sug["all"])
    ab = ma.ablation(A, B, n=20)
    assert {r["kind"] for r in ab} >= {"руны", "оружие принцессы"}


def test_with_resources_inventory_filter():
    from luna.matchup import filter_roster_inventory
    r = roster()
    r.inventory = {"heroes:s_mage": 1, "heroes:s_tank": 1, "runes:rune_0": 1}
    f = filter_roster_inventory(r)
    assert set(f.heroes) == {"s_mage", "s_tank"} and f.rune_pool == ["rune_0"] and f.pw_pool == []
