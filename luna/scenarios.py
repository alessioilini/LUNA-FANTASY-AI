"""Stage 9: known compositions (Team A / Team B / Seraphia-Nyxara-Seneren + 3 unknown) and hypothesis tests.

IMPORTANT - what this is and is not:
  * No RU skill texts or numbers could be fetched (network policy), so every kit below is a GENERIC
    ROLE TEMPLATE (confidence: hypothesis). The template choice is driven by the evidence available:
      Lucifer   -> magic AoE + abnormal-status amplification   (JP Dengeki/AppMedia snippets, LOW)
      Vignette  -> revive specialist support                    (JP AppMedia snippet, LOW)
      Seneren   -> team buffer + revive durability              (JP AppMedia snippet for セネリン, name-mapping hypothesis)
      Verafiel  -> support                                      (operator statement)
      Illusia   -> guardian/counter/poison                      (HYPOTHESIS: Illusia = エルシア)
      others    -> generic attacker (no evidence of role)
  * Stats are UNKNOWN and sampled from the SAME wide priors for every heroine (scale anchored to the
    JP AppMedia Vignette sample). Results therefore reflect structure (roles, mechanics), not real balance.
  * Hypothesis magnitudes (+20 % penetration etc.) are what-if inputs, not game values.
  * A conclusion is reported as robust only if its sign holds under every assumption variant.
"""
from __future__ import annotations

import copy
import itertools
import random

from .engine.assumptions import AssumptionSet
from .model import Catalog, Team, HeroBuild
from .provenance import UNKNOWN
from .sim.montecarlo import PriorBook, StatPrior, simulate
from .sim.stats import paired_diff

WHATIF_VERSION = "what-if:role-templates-v1"
P_HYP = {"source": "luna.scenarios role templates", "confidence": "hypothesis",
         "note": "Generic role template - NOT the real skill. Replace with sourced kit when available."}

HEROES = {
    # id: (ru name or None, template, evidence)
    "hymelle": (None, "generic_attacker", "no role evidence"),
    "lucifer": (None, "magic_aoe_dot", "JP: 闇属性 魔法使い 魔法範囲爆裂; amplifies abnormal-status damage (LOW)"),
    "klim": (None, "generic_attacker", "no role evidence"),
    "seneren": (None, "support_buffer", "JP セネリン: team buff by class, revive durability (LOW, mapping hypothesis)"),
    "vignette": (None, "support_revive", "JP ヴィネット: revives up to 3 allies, passive revives others (LOW)"),
    "kira": (None, "generic_attacker", "no role evidence"),
    "illusia": (None, "guardian_counter_poison", "HYPOTHESIS Illusia=エルシア: barrier, counter, poison (LOW)"),
    "verafiel": ("Верафиэль", "support_healer", "operator: Верафиэль - поддержка"),
    "chloe": (None, "generic_attacker", "no role evidence"),
    "seraphia": (None, "generic_attacker", "alias «Монашка»; no role evidence"),
    "nyxara": (None, "generic_attacker", "no role evidence"),
}
ROLE = {"generic_attacker": "attacker", "magic_aoe_dot": "attacker", "support_buffer": "support",
        "support_revive": "support", "support_healer": "support", "guardian_counter_poison": "tank"}


def template(name: str, hid: str) -> list[dict]:
    B = lambda coef=1.0, dt="physical": {"id": f"{hid}_basic", "kind": "basic", "tags": [dt],
                                         "effects": [{"op": "damage", "target": "enemy_single", "coef": coef, "dtype": dt}]}
    if name == "generic_attacker":
        return [B(), {"id": f"{hid}_skill", "kind": "active", "priority": 5, "trigger": {"on": "turn", "cooldown": 2},
                      "tags": ["physical"], "effects": [{"op": "damage", "target": "enemy_single", "coef": 2.2}]}]
    if name == "magic_aoe_dot":
        return [B(1.0, "magic"),
                {"id": f"{hid}_burst", "kind": "active", "priority": 5, "trigger": {"on": "turn", "cooldown": 2}, "tags": ["magic"],
                 "effects": [{"op": "damage", "target": "enemy_all", "coef": 0.7, "dtype": "magic", "bonus_vs_status": {"burn": 0.3}},
                             {"op": "status", "target": "hit", "status": {"key": "burn", "dot": {"coef": 0.12, "stat": "ATK", "dtype": "true"},
                                                                          "duration": 2, "stacking": "refresh"}}]}]
    if name == "support_buffer":
        return [B(0.6),
                {"id": f"{hid}_aura", "kind": "passive", "trigger": {"on": "battle_start"},
                 "effects": [{"op": "status", "target": "ally_all", "status": {"key": f"{hid}_aura", "kind": "buff", "undispellable": True,
                              "mods": [{"stat": "ATK", "value": 0.10, "mode": "pct"}, {"stat": "DEF", "value": 0.10, "mode": "pct"}]}}]},
                {"id": f"{hid}_rebirth", "kind": "passive", "trigger": {"on": "self_death", "per_battle": 1},
                 "effects": [{"op": "revive", "target": "self", "hp_pct": 0.5}]}]
    if name == "support_revive":
        return [B(0.5),
                {"id": f"{hid}_mass_revive", "kind": "active", "priority": 9,
                 "trigger": {"on": "turn", "cooldown": 4, "dead_ally_ge": 1},
                 "effects": [{"op": "revive", "target": "dead_allies", "count": 3, "hp_pct": 0.3}]},
                {"id": f"{hid}_guardian_angel", "kind": "passive", "trigger": {"on": "ally_death", "per_battle": 1},
                 "effects": [{"op": "revive", "target": "dead_ally_random", "count": 1, "hp_pct": 0.3}]}]
    if name == "support_healer":
        return [B(0.5),
                {"id": f"{hid}_heal", "kind": "active", "priority": 6, "trigger": {"on": "turn", "cooldown": 1, "ally_hp_below": 0.8},
                 "effects": [{"op": "heal", "target": "ally_lowest_hp:2", "coef": 1.6}]},
                {"id": f"{hid}_ward", "kind": "passive", "trigger": {"on": "battle_start"},
                 "effects": [{"op": "shield", "target": "ally_all", "coef": 0.8, "duration": 2}]}]
    if name == "guardian_counter_poison":
        return [B(0.7),
                {"id": f"{hid}_barrier", "kind": "passive", "trigger": {"on": "battle_start"},
                 "effects": [{"op": "shield", "target": "ally_all", "coef": 1.0, "duration": 3}]},
                {"id": f"{hid}_counter", "kind": "passive", "trigger": {"on": "damaged", "per_round": 2},
                 "effects": [{"op": "damage", "target": "attacker", "coef": 0.5},
                             {"op": "status", "target": "hit", "status": {"key": "poison", "dot": {"coef": 0.08, "stat": "ATK", "dtype": "true"},
                                                                          "duration": 2, "stacking": "stack", "max_stacks": 3}}]}]
    raise ValueError(name)


def whatif_catalog() -> Catalog:
    heroes = []
    for hid, (ru, tpl, ev) in HEROES.items():
        heroes.append({"id": hid, "names": {"ru": ru, "en": hid.capitalize()}, "role": ROLE[tpl], "template": tpl,
                       "base_stats": {k: "UNKNOWN" for k in ("ATK", "HP", "DEF", "SPD", "CRIT", "CRIT_DMG", "CTRL_RES")},
                       "abilities": template(tpl, hid), "tags": [ROLE[tpl]], "evidence": ev, "provenance": P_HYP})
    return Catalog({"region": "RU", "balance_version": WHATIF_VERSION, "heroes": heroes,
                    "meta": {"warning": "WHAT-IF catalog: generic role templates + priors. Not Luna Fantasy data."}})


def default_priors() -> PriorBook:
    # Scale anchor: JP AppMedia Vignette sample (ATK 112,804 / HP 1,166,073 / DEF 5,174 / SPD 4,677), LOW confidence.
    pb = PriorBook(label="symmetric-wide-v1 (JP-scale anchored)")
    for stat, lo, hi in [("ATK", 80_000, 140_000), ("HP", 800_000, 1_400_000), ("DEF", 3_000, 7_000), ("SPD", 3_500, 5_000),
                         ("CRIT", 0.05, 0.30), ("CRIT_DMG", 1.5, 2.0), ("CTRL_RES", 0.0, 0.2)]:
        pb.priors[("*", stat)] = StatPrior(lo, hi)
    return pb


def team(name: str, ids: list[str]) -> Team:
    hs = [HeroBuild(hero_id=h, stats={k: UNKNOWN for k in ("ATK", "HP", "DEF", "SPD", "CRIT", "CRIT_DMG", "CTRL_RES")}) for h in ids]
    return Team(name=name, heroes=hs, formation={h: i for i, h in enumerate(ids)}, region="RU",
                balance_version=WHATIF_VERSION, status="hypothetical",
                notes="Test composition from the brief - NOT the operator's confirmed roster")


TEAM_A = ["hymelle", "lucifer", "klim", "seneren", "vignette", "kira"]
TEAM_B = ["illusia", "kira", "verafiel", "seneren", "lucifer", "chloe"]
SCEN3_FIXED = ["seraphia", "nyxara", "seneren"]

VARIANTS = {
    "v1/kill-first": AssumptionSet.preset("exploratory_v1", **{"death.trigger_order": "kill_effects_first", "battle.max_rounds": 15, "battle.draw_result": "hp_percent"}),
    "v1/death-first": AssumptionSet.preset("exploratory_v1", **{"death.trigger_order": "death_effects_first", "battle.max_rounds": 15, "battle.draw_result": "hp_percent"}),
    "alt/kill-first": AssumptionSet.preset("exploratory_v1_alt", **{"death.trigger_order": "kill_effects_first", "battle.max_rounds": 15, "battle.draw_result": "hp_percent"}),
    "alt/death-first": AssumptionSet.preset("exploratory_v1_alt", **{"death.trigger_order": "death_effects_first", "battle.max_rounds": 15, "battle.draw_result": "hp_percent"}),
}


# ------------------------------------------------------------------ hypothesis modifiers
def _mod_all(t: Team, ids, stat, value, mode="flat", tag=""):
    for h in t.heroes:
        if ids is None or h.hero_id in ids:
            h.extra_mods.append({"stat": stat, "value": value, "mode": mode, "source_id": f"whatif:{tag}:{h.hero_id}"})
    return t


def _add_ability(t: Team, hid: str, ab: dict, cat: Catalog):
    hb = next(h for h in t.heroes if h.hero_id == hid)
    kit = copy.deepcopy(hb.abilities_override if hb.abilities_override is not None else cat.get("heroes", hid)["abilities"])
    kit.append(ab)
    hb.abilities_override = kit
    return t


def hypotheses(cat: Catalog) -> dict:
    attackers = [h for h, (_, tpl, _) in HEROES.items() if ROLE[tpl] == "attacker"]
    return {
        "H1_penetration": {"desc": "Пробитие: +20% игнорирования защиты атакующим героиням команды",
                           "apply": lambda t: _mod_all(t, attackers, "IGNORE_DEF", 0.20, tag="pen")},
        "H2_magic_combo": {"desc": "Магическое комбо: Люцифер получает 30% шанс доп. атаки после магической атаки",
                           "apply": lambda t: _add_ability(t, "lucifer", {"id": "lucifer_magic_combo", "kind": "passive",
                                    "trigger": {"on": "after_attack", "chance": 0.3, "ability_tag": "magic"},
                                    "effects": [{"op": "extra_attack", "ability": "basic"}]}, cat) if any(h.hero_id == "lucifer" for h in t.heroes) else t},
        "H3_speed": {"desc": "Скорость: +10% СКР всей команде", "apply": lambda t: _mod_all(t, None, "SPD", 0.10, "pct", "spd")},
        "H4_defense": {"desc": "Защита: +20% DEF всей команде", "apply": lambda t: _mod_all(t, None, "DEF", 0.20, "pct", "def")},
        "H5_anti_revive": {"desc": "Запрет воскрешения: Кира накладывает запрет воскрешения (3 хода) при убийстве",
                           "apply": lambda t: _add_ability(t, "kira", {"id": "kira_revive_ban", "kind": "passive", "trigger": {"on": "kill"},
                                    "effects": [{"op": "status", "target": "event_target", "status": {"key": "revive_ban", "kind": "debuff",
                                                 "revive_ban": True, "duration": 3}}]}, cat) if any(h.hero_id == "kira" for h in t.heroes) else t},
        "H6_soul_eater": {"desc": "Пожиратель душ", "blocked": "Эффект «Пожиратель душ» не найден ни в одном доступном источнике: "
                          "текст и числа UNKNOWN. Проверка невозможна без выдумывания механики - заблокировано."},
    }


def run_hypotheses(n: int = 400, seed: int = 2026, workers: int = 4) -> dict:
    cat = whatif_catalog()
    pri = default_priors()
    A, B = team("Команда A", TEAM_A), team("Команда B", TEAM_B)
    out = {"label": "WHAT-IF (structure-only): role templates + symmetric priors; not real balance",
           "n_per_run": n, "seed": seed, "priors": pri.to_dict(), "variants": list(VARIANTS), "results": {}}
    base = {}
    for vname, asm in VARIANTS.items():
        s = simulate(A, B, cat, asm, n=n, seed=seed, priors=pri, workers=workers, keep_raw=True)
        base[vname] = s
    out["baseline_A_vs_B"] = {v: {"model_win_rate": s["model_win_rate"], "ci95": s["ci95"], "avg_rounds": s["avg_rounds"],
                                  "draws": s["draws"]} for v, s in base.items()}
    for hname, h in hypotheses(cat).items():
        if "blocked" in h:
            out["results"][hname] = {"desc": h["desc"], "status": "BLOCKED", "reason": h["blocked"]}
            continue
        rows = {}
        for direction, (mine, opp) in {"A_vs_B": (A, B), "B_vs_A": (B, A)}.items():
            for vname, asm in VARIANTS.items():
                if direction == "A_vs_B":
                    braw = base[vname]["raw"]
                else:
                    braw = simulate(mine, opp, cat, asm, n=n, seed=seed, priors=pri, workers=workers, keep_raw=True)["raw"]
                mod = h["apply"](copy.deepcopy(mine))
                craw = simulate(mod, opp, cat, asm, n=n, seed=seed, priors=pri, workers=workers, keep_raw=True)["raw"]
                bw = [1.0 if r["winner"] == "A" else 0.0 for r in braw]
                cw = [1.0 if r["winner"] == "A" else 0.0 for r in craw]
                d = paired_diff(bw, cw)
                rows[f"{direction}|{vname}"] = {"wr_before": sum(bw) / n, "wr_after": sum(cw) / n, "delta": d["delta"],
                                                "ci95": d["ci"], "significant": d["significant"]}
        signs = {(1 if r["delta"] > 0 else -1 if r["delta"] < 0 else 0) for r in rows.values() if r["significant"]}
        sig = sum(1 for r in rows.values() if r["significant"])
        verdict = ("robust_positive" if signs == {1} and sig == len(rows) else
                   "robust_negative" if signs == {-1} and sig == len(rows) else
                   "depends_on_assumptions" if len(signs) > 1 else
                   "positive_in_some_variants" if signs == {1} else
                   "negative_in_some_variants" if signs == {-1} else "no_significant_effect")
        out["results"][hname] = {"desc": h["desc"], "runs": rows, "verdict": verdict}
    return out


def scenario3(n_fill: int = 24, n: int = 120, seed: int = 77, workers: int = 4) -> dict:
    """Seraphia + Nyxara + Seneren + 3 unknown heroines: distribution over random fill-ins."""
    cat = whatif_catalog()
    pri = default_priors()
    asm = VARIANTS["v1/kill-first"]
    pool = [h for h in HEROES if h not in SCEN3_FIXED]
    rng = random.Random(seed)
    fills = set()
    while len(fills) < min(n_fill, len(list(itertools.combinations(pool, 3)))):
        fills.add(tuple(sorted(rng.sample(pool, 3))))
    rows = []
    for f in sorted(fills):
        t = team("Сценарий 3", SCEN3_FIXED + list(f))
        r = {"fill": list(f)}
        for oname, opp in (("vs_A", team("A", TEAM_A)), ("vs_B", team("B", TEAM_B))):
            s = simulate(t, opp, cat, asm, n=n, seed=seed, priors=pri, workers=workers)
            r[oname] = s["model_win_rate"]
        r["mean"] = (r["vs_A"] + r["vs_B"]) / 2
        rows.append(r)
    rows.sort(key=lambda r: -r["mean"])
    means = [r["mean"] for r in rows]
    return {"label": "WHAT-IF: unknown 3 heroines sampled from the named pool (generic templates)",
            "fixed": SCEN3_FIXED, "n_fill_ins": len(rows), "n_per_matchup": n,
            "wr_distribution": {"min": min(means), "median": sorted(means)[len(means) // 2], "max": max(means)},
            "best_fill_ins": rows[:5], "worst_fill_ins": rows[-3:], "all": rows}
