"""Structure checks for the 2026-11-01 import (screenshots, XLSX plans, ChatGPT knowledge base)."""
import json
from pathlib import Path

from luna.kb import KnowledgeBase
from luna.provenance import Fact

ROOT = Path(__file__).resolve().parents[1]


def rows(name):
    return [json.loads(l) for l in (ROOT / "data/kb/facts" / name).read_text(encoding="utf-8").splitlines() if l.strip()]


def test_panel_facts_valid_and_verified():
    r = rows("RU.observed.jsonl")
    assert len(r) == 100
    for d in r:
        f = Fact.from_dict(d)
        assert f.ru_status.value == "verified_in_ru_client" and f.source.kind == "screenshot"
        assert (ROOT / f.source.url.split(":", 1)[1]).exists()


def test_chatgpt_facts_statuses_and_ranking():
    r = rows("RU.chatgpt.jsonl")
    assert all("import_status=" in d["notes"] for d in r)
    allowed = {"user_stated", "hypothesis", "low"}
    assert {d["confidence"] for d in r} <= allowed
    hist = [d for d in r if "ASSISTANT_HISTORICAL" in d["notes"]]
    assert hist and all(d["confidence"] == "hypothesis" for d in hist)
    assert any("FICTIONAL_GAME_DESIGN" in d["notes"] for d in r)


def test_historical_never_overrides_verified():
    kb = KnowledgeBase.load()
    v, f = kb.best("hero.illusia.panel_ru.SPD", "RU")
    assert v == 12992 and f.ru_status.value == "verified_in_ru_client"
    v, f = kb.best("hero.sbg:hymelle.name.ru", "RU")
    assert v == "Мяоинь"


def test_xlsx_dump_has_dates_and_status():
    books = json.loads((ROOT / "data/kb/imports/chatgpt/xlsx_dump.json").read_text(encoding="utf-8"))
    assert len(books) == 4 and all(b["status"] == "ASSISTANT_HISTORICAL" and b["plan_date"] for b in books)


def test_operator_panel_used_for_stats():
    from luna.engine.assumptions import AssumptionSet
    from luna.kits.catalog import build_catalog
    cat = build_catalog({"illusia": 24}, AssumptionSet.preset("exploratory_v1"), heroes=["illusia"])
    st = cat.get("heroes", "illusia")["base_stats"]
    assert st["SPD"] == 12992 and abs(st["DR"] - 0.637) < 1e-9


def test_soul_thief_talent_bans_revive():
    from luna.engine.assumptions import AssumptionSet
    from luna.engine.battle import Battle
    from luna.engine.resolve import build_units
    from luna.kits.catalog import build_catalog, team_from
    asm = AssumptionSet.preset("exploratory_v1", **{"talent.soul_thief_chance": 1.0, "kit.stat_sample": "sbg_lv350_panel"})
    cat = build_catalog({"lucifer": 24, "vinette": 14}, asm, heroes=["lucifer", "vinette"])
    a = team_from(cat, "A", ["lucifer"])
    a.heroes[0].talents = ["soul_thief"]
    b = Battle(build_units(a, cat, "A", asm), build_units(team_from(cat, "B", ["vinette"]), cat, "B", asm), asm, seed=1)
    r = b.run()
    assert any(e["t"] == "status" and e.get("key") == "soul_thief_ban" for e in r.log)
