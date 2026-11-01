"""Plan workbook: JP guide parsing, name mapping, vote weights, ranking, CP-SAT constraints, XLSX formulas."""
import datetime as dt
import glob
import json
import subprocess
import sys
from pathlib import Path

import pytest

from luna.collector.appmedia import parse
from luna.planbook import score as S
from luna.planbook import terms as T
from luna.planbook.votes import _sbg_talent_line

TODAY = dt.date(2026, 11, 1)

# minimal page with the same block structure as an AppMedia heroine page (synthetic text)
PAGE = """<html><head><title>【ヤバ少女】テストの評価とおすすめ刻印・戒魔 | AppMedia</title>
<script type="application/ld+json">{"datePublished":"2025-05-09T10:00:00+09:00","dateModified":"2025-06-02T10:00:00+09:00"}</script></head>
<body><h2>テストの評価とステータス</h2><div></div><table><tr><th>テストの評価</th><td>SS</td></tr></table>
<h2>テストのおすすめ刻印・タレント</h2><table><tr><th colspan="2">おすすめ刻印</th></tr>
<tr><td><div>魔法連擊</div></td><td>理由</td></tr><tr><td><div>強欲</div></td><td>理由</td></tr>
<tr><th colspan="2">候補</th></tr><tr><td><div>解除</div></td><td>理由</td></tr></table>
<h3>おすすめ戒魔</h3><table><tr><th>戒魔セット</th><th>評価</th></tr>
<tr><td><a href="#">奇夢うさぎ</a></td><td>【おすすめ度】★★★★★</td></tr><tr><td><a href="#">芳草</a></td><td>★★★★☆</td></tr></table>
<table><tr><th>スロット1・3</th></tr><tr><td>ATK / SPD</td></tr><tr><th>スロット2・4</th></tr><tr><td>被回復率 / 物理ダメ軽減</td></tr></table>
<h2>テストのおすすめペット</h2><table><tr><th colspan="3">ペットおすすめ</th></tr>
<tr><td><a href="#">夢女魅る枕</a></td><td><a href="#">スターユニコーン</a></td><td>-</td></tr></table></body></html>"""


def test_appmedia_parse_blocks():
    p = parse(PAGE, "https://appmedia.jp/yabasyoujyo/1")
    assert p["tier"] == "SS" and p["date_modified"] == "2025-06-02"
    assert [(t["name_jp"], t["group"], t["pos"]) for t in p["talents"]] == [
        ("魔法連擊", "main", 1), ("強欲", "main", 2), ("解除", "candidate", 1)]
    assert [(lb["name_jp"], lb["stars"], lb["stars_max"]) for lb in p["limbs"]] == [("奇夢うさぎ", 5, 5), ("芳草", 4, 5)]
    assert p["substats"] == {"スロット1・3": ["ATK", "SPD"], "スロット2・4": ["被回復率", "物理ダメ軽減"]}
    assert [x["name_jp"] for x in p["pets"]] == ["夢女魅る枕", "スターユニコーン"]          # '-' placeholder dropped


def test_sbg_marks_and_priority_chains():
    got = _sbg_talent_line("◎推奨：生命力 強靭 庇護、迅速 ◯推奨：神の赦し ☓非推奨：吸収")
    assert ("生命力", "main", 1) in got and ("神の赦し", "candidate", 1) in got and ("吸収", "avoid", 1) in got
    chain = _sbg_talent_line("現環境推奨：庇護、強靭 ＞減速、戒律")
    assert ("庇護", "main", 1) in chain and ("戒律", "candidate", 2) in chain


def test_term_mapping_keeps_status_and_never_merges_unknowns():
    assert T.talent_from_jp("魔法連擊")[:2] == ("Маг комбо", "lfru_alias")
    assert T.talent_from_jp("迅速")[1] == "hypothesis"            # Ловкость vs Быстрота: operator approval
    name, st, _ = T.talent_from_jp("謎の刻印")
    assert st == "unmapped" and name == "謎の刻印"
    assert T.limb_from_jp("幻蝶")[:3] == ("limb_set_genchou", "Кольцо миражей", "lfru_alias")
    assert T.hero_from_name("Иллюсия +")[0] == "illusia" and T.hero_from_name("Сеньерен")[0] == "seneren"


def v(hero="h", cat="sigil", cand="A", src="sbg", date="2026-11-01", group="main", pos=1, rating=None, st="lfru_alias"):
    return {"hero": hero, "cat": cat, "cand": cand, "name_ru": cand, "name_orig": cand, "source": src, "date": date,
            "group": group, "pos": pos, "rating": rating, "map_status": st, "note": "", "url": ""}


def test_vote_weight_formula():
    w = S.weights()
    vw, base = S.vote_weight(v(src="appmedia", date="2025-11-01", group="candidate", pos=3, rating=0.8, st="hypothesis"), w, TODAY)
    expect_base = 1.0 * 0.6 * 0.75 * (1 / (1 + 0.15 * 2)) * max(0.3, 0.5 ** (365 / 365))
    assert base == pytest.approx(expect_base) and vw == pytest.approx(expect_base * 0.8)
    assert S.vote_weight(v(group="avoid"), w, TODAY)[0] < 0


def test_candidates_normalise_rank_and_blend_model():
    w = S.weights()
    votes = [v(cand="A"), v(cand="A", src="lfru"), v(cand="B"), v(cand="C", group="avoid")]
    cs = {c["cand"]: c for c in S.candidates(votes, w, TODAY)}
    assert cs["A"]["s_cons"] == 1.0 and cs["A"]["rank"] == 1 and cs["B"]["rank"] == 2 and cs["C"]["rank"] == 3
    cs = {c["cand"]: c for c in S.candidates(votes, w, TODAY, model={("h", "sigil", "B"): 0.2, ("h", "sigil", "A"): 0.0})}
    assert cs["B"]["s_model"] == 1.0 and cs["A"]["s_model"] == 0.0
    assert cs["B"]["final"] == pytest.approx(round((0.75 * cs["B"]["s_cons"] + 0.25) / 1.0, 6))


def test_tie_break_is_by_row_like_the_sheet():
    cs = S.candidates([v(cand="X"), v(cand="Y")], S.weights(), TODAY)
    assert sorted(c["rank"] for c in cs) == [1, 2]


def test_cpsat_cards_unique_and_pet_caps():
    w = S.weights()
    votes = [v(hero=h, cat="card", cand="queen") for h in ("a", "b")] + [v(hero="b", cat="card", cand="maid", pos=3)]
    cards = S.assign_cards(S.candidates(votes, w, TODAY), ["a", "b"])
    assert {cards["a"]["cand"], cards["b"]["cand"]} == {"queen", "maid"}
    pv = [v(hero=h, cat="pet", cand=p, pos=i) for h in ("a", "b", "c") for i, p in enumerate(["p1", "p2", "p3", "p4", "p5"], 1)]
    w["pet_cap"] = {"Эпич": 2}
    pets = S.assign_pets(S.candidates(pv, w, TODAY), ["a", "b", "c"], {"p1": "Эпич"}, w)
    assert all(len(x) == 4 for x in pets.values())
    assert sum(1 for x in pets.values() for p in x if p["cand"] == "p1") <= 2


def _recalc_script():
    hits = glob.glob("/root/.claude/skills/**/xlsx/scripts/recalc.py", recursive=True)
    return hits[0] if hits else None


@pytest.mark.skipif(_recalc_script() is None, reason="LibreOffice recalc helper not available")
def test_workbook_formulas_equal_python(tmp_path):
    from openpyxl import load_workbook
    from luna.planbook import build as B
    from luna.planbook.xlsx import write
    res = B.run(use_model=False, today=TODAY, progress=lambda *a: None)
    out = write(res, tmp_path / "pb.xlsx")
    r = json.loads(subprocess.run([sys.executable, _recalc_script(), str(out), "300"], capture_output=True, text=True).stdout)
    assert r["status"] == "success" and r["total_errors"] == 0
    ws = load_workbook(out, data_only=True)["Кандидаты"]
    py = {(c["hero"], c["cat"], c["cand"]): c for c in res["cands"]}
    for row in ws.iter_rows(min_row=2, values_only=True):
        c = py[(row[0], row[2], row[3])]
        assert row[14] == pytest.approx(c["final"], abs=1e-6) and row[15] == c["rank"]
