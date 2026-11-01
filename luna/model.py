"""Hero / build / team model (stage 4).

Layers are explicit so nothing is counted twice:
  * personal layer  - hero base stats, sigils, talents, limbs, decorations, pets (bond), charm cards
  * team layer      - formation, faction bonus, global stats, runes, princess weapon, relics
A team-layer modifier is applied ONCE per hero at battle start, never copied into a build.

Builds reference catalog IDs (luna.model.Catalog); the catalog entry carries provenance.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .provenance import UNKNOWN, is_unknown, to_json_value, from_json_value

STAT_KEYS = [
    "ATK", "HP", "DEF", "SPD", "CRIT", "CRIT_DMG", "ACC", "DODGE", "DR", "IGNORE_DEF",
    "CTRL_RES", "CTRL_HIT", "HEAL_BONUS", "HEAL_RECV", "MDEF", "CRIT_RES", "DMG_BONUS",
    "PHYS_DMG_BONUS", "MAGIC_DMG_BONUS", "REFLECT", "LIFESTEAL",
    "DMG_TAKEN", "DOT_BONUS", "DOT_TAKEN_RED", "MAGIC_DR", "PHYS_DR", "CRIT_DMG_RES", "DMG_IMMUNITY",
]
# Combat stats expressed as fractions (0.15 == 15 %); everything else is an absolute number.
FRACTION_STATS = {"CRIT", "CRIT_DMG", "ACC", "DODGE", "DR", "IGNORE_DEF", "CTRL_RES", "CTRL_HIT",
                  "HEAL_BONUS", "HEAL_RECV", "CRIT_RES", "DMG_BONUS", "PHYS_DMG_BONUS",
                  "MAGIC_DMG_BONUS", "REFLECT", "LIFESTEAL", "DMG_TAKEN", "DOT_BONUS", "DOT_TAKEN_RED",
                  "MAGIC_DR", "PHYS_DR", "CRIT_DMG_RES", "DMG_IMMUNITY"}

CATALOG_SECTIONS = ["heroes", "sigils", "talents", "limbs", "limb_sets", "decorations", "pets",
                    "charm_cards", "charm_combos", "runes", "princess_weapon_parts", "princess_resonance",
                    "relics", "factions", "formations"]


@dataclass
class StatMod:
    stat: str
    value: float
    mode: str = "flat"          # flat | pct
    source_id: str = ""
    layer: str = "personal"     # personal | team

    @classmethod
    def from_dict(cls, d: dict, layer: str = "personal", source_id: str = "") -> "StatMod":
        return cls(stat=d["stat"], value=d["value"], mode=d.get("mode", "flat"),
                   source_id=d.get("source_id", source_id), layer=d.get("layer", layer))


@dataclass
class Identity:
    id: str
    names: dict = field(default_factory=dict)   # ru/en/jp/kr
    element: Any = UNKNOWN
    cls: Any = UNKNOWN
    role: Any = UNKNOWN
    rarity: Any = UNKNOWN
    faction: Any = UNKNOWN


@dataclass
class Progression:
    level: Any = UNKNOWN
    stars: Any = UNKNOWN
    awakening: Any = UNKNOWN
    skill_levels: dict = field(default_factory=dict)
    upgrades: list = field(default_factory=list)


@dataclass
class HeroBuild:
    """One heroine as fielded by a player."""

    hero_id: str
    progression: Progression = field(default_factory=Progression)
    stats: dict = field(default_factory=dict)          # numbers or "UNKNOWN"
    stats_mode: str = "base"                           # base: build mods still to add | panel: in-game panel (already includes build)
    sigils: list = field(default_factory=list)         # [{"id": sigil_id, "talents": [talent_id, talent_id]}] x2
    talents: list = field(default_factory=list)        # [talent_id] x2 (personal talents - separate system)
    limbs: list = field(default_factory=list)          # [limb_id] x4, index = position
    decorations: list = field(default_factory=list)    # [decoration_id] up to N slots
    pets: list = field(default_factory=list)           # [pet_id]
    charm_cards: list = field(default_factory=list)    # [card_id]
    extra_mods: list = field(default_factory=list)     # [{stat, value, mode, source_id}] other personal boosts
    abilities_override: list | None = None             # replace kit (testing / what-if)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["stats"] = {k: to_json_value(v) for k, v in self.stats.items()}
        d["progression"] = {k: to_json_value(v) if not isinstance(v, (dict, list)) else v
                            for k, v in asdict(self.progression).items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "HeroBuild":
        d = copy.deepcopy(d)
        prog = d.pop("progression", {}) or {}
        prog = Progression(**{k: from_json_value(v) for k, v in prog.items()})
        d["stats"] = {k: from_json_value(v) for k, v in (d.get("stats") or {}).items()}
        return cls(progression=prog, **d)


@dataclass
class Team:
    name: str
    heroes: list[HeroBuild] = field(default_factory=list)
    formation: dict = field(default_factory=dict)      # hero_id -> position index (0..5)
    formation_id: str | None = None
    faction_bonus: list = field(default_factory=list)  # StatMod dicts, team layer
    global_stats: list = field(default_factory=list)   # StatMod dicts, team layer (applied once per hero)
    runes: list = field(default_factory=list)          # rune ids in activation order (4)
    princess_weapon: list = field(default_factory=list)  # part ids by position (4)
    relics: list = field(default_factory=list)         # relic ids
    region: str = "RU"
    balance_version: str = "UNKNOWN"
    notes: str = ""
    status: str = "hypothetical"   # hypothetical | my_roster_confirmed | observed_opponent

    def to_dict(self) -> dict:
        d = asdict(self)
        d["heroes"] = [h.to_dict() for h in self.heroes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        d = copy.deepcopy(d)
        heroes = [HeroBuild.from_dict(h) for h in d.pop("heroes", [])]
        return cls(heroes=heroes, **d)

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Team":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def position_of(self, hero_id: str, default: int) -> int:
        return int(self.formation.get(hero_id, default))


class Catalog:
    """Item / hero definitions for ONE region + balance version. Every entry needs `provenance`."""

    def __init__(self, data: dict | None = None, region: str = "RU", balance_version: str = "UNKNOWN"):
        data = data or {}
        self.region = data.get("region", region)
        self.balance_version = data.get("balance_version", balance_version)
        self.meta = data.get("meta", {})
        self.sections: dict[str, dict] = {s: {} for s in CATALOG_SECTIONS}
        for s in CATALOG_SECTIONS:
            for entry in data.get(s, []):
                self.sections[s][entry["id"]] = entry

    @classmethod
    def load(cls, path: Path) -> "Catalog":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def merge(cls, *cats: "Catalog") -> "Catalog":
        keys = {(c.region, c.balance_version) for c in cats}
        if len(keys) > 1:
            from .provenance import MixedBalanceError
            raise MixedBalanceError(f"cannot merge catalogs of different balance versions: {keys}")
        out = cls(region=cats[0].region, balance_version=cats[0].balance_version)
        for c in cats:
            for s in CATALOG_SECTIONS:
                out.sections[s].update(c.sections[s])
        return out

    def get(self, section: str, item_id: str) -> dict:
        try:
            return self.sections[section][item_id]
        except KeyError:
            raise KeyError(f"{section}:{item_id} not in catalog {self.region}/{self.balance_version}") from None

    def has(self, section: str, item_id: str) -> bool:
        return item_id in self.sections.get(section, {})

    def ids(self, section: str) -> list[str]:
        return list(self.sections[section])

    def to_dict(self) -> dict:
        d = {"region": self.region, "balance_version": self.balance_version, "meta": self.meta}
        for s in CATALOG_SECTIONS:
            d[s] = list(self.sections[s].values())
        return d

    def unsourced_entries(self) -> list[str]:
        bad = []
        for s in CATALOG_SECTIONS:
            for iid, e in self.sections[s].items():
                p = e.get("provenance") or {}
                if not p.get("source") or not p.get("confidence"):
                    bad.append(f"{s}:{iid}")
        return bad


def hero_from_catalog(cat: Catalog, hero_id: str, **overrides) -> HeroBuild:
    """Start a build from the catalog's base stats (may be UNKNOWN)."""
    h = cat.get("heroes", hero_id)
    hb = HeroBuild(hero_id=hero_id, stats={k: from_json_value(v) for k, v in h.get("base_stats", {}).items()},
                   stats_mode=h.get("stats_mode", "base"))
    for k, v in overrides.items():
        setattr(hb, k, v)
    return hb
