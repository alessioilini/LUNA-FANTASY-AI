"""Matchup & counterpick analyzer (stage 8).

Every recommendation is a concrete change evaluated by paired Monte Carlo (same seeds for baseline
and candidate). The reason shown for a change is the set of mechanism metrics that moved the most
(e.g. enemy revives, first-round damage, deaths of my support) - not a hand-written opinion.
"""
from __future__ import annotations

import copy
import itertools
from collections import Counter

from .engine.assumptions import AssumptionSet
from .model import Catalog, Team
from .sim.montecarlo import simulate, PriorBook
from .sim.stats import paired_diff

METRICS_RU = {
    "my_damage": "урон моей команды", "enemy_damage": "урон соперника", "my_survival": "выживаемость моих героинь",
    "enemy_revives": "воскрешения соперника", "my_ctrl_landed": "мой наложенный контроль",
    "enemy_ctrl_landed": "контроль соперника по мне", "rounds": "длительность боя (раунды)",
    "r1_my_damage": "мой урон в 1-м раунде", "r1_enemy_damage": "урон соперника в 1-м раунде",
    "enemy_revive_blocked": "заблокированные воскрешения соперника", "my_heal": "моё эффективное лечение",
    "my_shield_absorb": "поглощение щитами по мне",
}
MODES = {
    "best_overall": "Best Overall Team - максимум среднего WR против пула мета-команд",
    "anti_meta": "Best Anti-Meta Team - максимум минимального WR по пулу (устойчивость)",
    "counter": "Best Counter Team - максимум WR против конкретного соперника",
    "no_donation": "Best No-Donation Team - только предметы без пометки donation_only",
    "with_resources": "Best With Available Resources - только то, что есть в инвентаре",
    "pve_boss": "Best PvE Boss Team - максимум урона по боссу за лимит раундов",
}


def _metrics(raws: list[dict]) -> dict:
    n = max(1, len(raws))
    m = Counter()
    for r in raws:
        for u in r["units"]:
            mine = u["side"] == "A"
            if u.get("team_source"):
                m["my_damage" if mine else "enemy_damage"] += u["dmg_effective"] + u["dmg_to_shield"]
                continue
            m["my_damage" if mine else "enemy_damage"] += u["dmg_effective"] + u["dmg_to_shield"]
            if mine:
                m["my_survival"] += 1 if u["alive"] else 0
                m["my_ctrl_landed"] += u["ctrl_landed"]
                m["my_heal"] += u["heal_effective"]
                m["my_shield_absorb"] += u["dmg_absorbed_by_own_shield"]
            else:
                m["enemy_revives"] += u["revives_done"]
                m["enemy_ctrl_landed"] += u["ctrl_landed"]
                m["enemy_revive_blocked"] += u["revive_blocked"]
        m["rounds"] += r["rounds"]
        m["r1_my_damage"] += r["first_round"]["damage"]["A"]
        m["r1_enemy_damage"] += r["first_round"]["damage"]["B"]
    out = {k: v / n for k, v in m.items()}
    out["my_survival"] = out.get("my_survival", 0) / 6
    return out


def _wins(raws):
    return [1.0 if r["winner"] == "A" else 0.0 for r in raws]


def explain(base_m: dict, cand_m: dict, top: int = 3) -> list[str]:
    rows = []
    for k, label in METRICS_RU.items():
        a, b = base_m.get(k, 0.0), cand_m.get(k, 0.0)
        if a == b:
            continue
        rel = (b - a) / abs(a) if a else (1.0 if b else 0.0)
        rows.append((abs(rel), f"{label}: {a:.3g} → {b:.3g} ({rel:+.0%})"))
    rows.sort(reverse=True)
    return [r for _, r in rows[:top]]


class MatchupAnalyzer:
    def __init__(self, cat: Catalog, asm: AssumptionSet, n: int = 300, seed: int = 21, priors: PriorBook | None = None):
        self.cat, self.asm, self.n, self.seed, self.priors = cat, asm, n, seed, priors

    def run(self, my: Team, enemy: Team, n: int | None = None) -> dict:
        return simulate(my, enemy, self.cat, self.asm, n=n or self.n, seed=self.seed, priors=self.priors, workers=1, keep_raw=True)

    # --------------------------------------------------------------- core analysis
    def analyze(self, my: Team, enemy: Team, key_heroes: list[str] | None = None) -> dict:
        s = self.run(my, enemy)
        raws = s.pop("raw")
        base_m = _metrics(raws)
        lost = [r for r in raws if r["winner"] != "A"]
        report = {
            "label": "MODEL ANALYSIS - выводы зависят от допущений (assumptions_used) и неполных данных",
            "summary": {k: s[k] for k in ("n", "model_win_rate", "ci95", "avg_rounds", "draws", "end_reasons")},
            "metrics": base_m,
            "first_round": self._first_round(raws),
            "key_heroes": self._key_heroes(s),
            "strengths_weaknesses": self._sw(base_m, s),
            "loss_causes": self._loss_causes(lost, key_heroes),
            "dangerous_interactions": self._danger(raws),
            "assumptions_used": s["assumptions_used"],
        }
        if key_heroes:
            report["key_hero_death_prob"] = {h: s["heroes"].get(f"A:{h}", {}).get("p_died") for h in key_heroes}
        return report

    def _first_round(self, raws):
        n = len(raws)
        before = Counter()
        for r in raws:
            order = r["first_round"]["order"]
            first_enemy = next((i for i, o in enumerate(order) if o[0][0] == "B"), len(order))
            before[sum(1 for o in order[:first_enemy] if o[0][0] == "A")] += 1
        sample = raws[0]["first_round"]["order"] if raws else []
        return {"order_sample": sample,
                "my_heroes_before_first_enemy": dict(sorted(before.items())),
                "avg_damage": {s: sum(r["first_round"]["damage"][s] for r in raws) / n for s in "AB"},
                "p_any_death_r1": {s: sum(1 for r in raws if any(d.startswith(s) for d in r["first_round"]["deaths"])) / n for s in "AB"},
                "avg_controls_r1": sum(r["first_round"]["controls"] for r in raws) / n}

    def _key_heroes(self, s):
        out = {}
        for side in "AB":
            hs = [(k.split(":", 1)[1], h) for k, h in s["heroes"].items() if k.startswith(side + ":") and k != f"{side}:__team__"]
            hs.sort(key=lambda kv: -(kv[1]["damage_share"] + kv[1]["heal_effective"] / max(1, s["avg_damage"][side] or 1)
                                     + 0.5 * kv[1]["revives_done"] + 0.1 * kv[1]["ctrl_landed"]))
            out["mine" if side == "A" else "enemy"] = [
                {"hero": h, "damage_share": round(v["damage_share"], 3), "heal": round(v["heal_effective"], 1),
                 "revives": round(v["revives_done"], 2), "ctrl_landed": round(v["ctrl_landed"], 2),
                 "survival_rate": round(v.get("survival_rate", 0), 3)} for h, v in hs]
        return out

    def _sw(self, m, s):
        st, wk = [], []
        dm, de = m.get("my_damage", 0), m.get("enemy_damage", 0)
        (st if dm >= de else wk).append(f"Суммарный урон: мой {dm:.0f} vs соперник {de:.0f}")
        r1a, r1b = m.get("r1_my_damage", 0), m.get("r1_enemy_damage", 0)
        (st if r1a >= r1b else wk).append(f"1-й раунд: мой урон {r1a:.0f} vs {r1b:.0f}")
        if m.get("enemy_revives", 0) > 0.3:
            wk.append(f"Соперник воскрешает в среднем {m['enemy_revives']:.2f} раз за бой - "
                      "проверьте запрет воскрешения/добивание")
        if m.get("enemy_ctrl_landed", 0) > m.get("my_ctrl_landed", 0):
            wk.append(f"Контроль соперника {m['enemy_ctrl_landed']:.2f} > мой {m['my_ctrl_landed']:.2f} за бой")
        elif m.get("my_ctrl_landed", 0) > 0:
            st.append(f"Мой контроль {m['my_ctrl_landed']:.2f} ≥ контроль соперника {m.get('enemy_ctrl_landed', 0):.2f}")
        if m.get("my_survival", 0) < 0.3:
            wk.append(f"Низкая выживаемость: {m['my_survival']:.0%} героинь доживают до конца")
        if s["draws"] / max(1, s["n"]) > 0.2:
            wk.append(f"{s['draws'] / s['n']:.0%} боёв упираются в лимит раундов - не хватает урона для добивания")
        return {"strengths": st, "weaknesses": wk}

    def _loss_causes(self, lost, key_heroes):
        if not lost:
            return {"n_lost": 0}
        n = len(lost)
        killers = Counter()
        first = Counter()
        for r in lost:
            for d in r["deaths"]:
                if d["uid"].startswith("A"):
                    killers[f"{d['killer_hero']}/{d['ability']}"] += 1
            mine = [d for d in r["deaths"] if d["uid"].startswith("A")]
            if mine:
                first[mine[0]["hero"]] += 1
        out = {"n_lost": n, "top_killers": killers.most_common(5),
               "first_to_die": {h: c / n for h, c in first.most_common()},
               "avg_rounds_in_losses": sum(r["rounds"] for r in lost) / n,
               "end_reasons": dict(Counter(r["end_reason"] for r in lost))}
        if key_heroes:
            out["key_hero_dead_in_losses"] = {h: sum(1 for r in lost for d in r["deaths"]
                                                     if d["uid"].startswith("A") and d["hero"] == h) / n for h in key_heroes}
        return out

    def _danger(self, raws):
        n = len(raws)
        ab = Counter()
        combos = Counter()
        refl = 0.0
        for r in raws:
            for u in r["units"]:
                if u["side"] != "B":
                    continue
                for a, v in u["by_ability"].items():
                    ab[f"{u['hero']}/{a}"] += v.get("dmg", 0) + v.get("dmg_to_shield", 0)
                combos[u["hero"]] += u.get("combo_triggers", 0)
                refl += u.get("reflected", 0)
        tot = sum(ab.values()) or 1
        return {"enemy_top_damage_sources": [(k, round(v / tot, 3)) for k, v in ab.most_common(6)],
                "enemy_combo_triggers_per_battle": {k: v / n for k, v in combos.most_common() if v},
                "enemy_reflect_damage_per_battle": refl / n}

    # --------------------------------------------------------------- counterpicks
    def evaluate_changes(self, my: Team, enemy: Team, changes: list[dict], n: int | None = None) -> list[dict]:
        """changes: [{"kind": "...", "desc": "...", "apply": callable(team)->team}]"""
        base = self.run(my, enemy, n)
        braw = base["raw"]
        bm = _metrics(braw)
        bw = _wins(braw)
        rows = []
        for ch in changes:
            t = ch["apply"](copy.deepcopy(my))
            c = self.run(t, enemy, n)
            cw = _wins(c["raw"])
            pdiff = paired_diff(bw, cw)
            rows.append({"kind": ch["kind"], "change": ch["desc"], "wr_before": sum(bw) / len(bw), "wr_after": sum(cw) / len(cw),
                         "delta": pdiff["delta"], "ci95": pdiff["ci"], "significant": pdiff["significant"],
                         "reason": explain(bm, _metrics(c["raw"]))})
        rows.sort(key=lambda r: -r["delta"])
        return rows

    def suggest(self, my: Team, enemy: Team, roster=None, rune_alternatives: bool = True, formation: bool = True,
                build_options: dict | None = None, n: int | None = None, max_changes: int = 60) -> dict:
        changes = []
        ids = [h.hero_id for h in my.heroes]
        if roster is not None:
            for out_h in ids:
                for in_h in roster.heroes:
                    if in_h in ids:
                        continue

                    def ap(t, out_h=out_h, in_h=in_h):
                        i = next(k for k, h in enumerate(t.heroes) if h.hero_id == out_h)
                        pos = t.formation.pop(out_h, i)
                        t.heroes[i] = copy.deepcopy(roster.heroes[in_h])
                        t.formation[in_h] = pos
                        return t
                    changes.append({"kind": "замена героини", "desc": f"{out_h} → {in_h}", "apply": ap})
        if formation:
            for a, b in itertools.combinations(ids, 2):
                def ap(t, a=a, b=b):
                    pa, pb = t.position_of(a, ids.index(a)), t.position_of(b, ids.index(b))
                    t.formation[a], t.formation[b] = pb, pa
                    return t
                changes.append({"kind": "формация", "desc": f"поменять местами {a} и {b}", "apply": ap})
        if rune_alternatives and len(my.runes) >= 2:
            for p in itertools.permutations(my.runes):
                if list(p) == my.runes:
                    continue
                changes.append({"kind": "порядок рун", "desc": " → ".join(p),
                                "apply": lambda t, p=p: (setattr(t, "runes", list(p)), t)[1]})
        for hid, fields in (build_options or {}).items():
            for f, alts in fields.items():
                for alt in alts:
                    def ap(t, hid=hid, f=f, alt=alt):
                        hb = next(h for h in t.heroes if h.hero_id == hid)
                        setattr(hb, f, copy.deepcopy(alt))
                        return t
                    kind = {"talents": "таланты", "sigils": "сигилы", "limbs": "лимбы", "pets": "питомцы",
                            "decorations": "украшения", "charm_cards": "карты прелестей"}.get(f, f)
                    changes.append({"kind": kind, "desc": f"{hid}.{f} = {alt}", "apply": ap})
        changes = changes[:max_changes]
        rows = self.evaluate_changes(my, enemy, changes, n)
        return {"label": "MODEL counterpick suggestions (paired Monte Carlo)", "evaluated": len(rows),
                "improvements": [r for r in rows if r["delta"] > 0][:15], "all": rows}

    def best_formation(self, my: Team, enemy: Team, passes: int = 2, n: int | None = None) -> dict:
        """Pairwise-swap hill climbing with CRN (6! = 720 orders is too many for full Monte Carlo)."""
        cur = copy.deepcopy(my)
        cur_wr = sum(_wins(self.run(cur, enemy, n)["raw"])) / (n or self.n)
        trace = [cur_wr]
        ids = [h.hero_id for h in cur.heroes]
        for _ in range(passes):
            improved = False
            for a, b in itertools.combinations(ids, 2):
                t = copy.deepcopy(cur)
                pa, pb = t.position_of(a, ids.index(a)), t.position_of(b, ids.index(b))
                t.formation[a], t.formation[b] = pb, pa
                wr = sum(_wins(self.run(t, enemy, n)["raw"])) / (n or self.n)
                if wr > cur_wr:
                    cur, cur_wr, improved = t, wr, True
                    trace.append(wr)
            if not improved:
                break
        return {"formation": cur.formation, "model_win_rate": cur_wr, "trace": trace}

    def ablation(self, my: Team, enemy: Team, n: int | None = None) -> list[dict]:
        """Contribution of every equipment set / team component: remove it, measure paired ΔWR."""
        changes = []
        for i, h in enumerate(my.heroes):
            if h.limbs:
                changes.append({"kind": "лимбы", "desc": f"снять лимбы у {h.hero_id}",
                                "apply": lambda t, i=i: (setattr(t.heroes[i], "limbs", []), t)[1]})
            if h.pets:
                changes.append({"kind": "питомцы", "desc": f"убрать питомцев у {h.hero_id}",
                                "apply": lambda t, i=i: (setattr(t.heroes[i], "pets", []), t)[1]})
            if h.sigils:
                changes.append({"kind": "сигилы", "desc": f"снять сигилы у {h.hero_id}",
                                "apply": lambda t, i=i: (setattr(t.heroes[i], "sigils", []), t)[1]})
            if h.talents:
                changes.append({"kind": "таланты", "desc": f"снять личные таланты у {h.hero_id}",
                                "apply": lambda t, i=i: (setattr(t.heroes[i], "talents", []), t)[1]})
            if h.decorations:
                changes.append({"kind": "украшения", "desc": f"снять украшения у {h.hero_id}",
                                "apply": lambda t, i=i: (setattr(t.heroes[i], "decorations", []), t)[1]})
        if my.runes:
            changes.append({"kind": "руны", "desc": "без рун", "apply": lambda t: (setattr(t, "runes", []), t)[1]})
        if my.princess_weapon:
            changes.append({"kind": "оружие принцессы", "desc": "без оружия принцессы",
                            "apply": lambda t: (setattr(t, "princess_weapon", []), t)[1]})
        if my.relics:
            changes.append({"kind": "реликты", "desc": "без реликтов", "apply": lambda t: (setattr(t, "relics", []), t)[1]})
        rows = self.evaluate_changes(my, enemy, changes, n)
        for r in rows:
            r["contribution"] = -r["delta"]
        rows.sort(key=lambda r: -r["contribution"])
        return rows


def mode_objective(mode: str) -> dict:
    """Objective weights + filters for the six optimizer modes."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode}; choose from {list(MODES)}")
    return {
        "best_overall": {"weights": {"win_rate": 1.0}},
        "anti_meta": {"weights": {"robust_wr": 1.0, "win_rate": 0.25}},
        "counter": {"weights": {"win_rate": 1.0}},
        "no_donation": {"weights": {"win_rate": 1.0}, "filter": "no_donation"},
        "with_resources": {"weights": {"win_rate": 1.0}, "filter": "inventory"},
        "pve_boss": {"weights": {"win_rate": 0.2, "speed": 1.0}},
    }[mode] | {"description": MODES[mode]}


def filter_roster_no_donation(roster, cat: Catalog):
    """Drop heroes/items flagged donation_only in the catalog (flag must be sourced)."""
    r = copy.deepcopy(roster)
    r.heroes = {h: b for h, b in r.heroes.items() if not cat.get("heroes", h).get("donation_only")}
    for hb in r.heroes.values():
        hb.limbs = [x for x in hb.limbs if not (x and cat.get("limbs", x).get("donation_only"))]
        hb.pets = [x for x in hb.pets if not cat.get("pets", x).get("donation_only")]
        hb.decorations = [x for x in hb.decorations if not (x and cat.get("decorations", x).get("donation_only"))]
    r.rune_pool = [x for x in r.rune_pool if not cat.get("runes", x).get("donation_only")]
    r.pw_pool = [x for x in r.pw_pool if not cat.get("princess_weapon_parts", x).get("donation_only")]
    return r
