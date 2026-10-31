"""Resource planner: choose upgrades under a multi-currency budget (CP-SAT knapsack) and project
how long the rest takes at a given daily income. Costs must be supplied/sourced; unknown costs are
reported, never guessed."""
from __future__ import annotations

import math

from .provenance import is_unknown


def plan(upgrades: list[dict], budget: dict, time_limit: float = 5.0) -> dict:
    """upgrades: [{"id", "desc", "cost": {res: amount|'UNKNOWN'}, "gain": ΔWR (model), "requires": [ids]}]"""
    from ortools.sat.python import cp_model
    known = [u for u in upgrades if not any(is_unknown(v) for v in u.get("cost", {}).values())]
    unknown = [u["id"] for u in upgrades if u not in known]
    m = cp_model.CpModel()
    x = {u["id"]: m.NewBoolVar(u["id"]) for u in known}
    for res, cap in budget.items():
        m.Add(sum(int(u["cost"].get(res, 0)) * x[u["id"]] for u in known) <= int(cap))
    for u in known:
        for req in u.get("requires", []):
            if req in x:
                m.AddImplication(x[u["id"]], x[req])
            else:
                m.Add(x[u["id"]] == 0)
    m.Maximize(sum(int(round(u.get("gain", 0) * 1e5)) * x[u["id"]] for u in known))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    st = s.Solve(m)
    chosen = [u for u in known if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) and s.Value(x[u["id"]])]
    spent = {r: sum(u["cost"].get(r, 0) for u in chosen) for r in budget}
    return {"status": s.StatusName(st), "chosen": [u["id"] for u in chosen],
            "expected_gain_model": sum(u.get("gain", 0) for u in chosen), "spent": spent,
            "left": {r: budget[r] - spent[r] for r in budget}, "cost_unknown": unknown,
            "label": "gain = модельный ΔWR (не реальный)"}


def days_to_afford(costs: dict, have: dict, income_per_day: dict) -> dict:
    out = {}
    for r, c in costs.items():
        if is_unknown(c):
            out[r] = "UNKNOWN"
            continue
        need = max(0.0, c - have.get(r, 0))
        inc = income_per_day.get(r, 0)
        out[r] = 0 if need == 0 else (math.ceil(need / inc) if inc > 0 else math.inf)
    finite = [v for v in out.values() if isinstance(v, (int, float))]
    return {"per_resource": out, "days": max(finite) if finite else None}


def long_term(upgrades: list[dict], have: dict, income_per_day: dict, horizon_days: int = 90) -> list[dict]:
    """Greedy schedule by gain/cost ratio over a horizon (heuristic, transparent)."""
    def ratio(u):
        c = sum(v for v in u["cost"].values() if not is_unknown(v)) or 1
        return u.get("gain", 0) / c
    stock = dict(have)
    day = 0
    sched = []
    for u in sorted([u for u in upgrades if not any(is_unknown(v) for v in u["cost"].values())], key=ratio, reverse=True):
        d = days_to_afford(u["cost"], stock, income_per_day)["days"]
        if d is None or d == math.inf or day + d > horizon_days:
            continue
        day += d
        for r in set(stock) | set(income_per_day):
            stock[r] = stock.get(r, 0) + income_per_day.get(r, 0) * d - u["cost"].get(r, 0)
        sched.append({"id": u["id"], "day": day, "gain_model": u.get("gain", 0)})
    return sched
