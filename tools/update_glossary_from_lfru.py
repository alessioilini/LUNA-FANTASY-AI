"""Refresh hero entries in data/glossary.json from the lunafantasy.ru catalog (data/kb/catalog_RU.json).

* site slug becomes the canonical hero key (hero.<slug>);
* names from the brief (Hymelle, Klim, ...) are kept as aliases and mapped to a slug only when a site
  name/alias matches (case-insensitive) or the mapping is listed in BRIEF_MAP with its evidence;
* unmapped brief names stay as their own entries with ru_status "missing" (never guessed).
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G = ROOT / "data" / "glossary.json"
CAT = ROOT / "data" / "kb" / "catalog_RU.json"
JP_RX = re.compile(r"[぀-ヿ一-鿿]")

# brief name -> site slug, filled from evidence printed by this script (see --report)
BRIEF = ["Hymelle", "Lucifer", "Klim", "Seneren", "Vignette", "Kira", "Illusia", "Verafiel", "Chloe", "Seraphia", "Nyxara"]
BRIEF_RU = {"Verafiel": "Верафиэль", "Seraphia": "Монашка"}


def norm(s):
    return re.sub(r"[^a-zа-яё0-9぀-ヿ一-鿿]", "", str(s).lower().replace("ё", "е"))


def main():
    g = json.loads(G.read_text(encoding="utf-8"))
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    heroes = cat["heroes"]
    index = {}
    for h in heroes:
        for n in [h["id"], h["names"].get("ru"), h["names"].get("jp")] + h.get("aliases", []):
            if n:
                index.setdefault(norm(n), h["id"])
    mapping, report = {}, []
    for b in BRIEF:
        cands = [norm(b), norm(BRIEF_RU.get(b, ""))]
        hit = next((index[c] for c in cands if c and c in index), None)
        mapping[b] = hit
        report.append((b, hit))
    entries = [e for e in g["entries"] if e["category"] != "hero"]
    by_slug = {h["id"]: h for h in heroes}
    for h in heroes:
        aliases = [a for a in h.get("aliases", []) if not JP_RX.search(a)]
        brief = [b for b, s in mapping.items() if s == h["id"]]
        user_aliases = [BRIEF_RU[x] for x in brief if x in BRIEF_RU and BRIEF_RU[x] != h["names"].get("ru")]
        entries.append({"key": f"hero.{h['id']}", "category": "hero", "ru": h["names"].get("ru"), "en": brief[0] if brief else h["id"],
                        "jp": h["names"].get("jp"), "kr": None, "aliases_ru": aliases + brief + user_aliases,
                        "ru_status": "site_lunafantasy.ru", "jp_status": "site_alias" if h["names"].get("jp") else None,
                        "note": f"lunafantasy.ru slug {h['id']}"})
    for b, s in mapping.items():
        if s is None:
            entries.append({"key": f"hero.{b.lower()}", "category": "hero", "ru": BRIEF_RU.get(b), "en": b, "jp": None,
                            "kr": None, "aliases_ru": [], "ru_status": "missing", "jp_status": None,
                            "note": "name from the brief; not found on lunafantasy.ru by name/alias - mapping UNKNOWN"})
    g["entries"] = entries
    g["version"] = cat["balance_version"]
    G.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    for b, s in report:
        h = by_slug.get(s)
        print(f"{b:10s} -> {s or 'NOT FOUND':14s} {(h or {}).get('names', {}).get('ru', '')}")


if __name__ == "__main__":
    main()
