"""Team + catalog -> battle units. Applies the personal and team stat layers exactly once."""
from __future__ import annotations

import copy
from collections import Counter

from ..model import Catalog, Team, HeroBuild, FRACTION_STATS
from ..provenance import is_unknown
from .assumptions import AssumptionSet
from .state import Unit


class UnknownStatError(ValueError):
    pass


def _mods(entry: dict, layer: str, source_id: str) -> list[dict]:
    out = []
    for m in entry.get("mods", []):
        mm = dict(m)
        mm.setdefault("mode", "flat")
        mm["layer"] = layer
        mm["source_id"] = mm.get("source_id") or source_id
        out.append(mm)
    return out


def personal_sources(hb: HeroBuild, cat: Catalog) -> tuple[list[dict], list[dict]]:
    """(stat mods, abilities) from the personal layer, each tagged with its source."""
    mods, abil = [], []

    def take(section, iid, tag):
        e = cat.get(section, iid)
        for m in _mods(e, "personal", f"{section}:{iid}"):
            if e.get("effect_key"):
                m["effect_key"] = e["effect_key"]
            mods.append(m)
        for a in e.get("abilities", []):
            a = copy.deepcopy(a)
            a.setdefault("source", f"{section}:{iid}")
            a.setdefault("effect_key", e.get("effect_key", a.get("id")))
            if tag:
                a.setdefault("tags", []).append(tag)
            abil.append(a)

    for s in hb.sigils:
        take("sigils", s["id"], "sigil")
        for t in s.get("talents", []):
            take("talents", t, "sigil_talent")
    for t in hb.talents:
        take("talents", t, "personal_talent")
    sets = Counter()
    for lid in hb.limbs:
        if lid:
            take("limbs", lid, "limb")
            sid = cat.get("limbs", lid).get("set")
            if sid:
                sets[sid] += 1
    for sid, n in sets.items():
        if not cat.has("limb_sets", sid):
            continue
        ls = cat.get("limb_sets", sid)
        for thr, bonus in sorted(ls.get("bonuses", {}).items(), key=lambda kv: int(kv[0])):
            if n >= int(thr):
                mods.extend(_mods(bonus, "personal", f"limb_sets:{sid}:{thr}"))
                for a in bonus.get("abilities", []):
                    a = copy.deepcopy(a)
                    a.setdefault("source", f"limb_sets:{sid}:{thr}")
                    a.setdefault("effect_key", a.get("id"))
                    abil.append(a)
    for d in hb.decorations:
        if d:
            take("decorations", d, "decoration")
    for p in hb.pets:
        e = cat.get("pets", p)
        mods.extend(_mods({"mods": e.get("bond_mods", [])}, "personal", f"pets:{p}"))
        for a in e.get("abilities", []):
            a = copy.deepcopy(a)
            a.setdefault("source", f"pets:{p}")
            a.setdefault("effect_key", a.get("id"))
            a.setdefault("tags", []).append("pet")
            abil.append(a)
    cards = set(hb.charm_cards)
    for c in hb.charm_cards:
        take("charm_cards", c, "charm")
    for combo in cat.sections["charm_combos"].values():
        if set(combo.get("requires", [])) <= cards and combo.get("requires"):
            mods.extend(_mods(combo, "personal", f"charm_combos:{combo['id']}"))
    for m in hb.extra_mods:
        mm = dict(m)
        mm.setdefault("mode", "flat")
        mm.setdefault("layer", "personal")
        mods.append(mm)
    return mods, abil


def team_sources(team: Team, cat: Catalog) -> tuple[list[dict], list[dict]]:
    """(team-layer stat mods applied once per hero, team abilities owned by the team source)."""
    mods = [dict(m, layer="team") for m in team.global_stats + team.faction_bonus]
    abil = []
    # faction thresholds defined in catalog
    facs = Counter()
    for h in team.heroes:
        if cat.has("heroes", h.hero_id):
            f = cat.get("heroes", h.hero_id).get("faction")
            if f:
                facs[f] += 1
    for fid, n in facs.items():
        if cat.has("factions", fid):
            for thr, b in sorted(cat.get("factions", fid).get("bonuses", {}).items(), key=lambda kv: int(kv[0])):
                if n >= int(thr):
                    mods.extend(_mods(b, "team", f"factions:{fid}:{thr}"))
    for order, rid in enumerate(team.runes):
        r = copy.deepcopy(cat.get("runes", rid))
        mods.extend(_mods(r, "team", f"runes:{rid}"))
        nested = []
        for n in r.get("nested", []):
            n = dict(n)
            if "rune" in n and cat.has("runes", n["rune"]):
                n.setdefault("effects", cat.get("runes", n["rune"]).get("effects", []))
                n.setdefault("id", n["rune"])
            nested.append(n)
        if r.get("effects") or r.get("trigger"):
            abil.append({"id": f"rune:{rid}", "kind": "rune", "rune_order": order, "trigger": r.get("trigger", {"on": "round_start"}),
                         "effects": r.get("effects", []), "nested": nested, "source": f"runes:{rid}",
                         "effect_key": f"rune:{rid}", "name_ru": r.get("name_ru", rid)})
    sets = Counter()
    for i, pid in enumerate(team.princess_weapon):
        if not pid:
            continue
        p = cat.get("princess_weapon_parts", pid)
        mods.extend(_mods(p, "team", f"princess_weapon_parts:{pid}"))
        if p.get("set"):
            sets[p["set"]] += 1
        for a in p.get("abilities", []):
            a = copy.deepcopy(a)
            a.setdefault("source", f"princess_weapon_parts:{pid}")
            a.setdefault("effect_key", a.get("id"))
            a.setdefault("pw_position", i)
            abil.append(a)
    parts = set(x for x in team.princess_weapon if x)
    for res in cat.sections["princess_resonance"].values():
        req = res.get("requires", {})
        ok = True
        if "parts" in req:
            ok &= set(req["parts"]) <= parts
        if "set" in req:
            ok &= sets.get(req["set"], 0) >= int(req.get("count", 4))
        if ok and req:
            mods.extend(_mods(res, "team", f"princess_resonance:{res['id']}"))
            for a in res.get("abilities", []):
                a = copy.deepcopy(a)
                a.setdefault("source", f"princess_resonance:{res['id']}")
                a.setdefault("effect_key", a.get("id"))
                abil.append(a)
    for rid in team.relics:
        r = cat.get("relics", rid)
        mods.extend(_mods(r, "team", f"relics:{rid}"))
        for a in r.get("abilities", []):
            a = copy.deepcopy(a)
            a.setdefault("source", f"relics:{rid}")
            a.setdefault("effect_key", a.get("id"))
            abil.append(a)
    return mods, abil


def aggregate(base: dict, mods: list[dict]) -> dict:
    """stat.aggregation = (base + Σflat) * (1 + Σpct); fraction stats are additive."""
    out = dict(base)
    flat, pct = Counter(), Counter()
    for m in mods:
        (pct if m.get("mode") == "pct" else flat)[m["stat"]] += m["value"]
    for k in set(flat) | set(pct) | set(base):
        b = base.get(k, 0.0)
        if k in FRACTION_STATS:
            out[k] = b + flat[k] + pct[k]
        else:
            out[k] = (b + flat[k]) * (1 + pct[k])
    return out


def dedupe_abilities(abil: list[dict], asm: AssumptionSet) -> list[dict]:
    keys = Counter(a.get("effect_key", a.get("id")) for a in abil)
    out, seen = [], set()
    for a in abil:
        k = a.get("effect_key", a.get("id"))
        if keys[k] > 1:
            pol = asm.stacking_for(k)
            if pol == "unique":
                if k in seen:
                    continue
                seen.add(k)
        out.append(a)
    return out


def dedupe_mods(mods: list[dict], asm: AssumptionSet) -> list[dict]:
    """Duplicate talents (same effect_key from different items) follow stack.duplicate_effect."""
    sources: dict[str, list[str]] = {}
    for m in mods:
        k = m.get("effect_key")
        if k:
            sources.setdefault(k, [])
            if m["source_id"] not in sources[k]:
                sources[k].append(m["source_id"])
    out = []
    for m in mods:
        k = m.get("effect_key")
        if k and len(sources[k]) > 1 and asm.stacking_for(k) == "unique" and m["source_id"] != sources[k][0]:
            continue
        out.append(m)
    return out


def build_units(team: Team, cat: Catalog, side: str, asm: AssumptionSet, stat_fill=None) -> list[Unit]:
    """stat_fill(hero_id, stat) -> number : used ONLY for stats that are UNKNOWN (simulations with unknowns)."""
    if team.region != cat.region:
        from ..provenance import MixedBalanceError
        raise MixedBalanceError(f"team region {team.region} != catalog region {cat.region}")
    t_mods, t_abil = team_sources(team, cat)
    units = []
    for i, hb in enumerate(team.heroes):
        hero = cat.get("heroes", hb.hero_id)
        base = {}
        for k, v in hb.stats.items():
            if is_unknown(v):
                if stat_fill is None:
                    raise UnknownStatError(f"{hb.hero_id}.{k} is UNKNOWN; pass stat_fill (prior) for a what-if run")
                v = stat_fill(hb.hero_id, k)
                asm.used.add(f"prior:{hb.hero_id}.{k}")
            base[k] = float(v)
        p_mods, p_abil = personal_sources(hb, cat)
        p_mods = dedupe_mods(p_mods, asm)
        if hb.stats_mode == "panel":
            mods = [] if asm.get("stat.panel_includes_team") else list(t_mods)
        else:
            mods = p_mods + t_mods
        stats = aggregate(base, mods)
        kit = copy.deepcopy(hb.abilities_override if hb.abilities_override is not None else hero.get("abilities", []))
        for a in kit:
            a.setdefault("effect_key", a.get("id"))
            a.setdefault("source", f"heroes:{hb.hero_id}")
        abilities = dedupe_abilities(kit + p_abil, asm)
        u = Unit(uid=f"{side}{team.position_of(hb.hero_id, i)}", side=side, pos=team.position_of(hb.hero_id, i),
                 hero_id=hb.hero_id, name=hero.get("names", {}).get("ru") or hero.get("names", {}).get("en") or hb.hero_id,
                 stats=stats, abilities=abilities)
        u.tags.update(hero.get("tags", []))
        u.tags.add(f"role:{hero.get('role', 'UNKNOWN')}")
        units.append(u)
    # team source: holds runes / princess weapon / relic abilities (not targetable, never dies)
    src_mode = asm.get("team_source.stats")
    if units:
        if src_mode == "team_avg":
            ss = {k: sum(u.stats.get(k, 0) for u in units) / len(units) for k in units[0].stats}
        else:
            best = max(units, key=lambda u: u.stats.get("ATK", 0))
            ss = dict(best.stats)
    else:
        ss = {}
    ss["HP"] = 1.0
    ts = Unit(uid=f"{side}T", side=side, pos=99, hero_id="__team__", name=f"Команда {side}", stats=ss,
              abilities=t_abil, is_team_source=True)
    return units + [ts]
