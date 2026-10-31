"""surrounded-by-girls.online (ヤバ少女攻略ペディア) - JP guide, the most complete character base.

Character pages are WordPress articles. Inside `.article-body` the hierarchy is
  h2 section > h3 block (ステータス / アクティブスキル / パッシブスキル / 覚醒効果 / 推奨ビルド ...)
  > h4 "スキル　<name>" > h5 国内版 (JP client text) | h5 グローバル版 (global/overseas client text)
JP-domestic texts get region JP; global-version texts get region GLOBAL - they are never merged.
"""
from __future__ import annotations

import re

SITE = "https://surrounded-by-girls.online"
STAT_JP = {"ATK": "ATK", "攻撃力": "ATK", "体力": "HP", "HP": "HP", "防御力": "DEF", "DEF": "DEF", "スピード": "SPD", "SPD": "SPD"}
INFO_KEYS = {"評価ランク": "rank_site", "属性": "element_jp", "職業": "class_jp", "特性": "trait_jp",
             "推奨タレント刻印": "talents_recommended_jp", "日本版実装日": "jp_release"}
ELEMENT_RU = {"光属性": "Свет", "闇属性": "Тьма", "火属性": "Огонь", "水属性": "Вода", "風属性": "Ветер"}
CLASS_RU = {"サポーター": "Поддержка", "ガーディアン": "Страж", "魔法使い": "Маг", "ウォーリア": "Воин", "戦士": "Воин"}


def _clean(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def sections(html: str) -> list[dict]:
    """Flatten the article into ordered blocks with their heading path."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(".article-body") or soup.find("article") or soup
    for t in body(["script", "style", "noscript", "svg"]):
        t.decompose()
    for ad in body.select(".surro-, [class*='surro-entity'], .keni-related-title"):
        ad.decompose()
    path = {"h2": "", "h3": "", "h4": "", "h5": ""}
    blocks = []
    cur = None
    for el in body.find_all(["h2", "h3", "h4", "h5", "p", "table", "ul", "ol", "div"], recursive=True):
        if el.name in path:
            lvl = el.name
            path[lvl] = _clean(el.get_text(" "))
            for deeper in ("h3", "h4", "h5"):
                if deeper > lvl:
                    path[deeper] = ""
            cur = {"path": dict(path), "text": [], "tables": []}
            blocks.append(cur)
            continue
        if el.name == "div" and el.find(["p", "table", "h2", "h3", "h4", "h5", "div"]):
            continue                       # container: its children are visited separately
        if cur is None:
            cur = {"path": dict(path), "text": [], "tables": []}
            blocks.append(cur)
        if el.name == "table":
            rows = [[_clean(c.get_text(" ")) for c in tr.find_all(["th", "td"])] for tr in el.find_all("tr")]
            cur["tables"].append(rows)
        elif el.find_parent("table") is None and el.find_parent(["ul", "ol"]) is None or el.name in ("ul", "ol"):
            t = _clean(el.get_text(" "))
            if t:
                cur["text"].append(t)
    return blocks


def parse_character(html: str, url: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    title = _clean((soup.find("h1") or soup.title or soup).get_text(" "))
    out = {"url": url, "slug": url.rstrip("/").split("/")[-1], "title": title, "info": {}, "stats": {}, "stats_level": None,
           "skills": [], "awakening": [], "build": {}, "overseas_eval": [], "dates": {}}
    m = re.search(r"更新日：\s*(\d{4})年(\d{1,2})月(\d{1,2})日", soup.get_text(" "))
    if m:
        out["dates"]["updated"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.search(r"公開日：\s*(\d{4})年(\d{1,2})月(\d{1,2})日", soup.get_text(" "))
    if m:
        out["dates"]["published"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # name line: 「花の芸者・綺羅 キラ Kira」（限定GR）
    m = re.search(r"「([^」]+)」\s*（([^）]+)）", soup.get_text(" "))
    if m:
        out["name_line"] = _clean(m.group(1))
        out["rarity_jp"] = _clean(m.group(2))
        latin = re.findall(r"[A-Za-z][A-Za-z .'\-]+", m.group(1))
        out["name_latin"] = _clean(latin[-1]) if latin else None
    tm = re.match(r"【ヤバ少女】\s*([^\s（(は]+)(?:[（(]([^）)]+)[）)])?", title)
    if tm:
        out["name_jp"] = tm.group(1)
        out["name_jp_alt"] = tm.group(2)
    for b in sections(html):
        p = b["path"]
        for tbl in b["tables"]:
            for row in tbl:
                if len(row) >= 2 and row[0] in INFO_KEYS and not out["info"].get(INFO_KEYS[row[0]]):
                    out["info"][INFO_KEYS[row[0]]] = row[1]
                if len(row) >= 2 and row[0] in STAT_JP and "ステータス" in p["h3"]:
                    v = re.sub(r"[^\d.]", "", row[1])
                    if v:
                        out["stats"][STAT_JP[row[0]]] = float(v)
        if "ステータス" in p["h3"]:
            lm = re.search(r"レベル\s*(\d+)", p["h3"])
            out["stats_level"] = int(lm.group(1)) if lm else out["stats_level"]
        if p["h4"].startswith("スキル") and ("アクティブ" in p["h3"] or "パッシブ" in p["h3"]):
            name = _clean(p["h4"].replace("スキル", "", 1))
            sk = next((s for s in out["skills"] if s["name_jp"] == name), None)
            if sk is None:
                sk = {"name_jp": name, "type": "active" if "アクティブ" in p["h3"] else "passive", "jp": [], "global": [], "other": []}
                out["skills"].append(sk)
            bucket = "jp" if p["h5"].startswith("国内版") else "global" if p["h5"].startswith("グローバル版") else "other"
            sk[bucket] += b["text"] + [" | ".join(r) for t in b["tables"] for r in t]
        elif "覚醒" in p["h3"]:
            out["awakening"] += b["text"] + [" | ".join(r) for t in b["tables"] for r in t]
        elif "推奨ビルド" in p["h2"] or "おすすめ" in p["h3"]:
            key = p["h3"] or p["h2"]
            out["build"].setdefault(key, []).extend(b["text"])
        elif "海外" in p["h2"] and "評価" in p["h2"]:
            out["overseas_eval"] += b["text"]
    info = out["info"]
    out["element_ru"] = ELEMENT_RU.get(info.get("element_jp", ""))
    out["class_ru"] = CLASS_RU.get(info.get("class_jp", ""))
    rel = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", info.get("jp_release", "") or "")
    out["jp_release_date"] = f"{rel.group(1)}-{int(rel.group(2)):02d}-{int(rel.group(3)):02d}" if rel else None
    out["not_in_jp_yet"] = "未実装" in (info.get("jp_release") or "") or "未実装" in title
    rk = re.search(r"(SSS|SS|S|A|B|C|D)ランク", info.get("rank_site", "") or "")
    out["rank"] = rk.group(1) if rk else None
    return out
