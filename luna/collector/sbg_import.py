"""surrounded-by-girls.online cache -> parsed characters, JP/GLOBAL facts, cross-reference with lunafantasy.ru.

python -m luna.collector.sbg_import [--snapshot 2026-10-31]
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import Counter
from pathlib import Path

from . import sbg

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "sbg"
OUT = ROOT / "data" / "kb" / "sbg"
FACTS = ROOT / "data" / "kb" / "facts"
LFRU_CAT = ROOT / "data" / "kb" / "catalog_RU.json"


def _fact(key, value, region, url, snapshot, conf="medium", notes="", original=None):
    return {"key": key, "value": value, "region": region, "balance_version": f"sbg@{snapshot}", "version_date": snapshot,
            "source": {"url": url, "title": "ヤバ少女攻略ペディア (surrounded-by-girls.online)", "accessed": snapshot, "kind": "web"},
            "confidence": conf, "ru_status": "unverified", "original_name": original, "notes": notes}


def norm(s):
    return re.sub(r"[\s・＆&]", "", str(s or ""))


def run(snapshot: str) -> dict:
    man = json.loads((CACHE / "manifest.json").read_text(encoding="utf-8"))
    chars = []
    for url, m in man.items():
        if m.get("status") != 200 or "/character/" not in url:
            continue
        c = sbg.parse_character(gzip.open(CACHE / m["file"], "rt", encoding="utf-8").read(), url)
        if c["is_character"]:
            chars.append(c)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "characters.json").write_text(json.dumps(chars, ensure_ascii=False, indent=0), encoding="utf-8")
    jp, gl = [], []
    for c in chars:
        k = f"hero.sbg:{c['slug']}"
        u = c["url"]
        jp.append(_fact(f"{k}.name.jp", c.get("name_jp"), "JP", u, snapshot, original=c.get("name_jp")))
        if c.get("name_jp_alt"):
            jp.append(_fact(f"{k}.name.jp_alt", c["name_jp_alt"], "JP", u, snapshot))
        if c.get("global_name"):
            gl.append(_fact(f"{k}.name.global", c["global_name"], "GLOBAL", u, snapshot, notes="quoted by JP guide: 海外版では…という表記"))
        if c.get("name_latin"):
            gl.append(_fact(f"{k}.name.latin", c["name_latin"], "GLOBAL", u, snapshot, conf="low", notes="latin name in the page intro"))
        for attr in ("element_jp", "class_jp", "trait_jp", "talents_recommended_jp"):
            if c["info"].get(attr):
                jp.append(_fact(f"{k}.{attr}", c["info"][attr], "JP", u, snapshot))
        if c.get("rank"):
            jp.append(_fact(f"{k}.tier.sbg", c["rank"], "JP", u, snapshot, conf="low", notes="site page rank; site says tier tables are more current"))
        if c.get("jp_release_date"):
            jp.append(_fact(f"{k}.jp_release", c["jp_release_date"], "JP", u, snapshot))
        if c.get("rarity_jp"):
            jp.append(_fact(f"{k}.rarity", c["rarity_jp"], "JP", u, snapshot))
        for st, v in c["stats"].items():
            jp.append(_fact(f"{k}.stat@lv{c['stats_level']}.{st}", v, "JP", u, snapshot,
                            notes=f"level {c['stats_level']}; stars/awakening/build of the sample not stated"))
        for i, s in enumerate(c["skills"]):
            if s["jp"]:
                jp.append(_fact(f"{k}.skill{i}.jp", {"name": s["name_jp"], "type": s["type"], "text": s["jp"]}, "JP", u, snapshot,
                                notes="国内版 (JP client) text"))
            if s["global"]:
                gl.append(_fact(f"{k}.skill{i}.global", {"name": s["name_jp"], "type": s["type"], "text": s["global"]}, "GLOBAL", u,
                                snapshot, notes="グローバル版 text as translated into Japanese by the guide"))
            if s["other"]:
                jp.append(_fact(f"{k}.skill{i}.text", {"name": s["name_jp"], "type": s["type"], "text": s["other"]}, "JP", u, snapshot,
                                conf="low", notes=s.get("version_note", "version not stated")))
        if c["awakening"]:
            jp.append(_fact(f"{k}.awakening", c["awakening"], "JP", u, snapshot, conf="low"))
        for bk, bv in c["build"].items():
            if bv:
                jp.append(_fact(f"{k}.build.{bk}", bv, "JP", u, snapshot, conf="low", notes="guide recommendation"))
    for name, rows in (("JP.sbg.jsonl", jp), ("GLOBAL.sbg.jsonl", gl)):
        with open(FACTS / name, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    # cross-reference with lunafantasy.ru by JP name / kanji / aliases
    lf = json.loads(LFRU_CAT.read_text(encoding="utf-8"))["heroes"] if LFRU_CAT.exists() else []
    idx = {}
    for h in lf:
        for n in [h["names"].get("jp")] + h.get("aliases", []):
            if n:
                idx.setdefault(norm(n), h["id"])
    xref, used = [], set()
    lf_by_slug = {h["id"]: h for h in lf}
    for c in chars:
        hit, how = None, None
        for n in (c.get("name_jp"), c.get("name_jp_alt")):
            if n and norm(n) in idx:
                hit, how = idx[norm(n)], "jp_name"
                break
        if not hit and c["slug"] in lf_by_slug:
            hit, how = c["slug"], "slug"
        if not hit:
            nj = norm(c.get("name_jp"))
            kata = re.compile(r"[\u30a0-\u30ff]")
            cands = [h["id"] for h in lf if h["names"].get("jp") and len(norm(h["names"]["jp"])) >= 2
                     and nj.endswith(norm(h["names"]["jp"]))
                     and not kata.search(nj[: -len(norm(h["names"]["jp"]))])]   # only an epithet prefix may differ
            if len(cands) == 1:
                hit, how = cands[0], "jp_substring"
        if hit:
            used.add(hit)
        xref.append({"sbg_slug": c["slug"], "name_jp": c.get("name_jp"), "name_jp_alt": c.get("name_jp_alt"),
                     "global_name": c.get("global_name"), "name_latin": c.get("name_latin"), "lfru_slug": hit,
                     "lfru_ru": next((h["names"]["ru"] for h in lf if h["id"] == hit), None),
                     "element_jp": c["info"].get("element_jp"), "class_jp": c["info"].get("class_jp"),
                     "jp_release": c.get("jp_release_date"), "rank_sbg": c.get("rank"), "stats_level": c.get("stats_level"),
                     "match": how})
    for h in lf:
        if h["id"] not in used:
            xref.append({"sbg_slug": None, "lfru_slug": h["id"], "lfru_ru": h["names"]["ru"], "name_jp": h["names"].get("jp"),
                         "match": None})
    (ROOT / "data" / "kb" / "crossref_heroes.json").write_text(json.dumps(xref, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"characters": len(chars), "facts_jp": len(jp), "facts_global": len(gl),
            "with_skills": sum(1 for c in chars if c["skills"]),
            "with_jp_and_global": sum(1 for c in chars if any(s["jp"] for s in c["skills"]) and any(s["global"] for s in c["skills"])),
            "matched_to_lfru": sum(1 for x in xref if x.get("sbg_slug") and x["lfru_slug"]),
            "sbg_only": sum(1 for x in xref if x.get("sbg_slug") and not x["lfru_slug"]),
            "lfru_only": sum(1 for x in xref if not x.get("sbg_slug")),
            "global_names": sum(1 for c in chars if c.get("global_name"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default="2026-10-31")
    print(json.dumps(run(ap.parse_args().snapshot), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
