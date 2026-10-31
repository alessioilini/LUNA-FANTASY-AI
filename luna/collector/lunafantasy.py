"""lunafantasy.ru extractor.

The site is a Next.js app: every page embeds a React Server Components payload
(`self.__next_f.push([1, "..."])`) that contains the whole entity index as JSON objects
(`{"id": "<kind>:<slug>", "kind": ..., "title": ..., "effects": [...], "stats": [...],
"status": ..., "confidence": ..., "sourceRefs": [...]}`). Character pages additionally render the
recommended build; its order is exposed through `data-inspectable-id` attributes.

Provenance policy (see `site_provenance`):
  * region RU (the operator's primary RU source), balance_version = SNAPSHOT;
  * the site's own status/confidence strings are kept verbatim in `notes`;
  * in-client screenshots -> confidence high, ru_status verified_in_ru_client (as claimed by the site);
  * AppMedia-derived entries -> medium/low, ru_status unverified, primary source URL recorded.
"""
from __future__ import annotations

import gzip
import json
import re
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "lfru"
SITE = "https://lunafantasy.ru"
KINDS = {"character", "sigil-talent", "sigil", "limb", "pet", "rune", "princess-weapon", "relic", "charm-card",
         "accessory", "code", "battle", "guide", "build", "team", "source", "roles"}


# ---------------------------------------------------------------------------------- payload
def rsc_text(html: str) -> str:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, flags=re.S)
    out = []
    for c in chunks:
        try:
            out.append(json.loads('"' + c + '"'))
        except json.JSONDecodeError:
            continue
    return "".join(out)


def _object_at(txt: str, start: int) -> str | None:
    depth, ins, esc = 0, False, False
    for j in range(start, len(txt)):
        c = txt[j]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
        elif c == '"':
            ins = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return txt[start:j + 1]
    return None


def entities(txt: str) -> list[dict]:
    """All JSON objects that look like `{"id":"<kind>:...","kind":"<kind>",...}`."""
    out = []
    for m in re.finditer(r'\{"id":"([a-z\-]+):[^"]*","kind":"([a-z\-]+)"', txt):
        s = _object_at(txt, m.start())
        if not s:
            continue
        try:
            o = json.loads(s)
        except json.JSONDecodeError:
            continue
        out.append(o)
    return out


def merge_entities(objs: list[dict]) -> "OrderedDict[str, dict]":
    """Same id may appear on many pages; keep the richest version (most keys / longest text)."""
    best: "OrderedDict[str, dict]" = OrderedDict()
    for o in objs:
        oid = o["id"]
        if oid not in best or len(json.dumps(o, ensure_ascii=False)) > len(json.dumps(best[oid], ensure_ascii=False)):
            best[oid] = o
    return best


# ---------------------------------------------------------------------------------- build parsing
def character_build(html: str) -> dict:
    """Ordered build from a character page: sigils (2x2), personal talents (2), limbs, pets, accessories."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    build = {"sigils": [], "personal_talents": [], "limbs": [], "pets": [], "accessories": [], "notes": []}
    seen_section = set()
    for el in soup.select("[data-inspectable-id]"):
        iid = el.get("data-inspectable-id")
        kind = iid.split(":", 1)[0]
        text = el.get_text(" ", strip=True)
        if "игровой термин" in text:
            continue                     # glossary repeat block
        heading = ""
        for anc in el.parents:
            h = anc.find(["h4", "h3"], recursive=False) if hasattr(anc, "find") else None
            if h:
                heading = h.get_text(" ", strip=True)
                break
        if kind in ("sigil-talent", "sigil"):
            rank = text.split(" ", 1)[0]
            if "Таланты персонажа" in heading:
                build["personal_talents"].append({"id": iid, "slot_note": rank})
            else:
                key = heading or "Сигил"
                build["sigils"].append({"id": iid, "rank": rank, "group": key})
        elif kind == "limb":
            build["limbs"].append({"id": iid, "label": text[:80]})
        elif kind == "pet":
            if iid not in [p["id"] for p in build["pets"]]:
                build["pets"].append({"id": iid})
        elif kind == "accessory":
            if iid not in build["accessories"]:
                build["accessories"].append(iid)
        seen_section.add(kind)
    # sigils: consecutive pairs = (sigil 1: t1, t2), (sigil 2: t1, t2)
    s = build["sigils"]
    build["sigil_pairs"] = [[x["id"] for x in s[i:i + 2]] for i in range(0, min(len(s), 4), 2)]
    return build


def page_text(html: str) -> list[str]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    main = soup.find("main") or soup.body or soup
    return [l.strip() for l in main.get_text("\n").splitlines() if l.strip()]


# ---------------------------------------------------------------------------------- provenance
def site_provenance(o: dict) -> dict:
    status = str(o.get("status") or "")
    conf = str(o.get("confidence") or "")
    refs = o.get("sourceRefs") or []
    paths = [r.get("path", "") for r in refs if r.get("path")]
    urls = [r.get("url", "") for r in refs if r.get("url")]
    media_src = (o.get("media") or {}).get("sourcePath") or ""
    client = (any(p.startswith("Скрины из игры") for p in paths + [media_src])
              or "ru_client" in status or "из игрового клиента" in status or "player проверено" in status)
    appmedia = any("appmedia.jp" in u for u in urls) or "appmedia" in conf.lower() or "appmedia" in status.lower()
    if client:
        confidence, ru_status = "high", "verified_in_ru_client"
    elif status in ("проверено вручную",) or conf in ("проверено вручную",) or "crosscheck" in conf or "checked" in conf:
        confidence, ru_status = "medium", "unverified"
    elif appmedia:
        confidence, ru_status = "low", "unverified"
    else:
        confidence, ru_status = "low", "unverified"
    return {"confidence": confidence, "ru_status": ru_status, "site_status": status, "site_confidence": conf,
            "primary_sources": urls + paths, "derived_from_jp_appmedia": appmedia and not client}


NUM = re.compile(r"[\d   ]+")


def to_number(s: str):
    s = str(s).replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


STAT_LABELS = {"ATK": "ATK", "АТК": "ATK", "OЗ": "HP", "ОЗ": "HP", "HP": "HP", "DEF": "DEF", "ЗАЩ": "DEF",
               "SPD": "SPD", "СКР": "SPD"}


def parse_stats(o: dict) -> dict:
    out = {}
    for s in o.get("stats") or []:
        k = STAT_LABELS.get(str(s.get("label", "")).strip())
        v = to_number(s.get("value", ""))
        if k and v is not None:
            out[k] = v
    return out


# Conservative stat-only effect parser. Anything not matching EXACTLY stays text.
SIMPLE = [
    (re.compile(r"^(?:Увеличивает )?СКР (?:на )?\+?(\d+(?:[.,]\d+)?)%\s*\+\s*(\d+)\.?$", re.I), lambda m: [
        {"stat": "SPD", "value": float(m.group(1).replace(",", ".")) / 100, "mode": "pct"},
        {"stat": "SPD", "value": float(m.group(2)), "mode": "flat"}]),
    (re.compile(r"^Увеличивает шанс крита на (\d+(?:[.,]\d+)?)%\.?$", re.I),
     lambda m: [{"stat": "CRIT", "value": float(m.group(1).replace(",", ".")) / 100}]),
    (re.compile(r"^Финальный урон игнорирует (\d+(?:[.,]\d+)?)% защиты цели\.?$", re.I),
     lambda m: [{"stat": "IGNORE_DEF", "value": float(m.group(1).replace(",", ".")) / 100}]),
    (re.compile(r"^(АТК|ОЗ|ЗАЩ|СКР|Лечение) \+(\d+(?:[.,]\d+)?)%\.?$", re.I),
     lambda m: [{"stat": {"атк": "ATK", "оз": "HP", "защ": "DEF", "скр": "SPD", "лечение": "HEAL_BONUS"}[m.group(1).lower()],
                 "value": float(m.group(2).replace(",", ".")) / 100,
                 "mode": "flat" if m.group(1).lower() == "лечение" else "pct"}]),
]


def simple_mods(text: str) -> list[dict] | None:
    t = (text or "").strip()
    for rx, fn in SIMPLE:
        m = rx.match(t)
        if m:
            return fn(m)
    return None


def subtitle_parts(sub: str) -> list[str]:
    return [p.strip() for p in str(sub or "").split("·") if p.strip()]
