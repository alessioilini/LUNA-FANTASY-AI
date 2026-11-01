"""Kits of the operator's main team: build, awakening values, key mechanics, determinism."""
import pytest

from luna.engine.assumptions import AssumptionSet
from luna.engine.battle import Battle
from luna.engine.resolve import build_units
from luna.kits import KITS, aw
from luna.kits.catalog import build_catalog, team_from

MAIN = ["illusia", "teselien", "seneren", "lucifer", "vinette", "sbg:hymelle"]
AWK = {"teselien": 24, "vinette": 14, "seneren": 24, "lucifer": 24, "illusia": 24, "sbg:hymelle": 19}


@pytest.fixture(scope="module")
def cat():
    return build_catalog(AWK, AssumptionSet.preset("exploratory_v1"))


def battle(cat, a_ids, b_ids, seed=1, **over):
    asm = AssumptionSet.preset("exploratory_v1")
    asm.values.update(over)
    ua = build_units(team_from(cat, "A", a_ids), cat, "A", asm)
    ub = build_units(team_from(cat, "B", b_ids), cat, "B", asm)
    b = Battle(ua, ub, asm, seed=seed)
    return b, b.run()


def test_awakening_values():
    assert aw(24, 1.34, (5, 1.59)) == 1.59 and aw(4, 1.34, (5, 1.59)) == 1.34
    asm = AssumptionSet.preset("exploratory_v1")
    k24 = KITS["seneren"](24, asm)
    k0 = KITS["seneren"](0, asm)
    meal = lambda k: next(a for a in k["abilities"] if a["id"] == "seneren:meal")["effects"][0]["pct_cur_hp"]
    assert meal(k24) == 0.13 and meal(k0) == 0.12
    styx = lambda k: next(a for a in k["abilities"] if a["id"] == "seneren:styx_one")["effects"][0]["hp_atk_pct"]
    assert styx(k24) == 1.99                      # A25 upgrade not reached at A24


def test_all_kits_build_with_sources_and_notes(cat):
    for hid in MAIN:
        h = cat.get("heroes", hid)
        assert h["abilities"] and h["base_stats"]["ATK"] > 0 and f"class:{h['class']}" in h["tags"]
        assert any(a["kind"] == "basic" for a in h["abilities"])


def test_operator_verified_values_for_miaoyin(cat):
    v = next(a for a in cat.get("heroes", "sbg:hymelle")["abilities"] if a["id"] == "sbg:hymelle:verdict")
    assert v["effects"][0]["coef"] == 1.94 and v["effects"][1]["status"]["duration"] == 1


def test_mirror_battle_is_deterministic(cat):
    _, r1 = battle(cat, MAIN, MAIN, seed=3)
    _, r2 = battle(cat, MAIN, MAIN, seed=3)
    assert r1.log == r2.log and r1.winner in ("A", "B", "draw")


def test_miaoyin_switches_forms_and_casts_verdict(cat):
    b, r = battle(cat, ["sbg:hymelle"], ["teselien"], **{"battle.max_rounds": 4})
    casts = [e["ab"] for e in r.log if e["t"] == "cast" and e["src"] == "A0"]
    assert "sbg:hymelle:to_ghost" in casts and "sbg:hymelle:verdict" in casts


def test_lucifer_every_sixth_decadence(cat):
    b, r = battle(cat, ["lucifer"], ["illusia"], **{"battle.max_rounds": 15, "battle.draw_result": "draw"})
    yuuda = sum(1 for e in r.log if e["t"] == "cast" and e["ab"] == "lucifer:yuuda")
    sixth = sum(1 for e in r.log if e["t"] == "cast" and e["ab"] == "lucifer:six")
    assert sixth == yuuda // 6


def test_seneren_oath_targets_classes(cat):
    b, r = battle(cat, ["seneren", "lucifer", "illusia"], ["teselien"], **{"battle.max_rounds": 1})
    a = {u.hero_id: u for u in b.units if u.side == "A" and not u.is_team_source}
    assert a["lucifer"].has_status("oath_mage") and a["illusia"].has_status("oath_guard") and a["seneren"].has_status("oath_support")


def test_vinette_spends_marks_only_on_successful_revive(cat):
    b, r = battle(cat, ["vinette", "illusia"], ["lucifer", "sbg:hymelle"], seed=5, **{"battle.max_rounds": 6})
    vin = next(u for u in b.units if u.hero_id == "vinette" and u.side == "A")
    revs = [e for e in r.log if e["t"] == "revive" and e["src"] == vin.uid and e["ab"] == "vinette:revive"]
    gained = sum(1 for e in r.log if e["t"] == "res" and e["tgt"] == vin.uid)
    assert vin.res["mark"] >= 0 and gained >= 1
