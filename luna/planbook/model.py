"""Model component of the build weights: paired Monte Carlo (common random numbers) with the project simulator.

What is measured (MODEL values, not real win rates):
  * limb 2-piece bonus      - +X% of one stat for one heroine of my team, mirror match vs. the unchanged team
  * kit contribution         - the heroine's encoded skills replaced by a plain basic attack (same stats)
Metric per battle: 1 win / 0 loss; a draw (round limit) scores 0.5 + 0.5*(HP share A - HP share B), because
uncalibrated battles often hit the 15-round limit and a pure win/loss would hide every effect.
Only 2-piece bonuses that are a plain stat are modelled; 4-piece effects are conditional and NOT encoded.
Heroines without an operator panel get stats scaled from the JP lv350 sample by the median panel/sample
ratio of the heroines that have both (assumption 'planbook.stat_scale', documented in the workbook).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import statistics
from pathlib import Path

from ..engine.assumptions import AssumptionSet
from ..kits.catalog import build_catalog, operator_panel, roster_awakening, stat_sample, team_from
from ..model import Catalog
from ..sim.montecarlo import simulate
from ..sim.stats import paired_diff
from . import terms as T

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "planbook" / "model_cache.json"
KIT_ID = {"hymelle": "sbg:hymelle", "kira": "sbg:kira", "nurse-girl": "sbg:nurse-girl", "chloe": "sbg:chloe"}
PCT_STATS = {"ATK", "HP", "SPD", "DEF"}
BONUS_RE = [
    (r"^АТК \+(\d+)%", "ATK"), (r"^ОЗ \+(\d+)%", "HP"), (r"^СКР \+(\d+)%", "SPD"), (r"^ЗАЩ \+(\d+)%", "DEF"),
    (r"^Урон от крита \+(\d+)%", "CRIT_DMG"), (r"^Шанс крита \+(\d+)%", "CRIT"), (r"^Крит\. СОПР \+(\d+)%", "CRIT_RES"),
    (r"^Сопротивление урону \+(\d+)%", "DR"), (r"^СОПР крит\. УРН \+(\d+)%", "CRIT_DMG_RES"),
    (r"^Лечение \+(\d+)%", "HEAL_BONUS"), (r"^Урон \+(\d+)%", "DMG_BONUS"),
]


def kit_id(hero: str) -> str:
    return KIT_ID.get(hero, hero)


def limb_two_piece() -> dict[str, tuple[str, float] | None]:
    out = {}
    for x in T.entities():
        if x["kind"] != "limb":
            continue
        two = next((f["text"] for f in x.get("effects", []) if f["label"].startswith("2")), "")
        out[x["id"].split(":", 1)[1]] = None
        for rx, stat in BONUS_RE:
            m = re.match(rx, two.strip())
            if m:
                out[x["id"].split(":", 1)[1]] = (stat, int(m.group(1)) / 100)
                break
    return out


def _score(raws: list[dict]) -> list[float]:
    xs = []
    for r in raws:
        if r["winner"] == "A":
            xs.append(1.0)
        elif r["winner"] == "B":
            xs.append(0.0)
        else:
            mx = {"A": 0.0, "B": 0.0}
            for u in r["units"]:
                if not u.get("team_source"):
                    mx[u["side"]] += u["max_hp"]
            fa = r["hp_left"]["A"] / mx["A"] if mx["A"] else 0
            fb = r["hp_left"]["B"] / mx["B"] if mx["B"] else 0
            xs.append(0.5 + 0.5 * (fa - fb))
    return xs


def scaled_catalog(team_kits: list[str], asm: AssumptionSet) -> tuple[Catalog, dict]:
    cat = build_catalog(roster_awakening(), asm, heroes=team_kits)
    ratios = {s: [] for s in PCT_STATS}
    for h in team_kits:
        op = operator_panel(h)
        js = stat_sample(h, "sbg_lv350_panel")["stats"]
        if op and js:
            for s in PCT_STATS:
                if js.get(s) and op["stats"].get(s):
                    ratios[s].append(op["stats"][s] / js[s])
    scale = {s: statistics.median(v) for s, v in ratios.items() if v}
    notes = {}
    for h in team_kits:
        if operator_panel(h) is None and scale:
            e = cat.get("heroes", h)
            for s, f in scale.items():
                if s in e["base_stats"]:
                    e["base_stats"][s] *= f
            e["stats_note"] = f"оценка: образец JP 350 ур. × медиана отношения панель/образец ({', '.join(f'{k} ×{v:.1f}' for k, v in scale.items())})"
            notes[h] = e["stats_note"]
    return cat, notes


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:20]


def run(team: list[str], limb_cands: dict[str, list[str]], n: int = 120, seed: int = 11, preset: str = "exploratory_v1",
        workers: int = 4, progress=print) -> dict:
    """team: planbook hero slugs; limb_cands: hero -> limb set ids to evaluate. Returns the model table."""
    asm = AssumptionSet.preset(preset)
    kits = [kit_id(h) for h in team]
    from ..kits import KITS
    missing = [h for h, k in zip(team, kits) if k not in KITS]
    if missing:
        return {"status": "skipped", "reason": f"нет закодированных навыков для: {', '.join(missing)}",
                "limb": {}, "kit": {}, "baseline": None}
    cat, notes = scaled_catalog(kits, asm)
    base_team = team_from(cat, "main", kits)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    ck_base = _key("base", kits, n, seed, preset, asm.fingerprint(), cat.to_dict())

    def arm(label, team_obj, catalog):
        k = _key(ck_base, label, team_obj.to_dict(), catalog.to_dict() if catalog is not cat else None)
        if k in cache:
            return cache[k]
        raws = simulate(team_obj, base_team, catalog, asm, n=n, seed=seed, workers=workers, keep_raw=True,
                        cat_b=cat)["raw"]
        cache[k] = _score(raws)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
        return cache[k]

    progress(f"  модель: базовый прогон {n} боёв")
    base = arm("base", base_team, cat)
    out = {"status": "ok", "n": n, "seed": seed, "preset": preset, "stat_notes": notes, "baseline": sum(base) / len(base),
           "metric": "1 победа / 0 поражение / ничья 0.5+0.5·(доля ОЗ A − доля ОЗ B)", "limb": {}, "kit": {}}
    two = limb_two_piece()
    done = {}
    for h, kid in zip(team, kits):
        for limb in limb_cands.get(h, []):
            bonus = two.get(limb)
            if not bonus:
                continue
            if (h, bonus) not in done:
                t2 = copy.deepcopy(base_team)
                hb = next(x for x in t2.heroes if x.hero_id == kid)
                stat, val = bonus
                if stat in PCT_STATS:
                    hb.stats[stat] = hb.stats.get(stat, 0) * (1 + val)
                else:
                    hb.stats[stat] = hb.stats.get(stat, 0) + val
                progress(f"  модель: {h} {stat} +{val:.0%}")
                xs = arm(f"{h}:{stat}:{val}", t2, cat)
                done[(h, bonus)] = paired_diff(base, xs)
            d = done[(h, bonus)]
            out["limb"][f"{h}|{limb}"] = {"stat": bonus[0], "value": bonus[1], "delta": d["delta"],
                                          "ci95": list(d["ci"])}
        cat2 = Catalog(copy.deepcopy(cat.to_dict()))
        e = cat2.get("heroes", kid)
        e["abilities"] = [a for a in e["abilities"] if a.get("kind") == "basic"]
        progress(f"  модель: {h} без навыков")
        xs = arm(f"{h}:no_kit", base_team, cat2)
        d = paired_diff(base, xs)
        out["kit"][h] = {"delta": d["delta"], "ci95": list(d["ci"])}
    return out
