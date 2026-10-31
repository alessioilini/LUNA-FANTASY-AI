import copy
import json
from pathlib import Path

import pytest

from luna.engine.assumptions import AssumptionSet, AssumptionRequired
from luna.engine.resolve import build_units, UnknownStatError
from luna.kb import KnowledgeBase
from luna.localization import resolve_hero, term, label
from luna.model import Catalog, Team, HeroBuild, hero_from_catalog
from luna.provenance import Fact, Source, UNKNOWN, MixedBalanceError, ensure_single_balance, is_unknown
from luna.rules import GameRules, validate_team

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "data" / "fixtures"


@pytest.fixture
def cat():
    return Catalog.load(FIX / "synthetic_catalog.json")


@pytest.fixture
def rules():
    return GameRules.from_kb(KnowledgeBase.load(FIX), "SYNTHETIC")


def asm(**kw):
    a = AssumptionSet.preset("exploratory_v1")
    a.values.update(kw)
    return a


def full_team(cat, **kw):
    ids = ["s_striker", "s_mage", "s_tank", "s_healer", "s_reviver", "s_controller"]
    heroes = []
    for i, h in enumerate(ids):
        hb = hero_from_catalog(cat, h)
        hb.sigils = [{"id": "sig_a", "talents": ["tal_power", "tal_guard"]}, {"id": "sig_b", "talents": ["tal_guard", "tal_power"]}]
        hb.talents = ["tal_swift", "tal_pierce"]
        hb.limbs = [f"limb_war_{p}" for p in range(4)]
        heroes.append(hb)
    t = Team(name="T", heroes=heroes, formation={h: i for i, h in enumerate(ids)}, region="SYNTHETIC",
             balance_version="fixture-1", runes=["rune_0", "rune_1", "rune_2", "rune_3"],
             princess_weapon=["pw_0", "pw_1", "pw_2", "pw_3"])
    for k, v in kw.items():
        setattr(t, k, v)
    return t


# ------------------------------------------------------------- provenance
def test_fact_requires_source():
    with pytest.raises(ValueError):
        Fact(key="x", value=1, region="RU", source=Source(url=""), confidence="low")


def test_synthetic_cannot_masquerade():
    with pytest.raises(ValueError):
        Fact(key="x", value=1, region="RU", source=Source(url="f"), confidence="synthetic")


def test_unknown_cannot_be_used_as_number():
    with pytest.raises(ValueError):
        float(UNKNOWN)
    with pytest.raises(ValueError):
        bool(UNKNOWN)
    assert is_unknown("UNKNOWN")


def test_mixed_balance_versions_rejected():
    a = Fact(key="k", value=1, region="JP", source=Source(url="u"), confidence="low", balance_version="1.0")
    b = Fact(key="k", value=2, region="RU", source=Source(url="u"), confidence="low", balance_version="1.0")
    with pytest.raises(MixedBalanceError):
        ensure_single_balance([a, b])


def test_seed_kb_loads_and_every_fact_has_source():
    kb = KnowledgeBase.load()
    assert len(kb.facts) > 30
    assert all(f.source.url for f in kb.facts)
    # the KB must not contain RU combat numbers it cannot source
    assert not kb.query("hero.kira.stat", region="RU")


def test_kb_never_falls_back_to_other_region():
    kb = KnowledgeBase.load()
    v, _ = kb.best("hero.vignette.panel.SPD", "RU")
    assert is_unknown(v)
    v, f = kb.best("hero.vignette.panel.SPD", "JP")
    assert v == 4677 and f.confidence.value == "low"


def test_localization():
    assert resolve_hero("Верафиэль") == "verafiel"
    assert resolve_hero("Монашка") == "seraphia"
    assert term("stat.SPD") == "СКР"
    assert label("stat.ATK").endswith("*(ATK)") or "*" in label("stat.ATK")  # generic translation flagged


# ------------------------------------------------------------- validator
def test_valid_team_passes(cat, rules):
    rep = validate_team(full_team(cat), cat, rules, stacking_assumptions={"power": "unique", "guard": "unique"})
    assert rep.ok, [str(i) for i in rep.issues if i.level == "ERROR"]


def test_too_many_sigils_and_talents(cat, rules):
    t = full_team(cat)
    t.heroes[0].sigils.append({"id": "sig_a", "talents": []})
    t.heroes[0].talents.append("tal_swift")
    rep = validate_team(t, cat, rules)
    assert rep.codes("ERROR").count("SLOT_COUNT") >= 2


def test_sigil_and_personal_talents_are_separate_systems(cat, rules):
    t = full_team(cat)
    t.heroes[0].talents = ["tal_power", "tal_swift"]           # sigil talent placed as personal
    t.heroes[1].sigils[0]["talents"] = ["tal_swift", "tal_guard"]  # personal talent placed in sigil
    rep = validate_team(t, cat, rules)
    assert rep.codes("ERROR").count("SYSTEM_MIX") == 2


def test_duplicate_effect_needs_stacking_assumption(cat, rules):
    t = full_team(cat)
    rep = validate_team(t, cat, rules)
    assert "DUPLICATE_EFFECT" in rep.codes("WARN")


def test_limb_position_and_team_rules(cat, rules):
    t = full_team(cat)
    t.heroes[0].limbs = ["limb_war_1", "limb_war_0", "limb_war_2", "limb_war_3"]
    t.heroes[1].hero_id = t.heroes[0].hero_id
    t.runes = t.runes[:3]
    rep = validate_team(t, cat, rules)
    codes = rep.codes()
    assert "WRONG_POSITION" in codes and "DUPLICATE_HERO" in codes and "SLOT_COUNT" in codes


def test_pet_slots_by_rarity(cat, rules):
    t = full_team(cat)
    t.heroes[0].pets = ["pet_owl", "pet_owl", "pet_owl"]
    rep = validate_team(t, cat, rules)
    assert any(i.code == "SLOT_COUNT" and "питомц" in i.message for i in rep.issues)


def test_global_stats_double_count_detected(cat, rules):
    g = {"stat": "ATK", "value": 100, "source_id": "guild_buff"}
    t = full_team(cat, global_stats=[g, dict(g)])
    t.heroes[0].extra_mods = [dict(g, layer="team")]
    rep = validate_team(t, cat, rules)
    assert rep.codes("ERROR").count("GLOBAL_DOUBLED") >= 1 and "GLOBAL_IN_PERSONAL" in rep.codes("ERROR")


def test_inventory_constraint(cat, rules):
    rep = validate_team(full_team(cat), cat, rules, inventory={"sigils:sig_a": 1})
    assert "NOT_OWNED" in rep.codes("ERROR")


def test_region_mismatch(cat, rules):
    t = full_team(cat, region="RU")
    assert "MIXED_BALANCE" in validate_team(t, cat, rules).codes("ERROR")


# ------------------------------------------------------------- stat layers
def test_global_stat_applied_exactly_once(cat):
    t = full_team(cat, global_stats=[{"stat": "DEF", "value": 1000, "source_id": "g"}], runes=[], princess_weapon=[])
    for h in t.heroes:
        h.sigils, h.talents, h.limbs = [], [], []
    units = build_units(t, cat, "A", asm())
    striker = units[0]
    assert striker.stats["DEF"] == pytest.approx(300 + 1000)


def test_panel_stats_do_not_add_items_and_respect_team_assumption(cat):
    t = full_team(cat, global_stats=[{"stat": "DEF", "value": 1000, "source_id": "g"}], runes=[], princess_weapon=[])
    for h in t.heroes:
        h.stats_mode = "panel"
    u = build_units(t, cat, "A", asm(**{"stat.panel_includes_team": True}))[0]
    assert u.stats["HP"] == pytest.approx(10000) and u.stats["DEF"] == pytest.approx(300)
    u = build_units(t, cat, "A", asm(**{"stat.panel_includes_team": False}))[0]
    assert u.stats["DEF"] == pytest.approx(1300) and u.stats["HP"] == pytest.approx(10000)
    with pytest.raises(AssumptionRequired):
        build_units(t, cat, "A", AssumptionSet())


def test_duplicate_talent_mods_follow_policy(cat):
    t = full_team(cat, runes=[], princess_weapon=[])
    for h in t.heroes:
        h.sigils = [{"id": "sig_a", "talents": ["tal_power", "tal_power_b"]}]
        h.talents, h.limbs = [], []
    a_unique = AssumptionSet.preset("exploratory_v1", stacking={"power": "unique"})
    a_stack = AssumptionSet.preset("exploratory_v1", stacking={"power": "stack"})
    u1 = build_units(t, cat, "A", a_unique)[0]
    u2 = build_units(t, cat, "A", a_stack)[0]
    # (1000 + 100 [+100]) * 1.05 (sig_a)
    assert u1.stats["ATK"] == pytest.approx(1100 * 1.05)
    assert u2.stats["ATK"] == pytest.approx(1200 * 1.05)


def test_limb_sets_2_and_4(cat):
    t = full_team(cat, runes=[], princess_weapon=[])
    for h in t.heroes:
        h.sigils, h.talents = [], []
    t.heroes[0].limbs = ["limb_war_0", "limb_war_1", "limb_life_2", "limb_life_3"]
    u = build_units(t, cat, "A", asm())
    assert u[0].stats["CRIT"] == pytest.approx(0.2)          # no 4-set
    assert u[0].stats["HP"] == pytest.approx((10000 + 2000) * 1.10)
    assert u[1].stats["CRIT"] == pytest.approx(0.1)          # s_mage: war 4-set gives +0.1 (base 0)


def test_princess_weapon_resonance_and_runes(cat):
    t = full_team(cat)
    for h in t.heroes:
        h.sigils, h.talents, h.limbs = [], [], []
    units = build_units(t, cat, "A", asm())
    assert units[0].stats["SPD"] == pytest.approx(123)        # 120 + resonance 3
    ts = units[-1]
    assert ts.is_team_source and [a["id"] for a in ts.abilities][:4] == ["rune:rune_0", "rune:rune_1", "rune:rune_2", "rune:rune_3"]
    t.princess_weapon = ["pw_0", "pw_1", "pw_2", None]
    units = build_units(t, cat, "A", asm())
    assert units[0].stats["SPD"] == pytest.approx(120)


def test_faction_and_charm_combo(cat):
    t = full_team(cat, runes=[], princess_weapon=[])
    for h in t.heroes:
        h.sigils, h.talents, h.limbs = [], [], []
    t.heroes[0].charm_cards = ["card_a", "card_b"]
    t.heroes[5].hero_id = "s_bruiser"; t.formation["s_bruiser"] = 5
    units = build_units(t, cat, "A", asm())
    assert units[0].stats["DEF"] == pytest.approx(340)        # combo_ab
    assert units[0].stats["ATK"] == pytest.approx((1000 + 30) * 1.05)   # f_dark x2 -> +5% for all


def test_unknown_stats_need_prior(cat):
    t = full_team(cat, runes=[], princess_weapon=[])
    t.heroes[0].stats["ATK"] = UNKNOWN
    with pytest.raises(UnknownStatError):
        build_units(t, cat, "A", asm())
    a = asm()
    units = build_units(t, cat, "A", a, stat_fill=lambda h, s: 777)
    assert "prior:s_striker.ATK" in a.used


def test_team_roundtrip(tmp_path, cat):
    t = full_team(cat)
    t.heroes[0].stats["ATK"] = UNKNOWN
    p = tmp_path / "t.json"
    t.save(p)
    t2 = Team.load(p)
    assert is_unknown(t2.heroes[0].stats["ATK"]) and t2.to_dict() == t.to_dict()


def test_catalog_merge_refuses_mixed_versions(cat):
    other = Catalog(region="RU", balance_version="x")
    with pytest.raises(MixedBalanceError):
        Catalog.merge(cat, other)


def test_catalog_entries_have_provenance(cat):
    assert cat.unsourced_entries() == []
