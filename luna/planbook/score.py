"""Weights and scoring - the Python twin of the workbook formulas (sheet «Веса» -> «Голоса» -> «Кандидаты»).

vote_w   = W_source * W_group * W_map * pos_f * rating_f * recency
pos_f    = 1 / (1 + gamma * (pos - 1))
recency  = max(floor, 0.5 ** (age_days / half_life))
cons     = sum of vote_w per (hero, category, candidate)
S_cons   = cons / max(cons over the same hero+category)          (0 if that max <= 0)
S_model  = (d - min d) / (max d - min d) over candidates of the hero+category that have a model value
           (0.5 if all model values are equal)
final    = S_cons                                   if no model value
         = (alpha * S_cons + beta * S_model) / (alpha + beta)  otherwise
Hero tier score = sum(w_base * tier_value) / sum(w_base) over 'tier' votes (w_base = vote_w without rating).
"""
from __future__ import annotations

import copy
import datetime as dt
from collections import defaultdict

from .votes import SOURCES, TEAM

DEFAULTS = {
    "source": {k: v[3] for k, v in SOURCES.items()},
    "group": {"main": 1.0, "list": 0.8, "candidate": 0.6, "avoid": -0.6},
    "map": {"lfru_alias": 1.0, "meaning": 0.95, "hypothesis": 0.75, "unmapped": 0.6},
    "tier": {"SSS": 1.0, "SS": 0.85, "S": 0.7, "A": 0.55, "B": 0.4, "C": 0.25, "D": 0.1},
    "gamma": 0.15, "half_life": 365.0, "recency_floor": 0.3, "alpha": 0.75, "beta": 0.25,
    "hero_w_tier": 0.6, "hero_w_model": 0.25, "hero_w_ready": 0.15,
    "pet_cap": {"Миф": 4, "Лег": 3, "Эпич": 2}, "pet_slots": 4, "accessory_slots": 8,
}


def weights(**over) -> dict:
    w = copy.deepcopy(DEFAULTS)
    for k, v in over.items():
        if isinstance(v, dict):
            w[k].update(v)
        else:
            w[k] = v
    return w


def vote_weight(v: dict, w: dict, today: dt.date) -> tuple[float, float]:
    """-> (vote_w, w_base) ; w_base excludes the rating factor (used for tier averages)."""
    age = (today - dt.date.fromisoformat(v["date"])).days
    rec = max(w["recency_floor"], 0.5 ** (age / w["half_life"]))
    pos_f = 1.0 / (1.0 + w["gamma"] * (v["pos"] - 1))
    base = w["source"][v["source"]] * w["group"][v["group"]] * w["map"][v["map_status"]] * pos_f * rec
    if v["cat"] == "tier":
        r = w["tier"].get(str(v["rating"]), 0.0)
    else:
        r = 1.0 if v["rating"] in (None, "") else float(v["rating"])
    return base * r, base


def candidates(votes: list[dict], w: dict, today: dt.date, model: dict | None = None) -> list[dict]:
    """Aggregate votes -> candidates with consensus, model and final score + rank (same tie-break as the sheet)."""
    model = model or {}
    agg: dict[tuple, dict] = {}
    for i, v in enumerate(votes):
        if v["cat"] == "tier":
            continue
        vw, _ = vote_weight(v, w, today)
        k = (v["hero"], v["cat"], v["cand"])
        c = agg.setdefault(k, {"hero": v["hero"], "cat": v["cat"], "cand": v["cand"], "name_ru": v["name_ru"],
                               "cons": 0.0, "n_votes": 0, "sources": set(), "map_status": v["map_status"]})
        c["cons"] += vw
        c["n_votes"] += 1
        c["sources"].add(v["source"])
    rows = sorted(agg.values(), key=lambda c: (c["hero"], c["cat"], c["cand"]))
    by = defaultdict(list)
    for c in rows:
        c["model"] = model.get((c["hero"], c["cat"], c["cand"]))
        by[(c["hero"], c["cat"])].append(c)
    for grp in by.values():
        mx = max(c["cons"] for c in grp)
        ms = [c["model"] for c in grp if c["model"] is not None]
        lo, hi = (min(ms), max(ms)) if ms else (0, 0)
        for c in grp:
            c["s_cons"] = c["cons"] / mx if mx > 0 else 0.0
            if c["model"] is None:
                c["s_model"] = None
                c["final"] = round(c["s_cons"], 6)
            else:
                c["s_model"] = (c["model"] - lo) / (hi - lo) if hi > lo else 0.5
                c["final"] = round((w["alpha"] * c["s_cons"] + w["beta"] * c["s_model"]) / (w["alpha"] + w["beta"]), 6)
    for idx, c in enumerate(rows):
        c["row"] = idx + 1
    for grp in by.values():
        for c in grp:
            c["rank"] = 1 + sum(1 for o in grp if o["final"] > c["final"]) + \
                sum(1 for o in grp if o["final"] == c["final"] and o["row"] < c["row"])
    for c in rows:
        c["sources"] = ", ".join(sorted(c["sources"]))
    return rows


def hero_tiers(votes: list[dict], w: dict, today: dt.date) -> dict[str, float]:
    num, den = defaultdict(float), defaultdict(float)
    for v in votes:
        if v["cat"] != "tier":
            continue
        vw, base = vote_weight(v, w, today)
        num[v["hero"]] += vw
        den[v["hero"]] += base
    return {h: num[h] / den[h] for h in den if den[h] > 0}


def top(cands: list[dict], hero: str, cat: str, k: int) -> list[dict]:
    return sorted([c for c in cands if c["hero"] == hero and c["cat"] == cat], key=lambda c: c["rank"])[:k]


# ------------------------------------------------------------------------------- CP-SAT assignments
def assign_cards(cands: list[dict], team: list[str]) -> dict[str, dict | None]:
    """One charm card per heroine, no card twice in the team (rule from the operator's plans); maximise sum(final)."""
    from ortools.sat.python import cp_model
    opts = {h: [c for c in cands if c["hero"] == h and c["cat"] == "card" and c["final"] > 0] for h in team}
    m = cp_model.CpModel()
    x = {(h, c["cand"]): m.NewBoolVar(f"{h}_{c['cand']}") for h in team for c in opts[h]}
    for h in team:
        if opts[h]:
            m.Add(sum(x[h, c["cand"]] for c in opts[h]) <= 1)
    for card in {c["cand"] for h in team for c in opts[h]}:
        m.Add(sum(v for (h, cc), v in x.items() if cc == card) <= 1)
    m.Maximize(sum(int(round(c["final"] * 10000)) * x[h, c["cand"]] for h in team for c in opts[h]))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 10
    s.parameters.num_workers = 1
    s.Solve(m)
    return {h: next((c for c in opts[h] if s.Value(x[h, c["cand"]])), None) for h in team}


def assign_pets(cands: list[dict], team: list[str], rarity: dict[str, str], w: dict, enforce_caps: bool = True) -> dict:
    """4 pets per heroine; a pet may be linked to at most cap[rarity] heroines (ChatGPT plan rule - UNVERIFIED)."""
    from ortools.sat.python import cp_model
    slots = int(w["pet_slots"])
    opts = {h: [c for c in cands if c["hero"] == h and c["cat"] == "pet" and c["final"] > 0] for h in team}
    m = cp_model.CpModel()
    x = {(h, c["cand"]): m.NewBoolVar(f"{h}_{c['cand']}") for h in team for c in opts[h]}
    for h in team:
        if opts[h]:
            m.Add(sum(x[h, c["cand"]] for c in opts[h]) == min(slots, len(opts[h])))
    if enforce_caps:
        for pet in {c["cand"] for h in team for c in opts[h]}:
            cap = w["pet_cap"].get(rarity.get(pet, ""), len(team))
            m.Add(sum(v for (h, p), v in x.items() if p == pet) <= cap)
    m.Maximize(sum(int(round(c["final"] * 10000)) * x[h, c["cand"]] for h in team for c in opts[h]))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = 20
    s.parameters.num_workers = 1
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return assign_pets(cands, team, rarity, w, enforce_caps=False) if enforce_caps else {h: [] for h in team}
    return {h: sorted([c for c in opts[h] if s.Value(x[h, c["cand"]])], key=lambda c: c["rank"]) for h in team}
