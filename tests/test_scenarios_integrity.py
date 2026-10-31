"""Integrity checks for completion criteria: no invented RU numbers, model vs real separation, stage-9 setup."""
import json
from pathlib import Path

from luna import scenarios as S
from luna.engine.assumptions import REGISTRY
from luna.kb import KnowledgeBase
from luna.model import Catalog
from luna.provenance import Region
from luna.sim.montecarlo import simulate

ROOT = Path(__file__).resolve().parents[1]


def test_ru_catalog_has_no_unsourced_numbers():
    cat = Catalog.load(ROOT / "data" / "kb" / "catalog_RU.json")
    assert cat.unsourced_entries() == []
    for h in cat.sections["heroes"].values():   # currently empty; if filled, stats need sources
        assert h.get("provenance", {}).get("source")


def test_kb_has_no_ru_combat_numbers_without_source():
    kb = KnowledgeBase.load()
    ru_stats = [f for f in kb.query("hero.", region="RU") if ".stat." in f.key or ".panel." in f.key]
    assert all(f.source.url and f.confidence.value != "hypothesis" for f in ru_stats)


def test_other_region_numbers_never_leak_into_ru():
    kb = KnowledgeBase.load()
    jp = {f.key for f in kb.query("hero.", region="JP") if ".panel." in f.key}
    ru = {f.key for f in kb.query("hero.", region="RU")}
    assert jp and not (jp & ru)


def test_whatif_catalog_is_labelled_and_kits_are_hypothesis():
    cat = S.whatif_catalog()
    assert cat.balance_version.startswith("what-if")
    assert all(h["provenance"]["confidence"] == "hypothesis" for h in cat.sections["heroes"].values())
    assert all(v == "UNKNOWN" for h in cat.sections["heroes"].values() for v in h["base_stats"].values())
    assert cat.get("heroes", "verafiel")["role"] == "support"


def test_team_compositions_from_brief():
    assert S.TEAM_A == ["hymelle", "lucifer", "klim", "seneren", "vignette", "kira"]
    assert S.TEAM_B == ["illusia", "kira", "verafiel", "seneren", "lucifer", "chloe"]
    t = S.team("A", S.TEAM_A)
    assert t.status == "hypothetical" and "NOT" in t.notes


def test_soul_eater_is_blocked_not_invented():
    h = S.hypotheses(S.whatif_catalog())["H6_soul_eater"]
    assert "blocked" in h and "apply" not in h


def test_model_results_are_labelled():
    cat = S.whatif_catalog()
    s = simulate(S.team("A", S.TEAM_A), S.team("B", S.TEAM_B), cat, S.VARIANTS["v1/kill-first"], n=8, seed=1,
                 priors=S.default_priors(), workers=1)
    assert "model_win_rate" in s and "win_rate" not in s and "MODEL" in s["label"]
    assert any(a.startswith("prior:") for a in s["assumptions_used"])


def test_critical_assumptions_have_no_default():
    crit = [a for a in REGISTRY.values() if a.critical]
    assert {a.id for a in crit} >= {"stack.duplicate_effect", "extra.timing", "extra.combo_chain_max", "stat.panel_includes_team"}
    assert all(a.default is None for a in crit)


def test_install_artifacts_present():
    for p in ["docs/ASSUMPTIONS.md", "reports/stage9/README.md", "third_party_licenses/gamedev-skills.LICENSE",
              "third_party_licenses/combinatorial-optimization-skills.LICENSE"]:
        assert (ROOT / p).exists(), p
