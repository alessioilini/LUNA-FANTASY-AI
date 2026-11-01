"""AppMedia (appmedia.jp/yabasyoujyo) - JP guide pages with structured build recommendations.

Every heroine page has the same blocks (checked on 2026-11-01):
  h2 "<name>のおすすめ刻印・タレント" -> table: "おすすめ刻印" rows (main picks) then "候補" rows (candidates)
  h3 "おすすめ戒魔"                    -> table: limb set | ★★★★☆ rating;  next table: sub-stats by slot (1・3 / 2・4)
  h2 "<name>のおすすめペット"           -> table of pet names
  h2 "<name>の評価とステータス"          -> "<name>の評価 | SS"
plus schema.org dateModified, which is stored as the source date of every recommendation.

Only structured facts are stored (names, order, ★ rating, dates) - the guide's prose is not copied.
Region of every value: JP (domestic JP client). Names stay in Japanese; the mapping to RU names lives in
luna/planbook/terms.py with an explicit status (lfru_alias / hypothesis).
robots.txt of appmedia.jp allows these pages; requests are rate-limited and cached under data/cache/appmedia.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "appmedia"
OUT = ROOT / "data" / "kb" / "appmedia" / "builds.json"
UA = "Mozilla/5.0 (luna-fantasy-ai research; personal, non-commercial; respects robots.txt)"
STARS = re.compile(r"(★+)(☆*)")


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def cache_path(url: str) -> Path:
    return CACHE / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".html.gz")


def fetch(url: str, delay: float = 2.0, refresh: bool = False) -> str | None:
    import requests
    from urllib import robotparser
    p = cache_path(url)
    if p.exists() and not refresh:
        return gzip.decompress(p.read_bytes()).decode("utf-8", "replace")
    rp = robotparser.RobotFileParser()
    r = requests.get("https://appmedia.jp/robots.txt", timeout=20, headers={"User-Agent": UA})
    rp.parse(r.text.splitlines() if r.ok else [])
    if not rp.can_fetch(UA, url):
        return None
    time.sleep(delay)
    resp = requests.get(url, timeout=30, headers={"User-Agent": UA})
    if not resp.ok:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(resp.text.encode("utf-8")))
    meta = CACHE / "manifest.json"
    m = json.loads(meta.read_text()) if meta.exists() else {}
    m[url] = {"file": p.name, "fetched": dt.datetime.now().isoformat(timespec="seconds")}
    meta.write_text(json.dumps(m, ensure_ascii=False, indent=1))
    return resp.text


def _rows_after(h, stop=("h2",)):
    sib = h.find_next_sibling()
    while sib is not None and sib.name not in stop:
        yield sib
        sib = sib.find_next_sibling()


def _name_cell(td) -> str:
    d = td.find("div")
    if d and _clean(d.get_text()):
        return _clean(d.get_text())
    a = td.find("a")
    t = _clean((a or td).get_text())
    if not t:
        img = td.find("img")
        t = re.sub(r"^ヤバ少女_|_アイコン$", "", img.get("alt", "")) if img else ""
    return t


def parse(html: str, url: str) -> dict:
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "lxml")
    title = _clean(s.title.get_text()) if s.title else ""
    mod = re.search(r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
    pub = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)
    name = re.sub(r"^【ヤバ少女】|の評価.*$", "", title).strip()
    out = {"url": url, "title": title, "name_jp": name, "date_modified": mod.group(1) if mod else None,
           "date_published": pub.group(1) if pub else None, "tier": None,
           "talents": [], "limbs": [], "substats": {}, "pets": []}
    for h in s.find_all(["h2", "h3"]):
        t = _clean(h.get_text())
        if t.endswith("の評価とステータス"):
            for el in _rows_after(h):
                m = re.search(r"の評価[\s|]*(SSS|SS|S|A|B|C|D)(?![A-Za-z])", _clean(el.get_text(" | ")))
                if m:
                    out["tier"] = m.group(1)
                    break
        elif "おすすめ刻印" in t and h.name == "h2":
            tbl = next((e for e in _rows_after(h) if e.name == "table"), None)
            group, pos = "main", {"main": 0, "candidate": 0}
            for tr in (tbl.find_all("tr") if tbl else []):
                th = tr.find("th")
                if th:
                    group = "candidate" if "候補" in th.get_text() else "main"
                    continue
                tds = tr.find_all("td")
                if not tds:
                    continue
                nm = _name_cell(tds[0])
                if not nm:
                    continue
                pos[group] += 1
                out["talents"].append({"name_jp": nm, "group": group, "pos": pos[group]})
        elif t == "おすすめ戒魔":
            tables = [e for e in _rows_after(h, stop=("h2", "h3")) if e.name == "table"]
            if tables:
                pos = 0
                for tr in tables[0].find_all("tr"):
                    tds = tr.find_all("td")
                    if len(tds) < 2:
                        continue
                    pos += 1
                    m = STARS.search(tds[1].get_text())
                    out["limbs"].append({"name_jp": _name_cell(tds[0]), "pos": pos,
                                         "stars": len(m.group(1)) if m else None,
                                         "stars_max": len(m.group(1)) + len(m.group(2)) if m else None})
            if len(tables) > 1:
                cur = None
                for tr in tables[1].find_all("tr"):
                    th, td = tr.find("th"), tr.find("td")
                    if th:
                        cur = _clean(th.get_text())
                    elif td and cur:
                        out["substats"][cur] = [x.strip() for x in td.get_text().split("/") if x.strip()]
        elif "おすすめペット" in t and h.name == "h2":
            tbl = next((e for e in _rows_after(h) if e.name == "table"), None)
            pos = 0
            for td in (tbl.find_all("td") if tbl else []):
                nm = _name_cell(td)
                if nm and nm.strip("-－—–ー "):
                    pos += 1
                    out["pets"].append({"name_jp": nm, "pos": pos})
    return out


def hero_urls() -> dict[str, str]:
    """lunafantasy.ru character entities point to their AppMedia source pages ('Билд'/'Источник')."""
    e = json.loads((ROOT / "data/kb/lfru/entities.json").read_text(encoding="utf-8"))
    urls = {}
    for x in e:
        if x["kind"] != "character":
            continue
        h = x.get("href") or ""
        slug = h.rstrip("/").split("/")[-1] if h.startswith("/characters/") else x["id"].split("_", 1)[1]
        refs = [r.get("url", "") for r in x.get("sourceRefs", []) if "appmedia.jp/yabasyoujyo/" in r.get("url", "")]
        build = [r.get("url") for r in x.get("sourceRefs", []) if r.get("label") == "Билд" and "appmedia" in r.get("url", "")]
        if build or refs:
            urls[slug] = (build or refs)[0]
    return urls


def collect(limit: int | None = None, refresh: bool = False, delay: float = 2.0) -> dict:
    res = {"snapshot": dt.date.today().isoformat(), "source": "https://appmedia.jp/yabasyoujyo", "region": "JP",
           "heroes": {}, "errors": []}
    for i, (slug, url) in enumerate(sorted(hero_urls().items())):
        if limit and i >= limit:
            break
        html = fetch(url, delay=delay, refresh=refresh)
        if not html:
            res["errors"].append({"slug": slug, "url": url, "error": "fetch failed or disallowed"})
            continue
        try:
            p = parse(html, url)
        except Exception as ex:  # page layout drift: keep going, record it
            res["errors"].append({"slug": slug, "url": url, "error": repr(ex)[:200]})
            continue
        p["lfru_slug"] = slug
        res["heroes"][slug] = p
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Collect AppMedia (JP) build recommendations")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--delay", type=float, default=2.0)
    a = ap.parse_args()
    r = collect(a.limit, a.refresh, a.delay)
    hs = r["heroes"].values()
    print(json.dumps({"heroes": len(r["heroes"]), "errors": len(r["errors"]),
                      "with_talents": sum(1 for h in hs if h["talents"]), "with_limbs": sum(1 for h in hs if h["limbs"]),
                      "with_pets": sum(1 for h in hs if h["pets"]), "with_tier": sum(1 for h in hs if h["tier"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
