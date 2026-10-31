"""Dashboard server (stage 12): HTTP API smoke tests with stdlib urllib only.

The server runs in a background thread on a free port; saved teams go to a temporary directory so the
user's data/user/teams is never touched.
"""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from luna.dashboard.server import make_server
from luna.model import Catalog, Team, hero_from_catalog
from luna.kb import ROOT

TEAM_A = ["s_striker", "s_mage", "s_tank", "s_healer", "s_reviver", "s_controller"]
TEAM_B = ["s_tank", "s_bruiser", "s_reviver", "s_healer", "s_mage", "s_controller"]


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    srv = make_server("127.0.0.1", 0, teams_dir=tmp_path_factory.mktemp("teams"))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return r.status, r.headers, r.read()


def _post(base, path, body, method="POST"):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _team(name, ids):
    cat = Catalog.load(ROOT / "data" / "fixtures" / "synthetic_catalog.json")
    t = Team(name=name, heroes=[hero_from_catalog(cat, h) for h in ids], formation={h: i for i, h in enumerate(ids)},
             region="SYNTHETIC", balance_version="fixture-1")
    return t.to_dict()


def test_index_served(base):
    status, headers, body = _get(base, "/")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    html = body.decode("utf-8")
    assert "/static/app.js" in html and "Luna Fantasy AI" in html
    status, _, js = _get(base, "/static/app.js")
    assert status == 200 and b"Battle Simulator" in js and b"Counterpick Matrix" in js


def test_catalogs(base):
    status, _, body = _get(base, "/api/catalogs")
    assert status == 200
    cats = {c["id"]: c for c in json.loads(body)}
    assert {"ru", "whatif", "synthetic"} <= set(cats)
    assert cats["ru"]["empty"] is False and cats["ru"]["heroes"] > 0   # lunafantasy.ru snapshot imported
    assert cats["synthetic"]["region"] == "SYNTHETIC" and cats["synthetic"]["heroes"] > 0
    assert cats["whatif"]["kind"] == "whatif"


def test_battle_returns_winner(base):
    body = {"team_a": _team("A", TEAM_A), "team_b": _team("B", TEAM_B), "catalog": "synthetic",
            "preset": "exploratory_v1", "seed": 3}
    status, _, raw = _post(base, "/api/battle", body)
    assert status == 200, raw
    rep = json.loads(raw)
    assert rep["winner"] in ("A", "B", "draw")
    assert rep["label"].startswith("MODEL")
    assert len([u for u in rep["units"] if u["hero"] != "__team__"]) == 12
    # a decisive tie-break assumption must yield A or B
    body["overrides"] = {"battle.draw_result": "hp_percent"}
    rep = json.loads(_post(base, "/api/battle", body)[2])
    assert rep["winner"] in ("A", "B")


def test_sim_n50(base):
    body = {"team_a": _team("A", TEAM_A), "team_b": _team("B", TEAM_B), "catalog": "synthetic", "n": 50, "seed": 1}
    status, _, raw = _post(base, "/api/sim", body)
    assert status == 200, raw
    s = json.loads(raw)
    assert s["n"] == 50 and s["wins"] + s["losses"] + s["draws"] == 50
    assert 0.0 <= s["model_win_rate"] <= 1.0 and len(s["ci95"]) == 2
    assert "MODEL" in s["label"]


def test_export_xlsx_is_zip(base):
    rep = {"label": "test", "rows": [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]}
    status, headers, raw = _post(base, "/api/export", {"report": rep, "fmt": "xlsx", "name": "t"})
    assert status == 200
    assert raw[:2] == b"PK"
    assert "attachment" in headers["Content-Disposition"]
    status, headers, raw = _post(base, "/api/export", {"report": rep, "fmt": "csv"})
    assert status == 200 and raw[:2] == b"PK" and headers["Content-Type"] == "application/zip"


def test_team_save_load_roundtrip(base):
    team = _team("Тестовая команда / 1", TEAM_A)
    team["runes"] = ["rune_0", "rune_1"]
    team["heroes"][0]["sigils"] = [{"id": "sig_a", "talents": ["tal_power", "tal_guard"]}]
    status, _, raw = _post(base, "/api/teams", {"team": team})
    assert status == 200, raw
    saved = json.loads(raw)["saved"]
    assert "/" not in saved and ".." not in saved
    names = [t["name"] for t in json.loads(_get(base, "/api/teams")[2])]
    assert saved in names
    status, _, raw = _get(base, "/api/teams/" + urllib.parse.quote(saved))
    assert status == 200
    assert json.loads(raw) == team
    status, _, _ = _post(base, "/api/teams/" + urllib.parse.quote(saved), {}, method="DELETE")
    assert status == 200


def test_errors_are_json(base):
    status, _, raw = _post(base, "/api/battle", {"team_a": _team("A", TEAM_A), "team_b": _team("B", TEAM_B), "catalog": "nope"})
    assert status == 400 and "error" in json.loads(raw)
    status, _, raw = _post(base, "/api/validate", {"team": {"heroes": [{"stats": {}}]}, "catalog": "synthetic"})
    assert status == 400 and "error" in json.loads(raw)
    try:
        _get(base, "/static/../server.py")
        assert False, "path traversal must not be served"
    except urllib.error.HTTPError as e:
        assert e.code == 404
