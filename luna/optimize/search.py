"""Team optimizer (stage 7).

Genome = team composition + formation + per-hero build + rune order + princess weapon.
Evaluation = Monte Carlo with common random numbers (same seeds for every candidate) and
racing (cheap screen, then more battles for the survivors). Results are MODEL estimates.

Algorithms
  * exhaustive        - only when the space is tiny (rune order: 4! = 24)
  * CP-SAT            - equipment assignment under inventory / slot / position constraints
  * beam search       - composition built hero by hero
  * genetic algorithm - composition + formation + runes + princess weapon; NSGA-II style
                        Pareto ranking for multi-objective runs
  * simulated annealing - build-level search (talents, limbs, pets) for a fixed composition
"""
from __future__ import annotations

import copy
import itertools
import math
import random
from dataclasses import dataclass, field

from ..engine.assumptions import AssumptionSet
from ..model import Catalog, Team, HeroBuild
from ..rules import GameRules, validate_team
from ..sim.montecarlo import simulate, PriorBook
from .pareto import non_dominated_sort, crowding_distance

OBJECTIVES = {
    # name: (direction, description)
    "win_rate": (+1, "средний модельный WR против пула соперников"),
    "robust_wr": (+1, "минимальный WR по пулу (устойчивость против популярных команд)"),
    "speed": (+1, "скорость победы: 1/средние раунды в победах"),
    "survival": (+1, "средняя доля выживших героинь"),
    "cost": (-1, "стоимость недостающих улучшений/предметов"),
}


# ===================================================================== evaluation
@dataclass
class Evaluator:
    opponents: list[Team]
    cat: Catalog
    asm: AssumptionSet
    n: int = 100
    seed: int = 11
    priors: PriorBook | None = None
    cost_fn: object = None          # callable(team) -> float
    cache: dict = field(default_factory=dict)
    calls: int = 0
    battles: int = 0

    def key(self, team: Team, n: int) -> str:
        d = team.to_dict()
        d.pop("name", None)
        import json
        return json.dumps(d, sort_keys=True, ensure_ascii=False) + f"|{n}"

    def __call__(self, team: Team, n: int | None = None) -> dict:
        n = n or self.n
        k = self.key(team, n)
        if k in self.cache:
            return self.cache[k]
        self.calls += 1
        per, rounds_w, surv = {}, [], []
        for opp in self.opponents:
            s = simulate(team, opp, self.cat, self.asm, n=n, seed=self.seed, priors=self.priors, workers=1)
            self.battles += n
            per[opp.name] = s["model_win_rate"]
            rounds_w.append(s["avg_rounds"])
            alive = [h.get("survival_rate", 0) for key, h in s["heroes"].items() if key.startswith("A:") and "survival_rate" in h]
            surv.append(sum(alive) / max(1, len(alive)))
        wr = sum(per.values()) / len(per)
        out = {"win_rate": wr, "robust_wr": min(per.values()), "speed": 1.0 / max(1e-9, sum(rounds_w) / len(rounds_w)),
               "survival": sum(surv) / len(surv), "cost": float(self.cost_fn(team)) if self.cost_fn else 0.0,
               "per_opponent": per, "n": n}
        self.cache[k] = out
        return out


def scalar(obj: dict, weights: dict) -> float:
    return sum(w * OBJECTIVES[k][0] * obj[k] for k, w in weights.items())


# ===================================================================== search space
@dataclass
class Roster:
    """Heroes I can field (with their builds) and the items I own."""

    heroes: dict                      # hero_id -> HeroBuild
    inventory: dict = field(default_factory=dict)   # "section:id" -> count
    region: str = "RU"
    balance_version: str = "UNKNOWN"
    rune_pool: list = field(default_factory=list)
    pw_pool: list = field(default_factory=list)     # princess weapon part ids
    status: str = "hypothetical"

    @classmethod
    def from_dict(cls, d: dict) -> "Roster":
        return cls(heroes={h["hero_id"]: HeroBuild.from_dict(h) for h in d["heroes"]}, inventory=d.get("inventory", {}),
                   region=d.get("region", "RU"), balance_version=d.get("balance_version", "UNKNOWN"),
                   rune_pool=d.get("rune_pool", []), pw_pool=d.get("pw_pool", []), status=d.get("status", "hypothetical"))


def make_team(roster: Roster, hero_ids: list[str], positions: list[int] | None = None, runes=None, pw=None,
              name="candidate", base: Team | None = None) -> Team:
    positions = positions or list(range(len(hero_ids)))
    t = Team(name=name, heroes=[copy.deepcopy(roster.heroes[h]) for h in hero_ids],
             formation={h: p for h, p in zip(hero_ids, positions)}, region=roster.region,
             balance_version=roster.balance_version, runes=list(runes or []), princess_weapon=list(pw or []))
    if base is not None:
        t.global_stats, t.faction_bonus, t.relics = base.global_stats, base.faction_bonus, base.relics
    return t


# ===================================================================== exhaustive (small spaces only)
def best_rune_order(team: Team, ev: Evaluator, max_perms: int = 24) -> dict:
    perms = list(itertools.permutations(team.runes))
    if len(perms) > max_perms:
        raise ValueError(f"{len(perms)} permutations > {max_perms}: use GA/SA instead of exhaustive search")
    rows = []
    for p in perms:
        t = copy.deepcopy(team)
        t.runes = list(p)
        rows.append({"order": list(p), **{k: v for k, v in ev(t).items() if k != "per_opponent"}})
    rows.sort(key=lambda r: -r["win_rate"])
    return {"method": "exhaustive", "evaluated": len(rows), "ranking": rows}


# ===================================================================== CP-SAT equipment assignment
def cp_sat_equipment(team: Team, cat: Catalog, inventory: dict, weights_by_role: dict | None = None,
                     time_limit: float = 10.0) -> dict:
    """Assign limbs (by position) and decorations to heroes maximising a linear stat score subject to
    inventory counts and slot positions. The score is a heuristic proxy (stat weights per role), used to
    produce FEASIBLE high-value starting points that Monte Carlo then evaluates."""
    from ortools.sat.python import cp_model
    weights_by_role = weights_by_role or {
        "attacker": {"ATK": 1.0, "CRIT": 3000, "CRIT_DMG": 1500, "IGNORE_DEF": 2500, "SPD": 20, "HP": 0.05},
        "tank": {"HP": 0.2, "DEF": 2.0, "DR": 3000, "ATK": 0.2, "SPD": 10},
        "support": {"SPD": 40, "HP": 0.12, "DEF": 1.0, "HEAL_BONUS": 2000, "ATK": 0.3, "CTRL_RES": 1500},
        "control": {"SPD": 40, "CTRL_HIT": 2500, "ATK": 0.5, "HP": 0.08},
        "UNKNOWN": {"ATK": 0.5, "HP": 0.1, "DEF": 1.0, "SPD": 20},
    }
    m = cp_model.CpModel()
    heroes = team.heroes
    items = {"limbs": [], "decorations": []}
    for key, cnt in inventory.items():
        sec, iid = key.split(":", 1)
        if sec in items and cat.has(sec, iid) and cnt > 0:
            items[sec].append((iid, cnt))
    x = {}
    score_terms = []
    for hi, hb in enumerate(heroes):
        role = cat.get("heroes", hb.hero_id).get("role", "UNKNOWN") if cat.has("heroes", hb.hero_id) else "UNKNOWN"
        w = weights_by_role.get(role, weights_by_role["UNKNOWN"])
        base = hb.stats
        for sec in items:
            for iid, cnt in items[sec]:
                e = cat.get(sec, iid)
                val = 0.0
                for mod in e.get("mods", []):
                    v = mod["value"] * (float(base.get(mod["stat"], 0) or 0) if mod.get("mode") == "pct" else 1.0)
                    val += w.get(mod["stat"], 0.0) * v
                x[(hi, sec, iid)] = m.NewBoolVar(f"x_{hi}_{sec}_{iid}")
                score_terms.append(int(round(val * 100)) * x[(hi, sec, iid)])
        # limb positions: at most one limb per position
        for pos in range(4):
            vs = [x[(hi, "limbs", iid)] for iid, _ in items["limbs"] if cat.get("limbs", iid).get("position") == pos]
            if vs:
                m.Add(sum(vs) <= 1)
        vs = [x[(hi, "decorations", iid)] for iid, _ in items["decorations"]]
        if vs:
            m.Add(sum(vs) <= 8)
    # inventory
    for sec in items:
        for iid, cnt in items[sec]:
            m.Add(sum(x[(hi, sec, iid)] for hi in range(len(heroes))) <= cnt)
    # set bonuses: y[h,set,thr] -> needs thr pieces
    for hi, hb in enumerate(heroes):
        role = cat.get("heroes", hb.hero_id).get("role", "UNKNOWN") if cat.has("heroes", hb.hero_id) else "UNKNOWN"
        w = weights_by_role.get(role, weights_by_role["UNKNOWN"])
        for sid, ls in cat.sections["limb_sets"].items():
            pieces = [x[(hi, "limbs", iid)] for iid, _ in items["limbs"] if cat.get("limbs", iid).get("set") == sid]
            if not pieces:
                continue
            for thr, bonus in ls.get("bonuses", {}).items():
                y = m.NewBoolVar(f"y_{hi}_{sid}_{thr}")
                m.Add(sum(pieces) >= int(thr)).OnlyEnforceIf(y)
                val = sum(w.get(md["stat"], 0.0) * md["value"] * (float(hb.stats.get(md["stat"], 0) or 0) if md.get("mode") == "pct" else 1)
                          for md in bonus.get("mods", []))
                score_terms.append(int(round(val * 100)) * y)
    m.Maximize(sum(score_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    st = solver.Solve(m)
    status = solver.StatusName(st)
    out = copy.deepcopy(team)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for hi, hb in enumerate(out.heroes):
            limbs = [None] * 4
            for iid, _ in items["limbs"]:
                if solver.Value(x[(hi, "limbs", iid)]):
                    limbs[cat.get("limbs", iid).get("position", 0)] = iid
            hb.limbs = [l for l in limbs] if any(limbs) else []
            hb.decorations = [iid for iid, _ in items["decorations"] if solver.Value(x[(hi, "decorations", iid)])]
    return {"method": "cp-sat", "status": status, "objective": solver.ObjectiveValue() if status in ("OPTIMAL", "FEASIBLE") else None,
            "team": out, "wall_time": solver.WallTime()}


# ===================================================================== beam search over composition
def beam_search(roster: Roster, ev: Evaluator, size: int = 6, width: int = 4, n_screen: int = 40, base: Team | None = None,
                must_include: list[str] | None = None, rng_seed: int = 3) -> dict:
    ids = sorted(roster.heroes)
    must = list(must_include or [])
    beams = [tuple(must)]
    trace = []
    while len(beams[0]) < size:
        cand = {}
        for b in beams:
            for h in ids:
                if h in b:
                    continue
                nb = tuple(sorted(b + (h,)))
                if nb in cand:
                    continue
                t = make_team(roster, list(nb), runes=roster.rune_pool[:4], pw=roster.pw_pool[:4], base=base)
                cand[nb] = ev(t, n_screen)
        ranked = sorted(cand.items(), key=lambda kv: -kv[1]["win_rate"])[:width]
        trace.append([(list(k), round(v["win_rate"], 3)) for k, v in ranked])
        beams = [k for k, _ in ranked]
    best = beams[0]
    t = make_team(roster, list(best), runes=roster.rune_pool[:4], pw=roster.pw_pool[:4], base=base, name="beam-best")
    return {"method": "beam", "best": list(best), "team": t, "objectives": ev(t), "trace": trace}


# ===================================================================== GA (single or multi objective)
@dataclass
class Genome:
    heroes: list
    positions: list
    runes: list
    pw: list

    def key(self):
        return (tuple(self.heroes), tuple(self.positions), tuple(self.runes), tuple(self.pw))


def _random_genome(roster: Roster, rng: random.Random, size=6) -> Genome:
    hs = rng.sample(sorted(roster.heroes), size)
    pos = rng.sample(range(6), size)
    runes = rng.sample(roster.rune_pool, min(4, len(roster.rune_pool))) if roster.rune_pool else []
    pw = list(roster.pw_pool[:4])
    return Genome(hs, pos, runes, pw)


def _mutate(g: Genome, roster: Roster, rng: random.Random) -> Genome:
    g = Genome(list(g.heroes), list(g.positions), list(g.runes), list(g.pw))
    r = rng.random()
    pool = [h for h in roster.heroes if h not in g.heroes]
    if r < 0.4 and pool:
        g.heroes[rng.randrange(len(g.heroes))] = rng.choice(pool)
    elif r < 0.7:
        i, j = rng.sample(range(len(g.positions)), 2)
        g.positions[i], g.positions[j] = g.positions[j], g.positions[i]
    elif r < 0.9 and len(g.runes) >= 2:
        i, j = rng.sample(range(len(g.runes)), 2)
        g.runes[i], g.runes[j] = g.runes[j], g.runes[i]
        extra = [x for x in roster.rune_pool if x not in g.runes]
        if extra and rng.random() < 0.3:
            g.runes[rng.randrange(len(g.runes))] = rng.choice(extra)
    else:
        free = [p for p in range(6) if p not in g.positions]
        if free:
            g.positions[rng.randrange(len(g.positions))] = rng.choice(free)
    return g


def _crossover(a: Genome, b: Genome, rng: random.Random) -> Genome:
    """Composition: union-sampling crossover that keeps heroes unique; positions follow the parent."""
    pool = list(dict.fromkeys(a.heroes + b.heroes))
    keep = [h for h in a.heroes if h in b.heroes]
    rest = [h for h in pool if h not in keep]
    rng.shuffle(rest)
    hs = (keep + rest)[:len(a.heroes)]
    src = a if rng.random() < 0.5 else b
    return Genome(hs, list(src.positions), list((a if rng.random() < 0.5 else b).runes), list(a.pw))


def genetic_algorithm(roster: Roster, ev: Evaluator, generations: int = 8, pop_size: int = 16, seed: int = 5,
                      weights: dict | None = None, multi_objective: list[str] | None = None, base: Team | None = None,
                      n_screen: int = 30, n_final: int = 200, rules: GameRules | None = None) -> dict:
    rng = random.Random(seed)
    weights = weights or {"win_rate": 1.0}
    to_team = lambda g, name="ga": make_team(roster, g.heroes, g.positions, g.runes, g.pw, name=name, base=base)
    pop = []
    seen = set()
    while len(pop) < pop_size:
        g = _random_genome(roster, rng, min(6, len(roster.heroes)))
        if g.key() not in seen:
            seen.add(g.key())
            pop.append(g)
    history = []
    for gen in range(generations):
        objs = [ev(to_team(g), n_screen) for g in pop]
        if multi_objective:
            vecs = [[OBJECTIVES[k][0] * o[k] for k in multi_objective] for o in objs]
            fronts = non_dominated_sort(vecs)
            rank = {}
            for fi, f in enumerate(fronts):
                cd = crowding_distance([vecs[i] for i in f])
                for i, c in zip(f, cd):
                    rank[i] = (fi, -c)
            order = sorted(range(len(pop)), key=lambda i: rank[i])
        else:
            order = sorted(range(len(pop)), key=lambda i: -scalar(objs[i], weights))
        history.append({"gen": gen, "best": round(objs[order[0]]["win_rate"], 4),
                        "mean": round(sum(o["win_rate"] for o in objs) / len(objs), 4)})
        elite = [pop[i] for i in order[: max(2, pop_size // 4)]]
        nxt = list(elite)
        while len(nxt) < pop_size:
            a, b = [pop[min(rng.sample(order, 2), key=order.index)] for _ in range(2)]   # tournament(2)
            c = _crossover(a, b, rng) if rng.random() < 0.7 else Genome(list(a.heroes), list(a.positions), list(a.runes), list(a.pw))
            if rng.random() < 0.8:
                c = _mutate(c, roster, rng)
            if c.key() not in seen or rng.random() < 0.1:
                seen.add(c.key())
                nxt.append(c)
        pop = nxt
    # racing: re-evaluate the top candidates with more battles before declaring a winner
    screened = sorted(pop, key=lambda g: -scalar(ev(to_team(g), n_screen), weights))[:4]
    final = [(g, ev(to_team(g), n_final)) for g in screened]
    final.sort(key=lambda kv: -scalar(kv[1], weights))
    best_g, best_o = final[0]
    out = {"method": "genetic_algorithm", "best": best_g.heroes, "positions": best_g.positions, "runes": best_g.runes,
           "team": to_team(best_g, "ga-best"), "objectives": best_o, "history": history,
           "finalists": [{"heroes": g.heroes, "positions": g.positions, "runes": g.runes, **{k: v for k, v in o.items() if k != "per_opponent"}}
                         for g, o in final],
           "evaluations": ev.calls, "battles": ev.battles}
    if multi_objective:
        objs = [ev(to_team(g), n_screen) for g in pop]
        vecs = [[OBJECTIVES[k][0] * o[k] for k in multi_objective] for o in objs]
        front = non_dominated_sort(vecs)[0]
        out["pareto_front"] = [{"heroes": pop[i].heroes, **{k: objs[i][k] for k in multi_objective}} for i in front]
    if rules is not None:
        out["validation"] = validate_team(out["team"], ev.cat, rules).to_dict()
    return out


# ===================================================================== SA over builds
def simulated_annealing_builds(team: Team, options: dict, ev: Evaluator, iters: int = 60, seed: int = 9,
                               t0: float = 0.05, alpha: float = 0.95, n: int = 40) -> dict:
    """options[hero_id] = {"talents": [[t1,t2], ...], "limbs": [[l0..l3], ...], "pets": [[p], ...], "sigils": [...]}
    Each field picks one of the listed legal alternatives (alternatives are pre-validated)."""
    rng = random.Random(seed)
    cur = copy.deepcopy(team)
    cur_o = ev(cur, n)
    best, best_o = copy.deepcopy(cur), cur_o
    T = t0
    trace = []
    choices = [(h, f) for h, fs in options.items() for f in fs if len(fs[f]) > 1]
    if not choices:
        return {"method": "simulated_annealing", "team": cur, "objectives": cur_o, "trace": [], "note": "no alternatives"}
    for it in range(iters):
        h, f = rng.choice(choices)
        cand = copy.deepcopy(cur)
        hb = next(x for x in cand.heroes if x.hero_id == h)
        setattr(hb, f, copy.deepcopy(rng.choice(options[h][f])))
        o = ev(cand, n)
        d = o["win_rate"] - cur_o["win_rate"]
        if d >= 0 or rng.random() < math.exp(d / max(T, 1e-9)):
            cur, cur_o = cand, o
            if o["win_rate"] > best_o["win_rate"]:
                best, best_o = copy.deepcopy(cand), o
        T *= alpha
        trace.append(round(cur_o["win_rate"], 4))
    return {"method": "simulated_annealing", "team": best, "objectives": best_o, "trace": trace, "iters": iters}
