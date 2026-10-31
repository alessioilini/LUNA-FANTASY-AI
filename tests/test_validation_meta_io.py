import json
from pathlib import Path

import pytest

import luna.meta as meta
import luna.validation as V
from luna import collector, resources
from luna.export import export
from luna.kb import KnowledgeBase
from luna.provenance import Fact

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(V, "RECORDS", tmp_path / "battles.jsonl")
    monkeypatch.setattr(V, "JOURNAL", tmp_path / "j.jsonl")
    monkeypatch.setattr(V, "EVIDENCE", tmp_path / "ev")
    monkeypatch.setattr(V, "CLAIMS", tmp_path / "claims.jsonl")
    monkeypatch.setattr(collector, "PENDING", tmp_path / "pending")
    return tmp_path


# ------------------------------------------------------------------ validation imports
def test_import_csv_ru_headers(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("Дата,Режим,Результат,Раунды,Моя команда,Соперник\n2026-10-01,PvP,Победа,5,Верафиэль; Монашка,Lucifer\n", encoding="utf-8")
    recs = V.import_table(p)
    assert recs[0]["result"] == "win" and recs[0]["rounds"] == 5
    assert recs[0]["my_team"] == ["verafiel", "seraphia"] and recs[0]["enemy_team"] == ["lucifer"]


def test_import_xlsx(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["date", "result", "my_team", "enemy_team"])
    ws.append(["2026-10-02", "loss", "Kira", "Vignette"])
    p = tmp_path / "h.xlsx"
    wb.save(p)
    recs = V.import_table(p)
    assert recs[0]["result"] == "loss" and recs[0]["enemy_team"] == ["vignette"]


def test_import_markdown_claims(tmp_path):
    p = tmp_path / "old.md"
    p.write_text("# Old\n- Верафиэль лучше всего на второй позиции\n- short\n", encoding="utf-8")
    c = V.import_markdown(p)
    assert len(c) == 1 and c[0]["heroes"] == ["verafiel"] and c[0]["status"] == "unverified_old_recommendation"


def test_screenshot_registration(tmp_path):
    p = tmp_path / "s.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    t = V.register_screenshot(p, hero_hint="kira")
    assert t["status"] == "needs_transcription" and t["ocr"] == "not_available"


def test_chronological_split_and_calibration_guard():
    recs = [{"id": i, "date": f"2026-10-{i + 1:02d}"} for i in range(10)]
    tr, te = V.split_train_test(recs, 0.3)
    assert max(r["date"] for r in tr) < min(r["date"] for r in te)
    from luna.engine.assumptions import AssumptionSet
    from luna.model import Catalog
    r = V.calibrate(Catalog(), AssumptionSet.preset("exploratory_v1"), {"dmg.k_def": [1, 2]}, records=[])
    assert r["status"] == "insufficient_data"


def test_calibration_runs_on_train_and_reports_test():
    from luna.engine.assumptions import AssumptionSet
    from luna.model import Catalog, Team, hero_from_catalog
    cat = Catalog.load(ROOT / "data" / "fixtures" / "synthetic_catalog.json")
    def t(ids):
        return Team(name="x", heroes=[hero_from_catalog(cat, h) for h in ids], region="SYNTHETIC", balance_version="fixture-1").to_dict()
    recs = [{"id": i, "date": f"2026-09-{i + 1:02d}", "result": "win" if i % 3 else "loss",
             "my_team": t(["s_striker", "s_tank"]), "enemy_team": t(["s_bruiser", "s_healer"])} for i in range(12)]
    r = V.calibrate(cat, AssumptionSet.preset("exploratory_v1"), {"dmg.k_def": [5000, 20000]}, records=recs, n=6)
    assert r["status"] == "ok" and r["train_size"] + r["test_size"] == 12 and r["simulator_validated"] is False


def test_discrepancy_journal():
    e = V.log_discrepancy({"id": "b1", "result": "win", "rounds": 4}, {"model_win_rate": 0.7, "avg_rounds": 5})
    assert e["brier"] == pytest.approx(0.09)
    assert V.status()["journal_entries"] == 1


# ------------------------------------------------------------------ meta
def test_meta_rules(tmp_path):
    p = tmp_path / "m.jsonl"
    meta.add({"region": "JP", "kind": "new_hero", "subject": "x", "status": "community", "source": "u"}, p)
    assert meta.load(p)[0]["ru_available"] is False
    with pytest.raises(meta.MetaError):
        meta.add({"region": "JP", "kind": "new_hero", "subject": "y", "status": "community", "source": "u", "ru_available": True}, p)
    with pytest.raises(meta.MetaError):
        meta.add({"region": "RU", "kind": "combo", "subject": "z", "status": "community"}, p)
    assert meta.forecast_ru(p)[0]["status"] == "hypothesis"


def test_meta_region_diff():
    d = meta.region_diff(KnowledgeBase.load())
    assert any(r["hero"] == "vignette" and r["missing_in_RU"] for r in d["rows"])


# ------------------------------------------------------------------ collector
HTML = """<html><head><title>Кира | Luna Fantasy</title></head><body><h1>Кира</h1>
<table><tr><th>Атака</th><td>12 345</td></tr><tr><th>Здоровье</th><td>98 765</td></tr>
<tr><th>СКР</th><td>4 321</td></tr><tr><th>Шанс крит. удара</th><td>15%</td></tr></table></body></html>"""


def test_parse_page_extracts_ru_stats():
    p = collector.parse_page(HTML, "https://lunafantasy.ru/x", "RU")
    assert p["title"] == "Кира"
    assert p["stats"] == {"ATK": 12345.0, "HP": 98765.0, "SPD": 4321.0, "CRIT": pytest.approx(0.15)}
    facts = collector.to_pending_facts(p, "kira", "https://lunafantasy.ru/x")
    assert all(Fact.from_dict(f).source.url for f in facts)


def test_offline_ingest(tmp_path):
    d = tmp_path / "saved"
    d.mkdir()
    (d / "kira.html").write_text(HTML, encoding="utf-8")
    r = collector.ingest_offline_dir(d)
    assert r["pages"] == 1 and r["pending_facts"] == 4


def test_manual_csv_import(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("hero_id,name_ru,stat,value,level,stars,source_url,date,confidence\n"
                 "kira,Кира,ATK,\"12,345\",240,5,https://lunafantasy.ru/kira,2026-10-31,high\n", encoding="utf-8")
    f = collector.import_hero_csv(p)[0]
    fact = Fact.from_dict(f)
    assert fact.value == 12345 and fact.region.value == "RU"


# ------------------------------------------------------------------ export & resources
def test_export_formats(tmp_path):
    rep = {"title": "t", "model_win_rate": 0.5, "rows": [{"a": 1, "b": "x"}], "heroes": {"A:x": {"dmg": 1.0}}}
    assert export(rep, tmp_path / "r.xlsx")[0].endswith(".xlsx")
    assert len(export(rep, tmp_path / "r.csv")) >= 2
    h = export(rep, tmp_path / "r.html")[0]
    assert "Модельные" in Path(h).read_text(encoding="utf-8")


def test_resource_plan_knapsack():
    ups = [{"id": "a", "cost": {"gold": 60}, "gain": 0.05}, {"id": "b", "cost": {"gold": 50}, "gain": 0.04},
           {"id": "c", "cost": {"gold": 50}, "gain": 0.03}, {"id": "d", "cost": {"gold": "UNKNOWN"}, "gain": 0.5}]
    r = resources.plan(ups, {"gold": 100})
    assert set(r["chosen"]) == {"b", "c"} and r["cost_unknown"] == ["d"]
    sched = resources.long_term(ups[:3], {"gold": 0}, {"gold": 10}, 30)
    assert sched and sched[0]["day"] >= 5
