"""Turn the cached lunafantasy.ru crawl into: entity dump, KB facts, RU catalog, builds, page snapshots.

Usage:  python -m luna.collector.lfru_import [--snapshot 2026-10-31]
Inputs: data/cache/lfru/manifest.json + *.html.gz (made by the polite crawler, robots.txt respected).
Outputs (all regenerated, all provenance-tagged):
  data/kb/lfru/entities.json        merged entity index exactly as published by the site
  data/kb/lfru/builds.json          recommended builds per heroine (sigil pairs, personal talents, limbs, pets, accessories)
  data/kb/lfru/pages/*.txt          visible text of rule/reference pages (battle, teams, roles, localization, ...)
  data/kb/facts/RU.lfru.jsonl       facts (region RU, balance_version lunafantasy.ru@<snapshot>)
  data/kb/catalog_RU.json           catalog for the engine; skill texts kept verbatim, only exact stat-only effects encoded
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter, OrderedDict
from pathlib import Path

from . import lunafantasy as L

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "kb" / "lfru"
FACTS = ROOT / "data" / "kb" / "facts" / "RU.lfru.jsonl"
CATALOG = ROOT / "data" / "kb" / "catalog_RU.json"
TEXT_PAGES = ["battle", "teams", "roles", "localization", "tier-list", "runes", "princess-weapons", "limbs", "sigils",
              "relics", "charm-cards", "pets", "talents", "accessories", "materials", "sources", "guides", "builds"]
ELEMENTS = {"Огонь", "Вода", "Свет", "Тьма", "Ветер", "Лед", "Лёд", "Звездный свет", "Звёздный свет", "Земля", "Природа"}
CLASSES = {"Поддержка": "support", "Страж": "tank", "Маг": "mage", "Воин": "warrior", "Стрелок": "ranged",
           "Убийца": "assassin", "Жрец": "support"}
TIERS = {"SSS", "SS", "S", "A", "B", "C", "D"}
JP_RX = re.compile(r"[぀-ヿ一-鿿]")


def load_pages() -> list[tuple[str, str]]:
    man = json.loads((L.CACHE / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for url, m in man.items():
        if m.get("status") == 200 and m.get("file"):
            out.append((url, gzip.open(L.CACHE / m["file"], "rt", encoding="utf-8").read()))
    return out, man


def fact(key, value, prov, snapshot, url, ru_name=None, original=None, notes=""):
    n = [f"site_status={prov['site_status']}", f"site_confidence={prov['site_confidence']}"]
    if prov["primary_sources"]:
        n.append("primary=" + " ".join(dict.fromkeys(prov["primary_sources"]))[:400])
    if prov["derived_from_jp_appmedia"]:
        n.append("DERIVED FROM JP AppMedia data - numbers may differ from RU client balance")
    if notes:
        n.append(notes)
    return {"key": key, "value": value, "region": "RU", "balance_version": f"lunafantasy.ru@{snapshot}",
            "version_date": snapshot, "source": {"url": url, "title": "lunafantasy.ru", "accessed": snapshot, "kind": "web"},
            "confidence": prov["confidence"], "ru_status": prov["ru_status"], "ru_name": ru_name,
            "original_name": original, "notes": "; ".join(n)}


def hero_slug(o: dict) -> str:
    return o["href"].rstrip("/").split("/")[-1] if o.get("href", "").startswith("/characters/") else o["id"].split(":", 1)[1]


def run(snapshot: str) -> dict:
    pages, man = load_pages()
    allobjs = []
    builds = {}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "pages").mkdir(exist_ok=True)
    for url, html in pages:
        txt = L.rsc_text(html)
        allobjs += L.entities(txt)
        path = url.replace(L.SITE, "").strip("/")
        if path.startswith("characters/") and path.count("/") == 1:
            b = L.character_build(html)
            b["source"] = url
            builds[path.split("/")[1]] = b
        if path in TEXT_PAGES:
            (OUT / "pages" / f"{path}.txt").write_text("\n".join(L.page_text(html)), encoding="utf-8")
    ents = L.merge_entities([o for o in allobjs if o.get("kind") in L.KINDS])
    (OUT / "entities.json").write_text(json.dumps(list(ents.values()), ensure_ascii=False, indent=0), encoding="utf-8")
    (OUT / "builds.json").write_text(json.dumps(builds, ensure_ascii=False, indent=1), encoding="utf-8")

    facts, cat = [], {"region": "RU", "balance_version": f"lunafantasy.ru@{snapshot}",
                      "meta": {"source": L.SITE, "snapshot": snapshot,
                               "warning": "Skill texts are verbatim from lunafantasy.ru. Most hero numbers there are derived "
                                          "from JP AppMedia (see provenance.derived_from_jp_appmedia). Hero abilities are NOT "
                                          "encoded for the engine yet (kit_status=text_only); only exact stat-only item effects "
                                          "are encoded as mods.",
                               "pages_ok": sum(1 for m in man.values() if m.get("status") == 200)}}
    for s in ("heroes", "sigils", "talents", "limbs", "limb_sets", "decorations", "pets", "charm_cards", "charm_combos",
              "runes", "princess_weapon_parts", "princess_resonance", "relics", "factions", "formations"):
        cat[s] = []
    encoded = Counter()
    for oid, o in ents.items():
        kind = o["kind"]
        prov = L.site_provenance(o)
        url = L.SITE + o["href"] if str(o.get("href", "")).startswith("/") else L.SITE
        title = o.get("title")
        jp = next((a for a in o.get("aliases", []) if JP_RX.search(a)), None)
        p_cat = {"source": url, "confidence": prov["confidence"], "ru_status": prov["ru_status"],
                 "site_status": prov["site_status"], "site_confidence": prov["site_confidence"],
                 "primary_sources": list(dict.fromkeys(prov["primary_sources"])),
                 "derived_from_jp_appmedia": prov["derived_from_jp_appmedia"]}
        if kind == "character":
            hid = hero_slug(o)
            parts = L.subtitle_parts(o.get("subtitle"))
            tags = o.get("tags", [])
            element = next((p for p in parts if p in ELEMENTS), None)
            cls = next((p for p in parts if p in CLASSES), None)
            rarity = parts[0] if parts else None
            tier = next((t for t in tags if t in TIERS), None)
            stats = L.parse_stats(o)
            k = f"hero.{hid}"
            facts.append(fact(f"{k}.name.ru", title, prov, snapshot, url, ru_name=title, original=jp))
            facts.append(fact(f"{k}.aliases", o.get("aliases", []), prov, snapshot, url))
            if jp:
                facts.append(fact(f"{k}.name.jp", jp, prov, snapshot, url, original=jp))
            for attr, v in (("element", element), ("class", cls), ("rarity", rarity), ("tier.site", tier),
                            ("summary", o.get("summary")), ("tags", tags)):
                if v:
                    facts.append(fact(f"{k}.{attr}", v, prov, snapshot, url))
            if o.get("effects"):
                facts.append(fact(f"{k}.skills", o["effects"], prov, snapshot, url, notes="verbatim skill texts"))
            for st, v in stats.items():
                facts.append(fact(f"{k}.panel.{st}", v, prov, snapshot, url,
                                  notes="panel value; level/stars/build of the sample UNKNOWN"))
            cat["heroes"].append({
                "id": hid, "names": {"ru": title, "jp": jp}, "aliases": o.get("aliases", []), "element": element,
                "class": cls, "role": CLASSES.get(cls, "UNKNOWN"), "rarity": rarity, "tier_site": tier, "tags": tags,
                "summary": o.get("summary"), "skills_text": o.get("effects", []), "kit_status": "text_only",
                "abilities": [], "stats_mode": "panel",
                "base_stats": {s: stats.get(s, "UNKNOWN") for s in ("ATK", "HP", "DEF", "SPD")} |
                              {s: "UNKNOWN" for s in ("CRIT", "CRIT_DMG", "CTRL_RES")},
                "stats_note": "panel sample of unknown level/stars (site, mostly AppMedia-derived)",
                "provenance": p_cat})
        elif kind == "sigil-talent":
            tid = oid.split(":", 1)[1]
            mods = L.simple_mods(o.get("summary", ""))
            encoded["talent_" + ("encoded" if mods else "text")] += 1
            facts.append(fact(f"talent.{tid}.text", o.get("summary"), prov, snapshot, url, ru_name=title))
            cat["talents"].append({"id": tid, "name_ru": title, "system": "any", "effect_key": tid,
                                   "text": o.get("summary"), "mods": mods or [], "encoded": bool(mods), "provenance": p_cat})
        elif kind == "sigil":
            # "Талант из билда": a JP-named talent reference used in AppMedia builds
            jid = oid.split(":", 1)[1]
            facts.append(fact(f"talent_ref.{jid}.name", title, prov, snapshot, url, ru_name=title, original=jid,
                              notes="talent named in an AppMedia build; exact card not linked"))
            cat["talents"].append({"id": f"ref:{jid}", "name_ru": title, "name_jp": jid, "system": "any",
                                   "effect_key": f"ref:{jid}", "text": o.get("summary"), "mods": [], "encoded": False,
                                   "provenance": p_cat})
        elif kind == "limb":
            sid = oid.split(":", 1)[1]
            bonuses = {}
            for e in o.get("effects", []):
                m = re.match(r"(\d+)\s*части", e.get("label", ""))
                if m:
                    mods = L.simple_mods(e.get("text", ""))
                    encoded["limbset_" + ("encoded" if mods else "text")] += 1
                    bonuses[m.group(1)] = {"text": e.get("text"), "mods": mods or [], "encoded": bool(mods)}
                    facts.append(fact(f"limb_set.{sid}.bonus{m.group(1)}", e.get("text"), prov, snapshot, url, ru_name=title, original=jp))
            cat["limb_sets"].append({"id": sid, "name_ru": title, "name_jp": jp, "category": o.get("subtitle"),
                                     "bonuses": bonuses, "provenance": p_cat})
            for pos in range(4):
                cat["limbs"].append({"id": f"{sid}#{pos}", "set": sid, "position": pos, "mods": [],
                                     "provenance": dict(p_cat, note="positional piece derived from 4-slot rule; piece main stats UNKNOWN")})
        elif kind in ("pet", "rune", "princess-weapon", "relic", "charm-card", "accessory"):
            iid = oid.split(":", 1)[1]
            section = {"pet": "pets", "rune": "runes", "princess-weapon": "princess_weapon_parts", "relic": "relics",
                       "charm-card": "charm_cards", "accessory": "decorations"}[kind]
            texts = [e.get("text") for e in o.get("effects", []) if e.get("text")] or [o.get("summary")]
            stats = L.parse_stats(o)
            facts.append(fact(f"{kind}.{iid}.text", texts, prov, snapshot, url, ru_name=title, original=jp))
            if stats:
                facts.append(fact(f"{kind}.{iid}.stats", stats, prov, snapshot, url, notes=o.get("subtitle") or ""))
            entry = {"id": iid, "name_ru": title, "name_jp": jp, "subtitle": o.get("subtitle"), "text": texts,
                     "summary": o.get("summary"), "stats_sample": stats, "mods": [], "abilities": [], "encoded": False,
                     "provenance": p_cat}
            if kind == "pet":
                entry["rarity"] = (L.subtitle_parts(o.get("subtitle")) or [None])[0]
                entry["bond_mods"] = []
            cat[section].append(entry)
    FACTS.parent.mkdir(parents=True, exist_ok=True)
    with open(FACTS, "w", encoding="utf-8") as fh:
        for f in facts:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    cat["sigils"] = [{"id": "sigil_generic", "name_ru": "Сигил (основные статы UNKNOWN)", "mods": [],
                      "provenance": {"source": L.SITE + "/sigils", "confidence": "low", "ru_status": "unverified",
                                     "note": "sigil item stats are not published per item; placeholder so builds can be expressed"}}]
    CATALOG.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"pages": len(pages), "entities": Counter(o["kind"] for o in ents.values()), "facts": len(facts),
            "builds": len(builds), "encoded": dict(encoded),
            "confidence": Counter(f["confidence"] for f in facts), "ru_status": Counter(f["ru_status"] for f in facts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="2026-10-31")
    r = run(ap.parse_args().snapshot)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=dict))


if __name__ == "__main__":
    main()
