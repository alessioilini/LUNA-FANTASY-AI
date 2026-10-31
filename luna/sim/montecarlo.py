"""Battle simulator 6x6: single battles with full report and Monte Carlo series (1k / 10k+).

Model win rates are labelled `model_win_rate` everywhere - they are NOT real win rates until the
simulator passes validation on real battles (luna.validation).
"""
from __future__ import annotations

import os
import random
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from ..engine.assumptions import AssumptionSet
from ..engine.battle import Battle, BattleResult
from ..engine.resolve import build_units
from ..model import Catalog, Team
from .stats import wilson, mean_ci

SEED_STRIDE = 1_000_003


# ------------------------------------------------------------------------- priors
@dataclass
class StatPrior:
    """Distribution for an UNKNOWN stat: uniform [lo, hi] (explicitly an assumption)."""

    lo: float
    hi: float

    def sample(self, rng: random.Random) -> float:
        return rng.uniform(self.lo, self.hi)


@dataclass
class PriorBook:
    """priors[(hero_id or '*', stat)] -> StatPrior. Recorded in results as `prior:*` assumptions."""

    priors: dict = field(default_factory=dict)
    label: str = "unnamed-priors"

    def to_dict(self):
        return {"label": self.label, "priors": {f"{h}|{s}": [p.lo, p.hi] for (h, s), p in self.priors.items()}}

    @classmethod
    def from_dict(cls, d):
        pb = cls(label=d.get("label", "priors"))
        for k, (lo, hi) in d.get("priors", {}).items():
            h, s = k.split("|")
            pb.priors[(h, s)] = StatPrior(lo, hi)
        return pb

    def filler(self, rng: random.Random):
        cache = {}

        def fill(hero_id, stat):
            key = (hero_id, stat)
            if key not in cache:
                p = self.priors.get(key) or self.priors.get(("*", stat))
                if p is None:
                    raise KeyError(f"no prior for {hero_id}.{stat}")
                cache[key] = p.sample(rng)
            return cache[key]

        return fill


# ------------------------------------------------------------------------- single battle
def run_battle(team_a: Team, team_b: Team, cat: Catalog, asm: AssumptionSet, seed: int = 0,
               priors: PriorBook | None = None, log: bool = True, cat_b: Catalog | None = None) -> BattleResult:
    rng = random.Random(seed ^ 0x5EED)
    fill = priors.filler(rng) if priors else None
    ua = build_units(team_a, cat, "A", asm, fill)
    ub = build_units(team_b, cat_b or cat, "B", asm, fill)
    return Battle(ua, ub, asm, seed=seed, log=log).run()


def battle_report(res: BattleResult) -> dict:
    """Human-oriented single-battle report (actions, combos, damage, heal, shields, control, revives, deaths)."""
    rows = []
    for u in res.units:
        if u.get("team_source"):
            rows.append({"uid": u["uid"], "hero": "__team__", "dmg_effective": u["dmg_effective"],
                         "by_ability": u["by_ability"]})
            continue
        rows.append({k: u[k] for k in ("uid", "hero", "alive", "hp", "max_hp", "actions", "extra_actions", "combo_triggers",
                                         "dmg_raw", "dmg_effective", "dmg_to_shield", "overkill", "dmg_taken_hp",
                                         "dmg_absorbed_by_own_shield", "heal_effective", "overheal", "shield_given",
                                         "ctrl_attempts", "ctrl_landed", "ctrl_resisted", "turns_controlled",
                                         "revives_done", "revived_times", "revive_blocked", "deaths", "kills", "crits",
                                         "dodges", "reflected", "by_ability")})
    return {"winner": res.winner, "rounds": res.rounds, "seed": res.seed, "end_reason": res.end_reason,
            "hp_left": res.hp_left, "first_round": res.first_round, "deaths": res.deaths,
            "round_damage": res.round_damage, "units": rows, "assumptions_used": res.assumptions_used,
            "label": "MODEL RESULT - not validated against real battles"}


# ------------------------------------------------------------------------- monte carlo
def _chunk(payload):
    ta, tb, catd, catbd, asm_vals, asm_stacking, prior_d, seeds, keep_logs = payload
    team_a, team_b = Team.from_dict(ta), Team.from_dict(tb)
    cat = Catalog(catd)
    cat_b = Catalog(catbd) if catbd else None
    priors = PriorBook.from_dict(prior_d) if prior_d else None
    out = []
    used = set()
    for s in seeds:
        asm = AssumptionSet(values=dict(asm_vals), stacking=dict(asm_stacking))
        r = run_battle(team_a, team_b, cat, asm, s, priors, log=keep_logs, cat_b=cat_b)
        used |= set(r.assumptions_used)
        out.append(_compact(r))
    return out, used


def _compact(r: BattleResult) -> dict:
    units = []
    for u in r.units:
        d = {k: v for k, v in u.items() if k != "by_ability"}
        d["by_ability"] = {k: dict(v) for k, v in u["by_ability"].items()}
        units.append(d)
    return {"winner": r.winner, "rounds": r.rounds, "seed": r.seed, "units": units, "deaths": r.deaths,
            "hp_left": r.hp_left, "first_round": r.first_round, "end_reason": r.end_reason,
            "round_damage": r.round_damage}


def simulate(team_a: Team, team_b: Team, cat: Catalog, asm: AssumptionSet, n: int = 1000, seed: int = 1,
             priors: PriorBook | None = None, workers: int | None = None, key_heroes: list[str] | None = None,
             cat_b: Catalog | None = None, keep_raw: bool = False) -> dict:
    seeds = [seed * SEED_STRIDE + i for i in range(n)]
    workers = workers if workers is not None else (min(os.cpu_count() or 1, 8) if n >= 2000 else 1)
    base = (team_a.to_dict(), team_b.to_dict(), cat.to_dict(), cat_b.to_dict() if cat_b else None,
            dict(asm.values), dict(asm.stacking), priors.to_dict() if priors else None)
    raws, used = [], set()
    if workers <= 1:
        r, u = _chunk(base + (seeds, False))
        raws, used = r, u
    else:
        size = max(1, len(seeds) // (workers * 4))
        chunks = [seeds[i:i + size] for i in range(0, len(seeds), size)]
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for r, u in ex.map(_chunk, [base + (c, False) for c in chunks]):
                raws.extend(r)
                used |= u
    summary = aggregate(raws, key_heroes=key_heroes)
    summary["assumptions_used"] = sorted(used)
    summary["assumption_values"] = asm.fingerprint()
    summary["seed"] = seed
    summary["priors"] = priors.to_dict() if priors else None
    summary["label"] = "MODEL WIN RATE - not a real win rate until validated (see luna validate)"
    if keep_raw:
        summary["raw"] = raws
    return summary


def aggregate(raws: list[dict], key_heroes: list[str] | None = None) -> dict:
    n = len(raws)
    res = Counter(r["winner"] for r in raws)
    wins = res.get("A", 0)
    lo, hi = wilson(wins, n)
    rounds = [r["rounds"] for r in raws]
    per = defaultdict(lambda: defaultdict(float))
    abil = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    death_causes = defaultdict(Counter)
    first_death = Counter()
    for r in raws:
        side_dmg = {"A": 0.0, "B": 0.0}
        for u in r["units"]:
            side_dmg[u["side"]] += u["dmg_effective"] + u["dmg_to_shield"]
        for u in r["units"]:
            key = f"{u['side']}:{u['hero']}"
            p = per[key]
            for k in ("dmg_raw", "dmg_effective", "dmg_to_shield", "overkill", "dmg_taken_hp", "dmg_absorbed_by_own_shield",
                      "heal_effective", "overheal", "shield_given", "ctrl_attempts", "ctrl_landed", "ctrl_resisted",
                      "turns_controlled", "revives_done", "revived_times", "revive_blocked", "deaths", "kills", "actions",
                      "extra_actions", "combo_triggers", "crits", "dodges", "reflected"):
                p[k] += u.get(k, 0)
            if not u.get("team_source"):
                p["survived"] += 1 if u["alive"] else 0
                p["died_at_least_once"] += 1 if u["deaths"] > 0 else 0
                p["max_hp"] += u["max_hp"]
            tot = side_dmg[u["side"]]
            p["damage_share"] += (u["dmg_effective"] + u["dmg_to_shield"]) / tot if tot else 0.0
            for ab, vals in u["by_ability"].items():
                for k, v in vals.items():
                    abil[key][ab][k] += v
        if r["deaths"]:
            d0 = r["deaths"][0]
            first_death[f"{d0['uid'][0]}:{d0['hero']}"] += 1
        for d in r["deaths"]:
            death_causes[f"{d['uid'][0]}:{d['hero']}"][f"{d['killer'][0]}:{d['killer_hero']}/{d['ability']}"] += 1
    heroes = {}
    for key, p in per.items():
        avg = {k: v / n for k, v in p.items()}
        if "survived" in p:
            avg["survival_rate"] = p["survived"] / n
            avg["p_died"] = p["died_at_least_once"] / n
            avg["max_hp"] = p["max_hp"] / n
        avg["abilities"] = {ab: {k: v / n for k, v in vals.items()} for ab, vals in abil[key].items()}
        avg["death_causes_top"] = death_causes[key].most_common(5)
        heroes[key] = avg
    out = {
        "n": n, "wins": wins, "losses": res.get("B", 0), "draws": res.get("draw", 0),
        "model_win_rate": wins / n if n else 0.0, "ci95": (lo, hi),
        "avg_rounds": sum(rounds) / n if n else 0.0, "rounds_ci95": mean_ci(rounds)[1:],
        "rounds_hist": dict(sorted(Counter(rounds).items())),
        "avg_damage": {s: sum(h["dmg_effective"] + h["dmg_to_shield"] for k, h in heroes.items() if k.startswith(s + ":"))
                       for s in "AB"},
        "avg_hp_left": {s: sum(r["hp_left"][s] for r in raws) / n for s in "AB"} if n else {},
        "heroes": heroes,
        "first_death": dict(first_death.most_common()),
        "end_reasons": dict(Counter(r["end_reason"] for r in raws)),
    }
    if key_heroes:
        out["key_hero_death_prob"] = {h: heroes.get(f"A:{h}", {}).get("p_died", None) for h in key_heroes}
    return out


def compare(team_a: Team, team_a2: Team, opponents: list[Team], cat: Catalog, asm: AssumptionSet, n: int = 500,
            seed: int = 7, priors: PriorBook | None = None) -> dict:
    """Paired (CRN) comparison of two versions of my team against a pool of opponents."""
    from .stats import paired_diff
    out = {"per_opponent": {}, "label": "MODEL comparison (common random numbers)"}
    all_a, all_b = [], []
    for opp in opponents:
        ra = simulate(team_a, opp, cat, asm, n, seed, priors, workers=1, keep_raw=True)["raw"]
        rb = simulate(team_a2, opp, cat, asm, n, seed, priors, workers=1, keep_raw=True)["raw"]
        xa = [1.0 if r["winner"] == "A" else 0.0 for r in ra]
        xb = [1.0 if r["winner"] == "A" else 0.0 for r in rb]
        all_a += xa
        all_b += xb
        out["per_opponent"][opp.name] = {"wr_a": sum(xa) / n, "wr_b": sum(xb) / n, **paired_diff(xa, xb)}
    out["overall"] = paired_diff(all_a, all_b)
    out["overall"]["wr_a"] = sum(all_a) / max(1, len(all_a))
    out["overall"]["wr_b"] = sum(all_b) / max(1, len(all_b))
    return out


def ehp_model(unit_stats: dict, ref_atk: float, asm: AssumptionSet) -> float:
    """Effective HP against a reference physical attack under the CURRENT damage assumptions."""
    hp = unit_stats.get("HP", 0.0)
    D = unit_stats.get("DEF", 0.0)
    fam = asm.get("dmg.family")
    if fam == "divisive":
        k = float(asm.get("dmg.k_def"))
        mult = k / (k + D)
    elif fam == "ratio":
        mult = ref_atk / (ref_atk + D) if ref_atk > 0 else 1.0
    else:
        mult = max(float(asm.get("dmg.min_fraction")), (ref_atk - D) / ref_atk) if ref_atk > 0 else 1.0
    mult *= 1 - min(unit_stats.get("DR", 0.0), float(asm.get("dmg.dr_cap")))
    return hp / mult if mult > 0 else float("inf")
