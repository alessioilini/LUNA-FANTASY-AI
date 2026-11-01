"""Orchestrates the plan workbook: votes -> model -> scores -> CP-SAT assignments -> XLSX."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import model as M
from . import score as S
from . import terms as T
from .votes import TEAM, collect_all

ROOT = Path(__file__).resolve().parents[2]


def team_from_file(path: str | Path | None = None) -> tuple[str, list[str]]:
    p = Path(path or ROOT / "data/user/teams/main.json")
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("name", p.stem), [h["hero_id"].split(":", 1)[-1] for h in d["heroes"]]


def hero_names() -> dict[str, str]:
    out = {}
    for _, (slug, title) in T.hero_index().items():
        out.setdefault(slug, title)
    for x in json.loads((ROOT / "data/glossary.json").read_text(encoding="utf-8"))["entries"]:
        if x.get("category") in ("hero", "heroine", "character") and x.get("ru"):
            out.setdefault(x["key"].split(".", 1)[1], x["ru"])
    for line in (ROOT / "data/kb/approvals/decisions.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line) if line.strip() else {}
        if d.get("topic") == "ru_names" and isinstance(d.get("answer"), dict):     # operator-approved RU names
            for k, ru in d["answer"].items():
                out.setdefault(k.split(":", 1)[-1], ru)
    out.setdefault("chara050", "Морозная Дымка")                                      # decision P8
    for c in json.loads((ROOT / "data/kb/sbg/characters.json").read_text(encoding="utf-8")):
        if c.get("name_jp"):
            out.setdefault(c["slug"], f"{c['name_jp']} (JP, RU-имя не подтверждено)")
    out.update({"seneren": "Сеньерен", "hymelle": "Мяоинь", "nurse-girl": "Верафиэль", "yuki": "Юки Юки",
                "teselien": "Тессарион", "kira": "Кира", "chloe": "Хлоя", "kurimu": "Клим", TEAM: "Команда"})
    return out


def panel_spd(hero: str) -> float | None:
    from ..kits.catalog import operator_panel
    op = operator_panel(M.kit_id(hero))
    return op["stats"].get("SPD") if op else None


def roster() -> dict[str, dict]:
    r = json.loads((ROOT / "data/user/roster.json").read_text(encoding="utf-8"))
    return {h["hero_id"].split(":", 1)[-1]: h["progression"] for h in r["heroes"]}


def run(team_file=None, model_n: int = 600, use_model: bool = True, today: dt.date | None = None, progress=print) -> dict:
    today = today or dt.date.today()
    team_name, team = team_from_file(team_file)
    w = S.weights()
    progress(f"Команда «{team_name}»: {', '.join(team)}")
    votes = collect_all(team)
    progress(f"Голосов собрано: {len(votes)}")
    # limb candidates of team heroines for the model
    limb_c = {h: sorted({v["cand"] for v in votes if v["hero"] == h and v["cat"] == "limb"}) for h in team}
    mres = {"status": "disabled", "limb": {}, "kit": {}}
    if use_model:
        progress(f"Модель: парные прогоны по {model_n} боёв")
        mres = M.run(team, limb_c, n=model_n)
    model_vals, model_sig = {}, {}
    for k, r in mres.get("limb", {}).items():
        h, limb = k.split("|", 1)
        model_vals[(h, "limb", limb)] = r["delta"]
        model_sig[(h, "limb", limb)] = 1 if (r["ci95"][0] > 0 or r["ci95"][1] < 0) else 0
    eligible = {k: v for k, v in model_vals.items() if model_sig[k] == 1}
    cands = S.candidates(votes, w, today, eligible)
    for c in cands:
        k = (c["hero"], c["cat"], c["cand"])
        c["model_raw"] = model_vals.get(k)
        c["model_sig"] = model_sig.get(k)
    tiers = S.hero_tiers(votes, w, today)
    rarity = {}
    for x in T.entities():
        if x["kind"] == "pet":
            rarity[x["id"].split(":", 1)[1]] = next((r for r in w["pet_cap"] if (x.get("subtitle") or "").startswith(r)), "")
    cards = S.assign_cards(cands, team)
    pets = S.assign_pets(cands, team, rarity, w)
    order = sorted(team, key=lambda h: -(panel_spd(h) or -1))
    return {"today": today, "team_name": team_name, "team": team, "order": order, "weights": w, "votes": votes,
            "cands": cands, "tiers": tiers, "model": mres, "cards": cards, "pets": pets, "rarity": rarity,
            "names": hero_names(), "roster": roster(), "spd": {h: panel_spd(h) for h in team}}


def main(argv=None):
    import argparse
    from .xlsx import write
    ap = argparse.ArgumentParser(description="Excel plan for a team: build recommendations weighted by sources and model")
    ap.add_argument("--team", help="team JSON (default data/user/teams/main.json)")
    ap.add_argument("--out", help="output .xlsx")
    ap.add_argument("--model-n", type=int, default=600)
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--today", help="YYYY-MM-DD (date used for source recency)")
    a = ap.parse_args(argv)
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    res = run(a.team, a.model_n, not a.no_model, today)
    out = Path(a.out or ROOT / f"reports/planbook/Luna_planbook_{today.isoformat()}.xlsx")
    write(res, out)
    print(f"Готово: {out}")
    return out


if __name__ == "__main__":
    main()
