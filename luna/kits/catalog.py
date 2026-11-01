"""Build a playable RU catalog from encoded kits + stat samples + the operator roster."""
from __future__ import annotations

import json
from pathlib import Path

from ..engine.assumptions import AssumptionSet
from ..model import Catalog, HeroBuild, Progression, Team
from . import KITS

ROOT = Path(__file__).resolve().parents[2]
SBG_SLUG = {"teselien": "blue-dragon", "vinette": "vignette", "seneren": "senerin", "lucifer": "lucifer",
            "illusia": "elsia", "sbg:hymelle": "hymelle", "kurimu": "crim", "sbg:kira": "kira",
            "sbg:nurse-girl": "nurse-girl", "sbg:chloe": "chloe", "christine": "anubis", "pandora": "pandora"}
RU_NAMES = {"teselien": "Тессарион", "vinette": "Виньетта", "seneren": "Сеньерен", "lucifer": "Люцифер", "illusia": "Иллюсия",
            "sbg:hymelle": "Мяоинь", "kurimu": "Клим", "sbg:kira": "Кира", "sbg:nurse-girl": "Верафиэль", "sbg:chloe": "Хлоя",
            "christine": "Кристина", "pandora": "Пандора"}
VERSION = "ru-client@2026-11-01+kits-v1"


def stat_sample(hero_id: str) -> dict:
    sb = {c["slug"]: c for c in json.loads((ROOT / "data/kb/sbg/characters.json").read_text(encoding="utf-8"))}
    c = sb.get(SBG_SLUG.get(hero_id, ""))
    if c and c["stats"]:
        return {"stats": dict(c["stats"]), "level": c.get("stats_level"), "source": c["url"]}
    return {"stats": {}, "level": None, "source": None}


def build_catalog(awakening: dict, asm: AssumptionSet, heroes: list[str] | None = None) -> Catalog:
    heroes = heroes or list(KITS)
    entries = []
    for hid in heroes:
        kit = KITS[hid](awakening.get(hid), asm)
        smp = stat_sample(hid)
        entries.append({
            "id": hid, "names": {"ru": RU_NAMES.get(hid, hid)}, "role": kit["class"], "class": kit["class"],
            "tags": [f"class:{kit['class']}"], "abilities": kit["abilities"], "kit_notes": kit["notes"],
            "kit_awakening": awakening.get(hid), "base_stats": smp["stats"], "stats_mode": "panel",
            "stats_note": f"образец ур. {smp['level']} с {smp['source']} (kit.stat_sample); звёзды/экипировка образца неизвестны",
            "provenance": {"source": "; ".join(kit["sources"]), "confidence": "medium",
                           "note": "навыки закодированы по тексту (kits-v1); проверить в игре"}})
    return Catalog({"region": "RU", "balance_version": VERSION, "heroes": entries,
                    "meta": {"warning": "Kits encoded from skill texts; stats are lv350 samples, not the operator's panels.",
                             "assumptions": ["kit.ct_semantics", "kit.turn_means_round", "kit.basic_coef",
                                             "kit.constitution_in_panel", "kit.basic_dtype", "kit.stat_sample"]}})


def roster_awakening(path: Path | None = None) -> dict:
    r = json.loads(Path(path or ROOT / "data/user/roster.json").read_text(encoding="utf-8"))
    return {h["hero_id"]: h["progression"].get("awakening") if isinstance(h["progression"].get("awakening"), int) else None
            for h in r["heroes"]}


def team_from(cat: Catalog, name: str, ids: list[str], positions: list[int] | None = None) -> Team:
    hs = [HeroBuild(hero_id=h, stats=dict(cat.get("heroes", h)["base_stats"]), stats_mode="panel",
                    progression=Progression(awakening=cat.get("heroes", h).get("kit_awakening"))) for h in ids]
    return Team(name=name, heroes=hs, formation={h: (positions[i] if positions else i) for i, h in enumerate(ids)},
                region="RU", balance_version=VERSION)
