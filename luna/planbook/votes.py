"""Collect build 'votes' from every source into one long table.

A vote = one source recommending one candidate for one heroine (or for the team) in one category.
Weights are NOT applied here: the workbook computes them with formulas from the sheet «Веса», and
luna.planbook.score reproduces the same formulas in Python (tested to match after recalculation).

Categories:
  sigil, personal          - sigil talents (2 sigils x 2) and personal talents (2) - never merged
  limb                     - limb ('демон') set worn 4/4
  substat_13, substat_24   - limb sub-stats for slots 1/3 and 2/4
  pet, accessory, card     - per heroine
  rune, pw                 - team level (hero = "__team__")
  tier                     - heroine strength (hero level; candidate = the heroine herself)
Groups (how strongly the source recommends): main, candidate, list, avoid (negative vote).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from . import terms as T

ROOT = Path(__file__).resolve().parents[2]
TEAM = "__team__"

SOURCES = {
    # id: (name, region, url, default weight, note)
    "appmedia": ("AppMedia — やばい！少女に囲まれた！攻略", "JP", "https://appmedia.jp/yabasyoujyo", 1.00,
                 "японский гайд:刻印/戒魔/ペット по каждой героине, оценка SSS…C; дата — dateModified страницы"),
    "sbg": ("surrounded-by-girls.online (ヤバ少女攻略ペディア)", "JP", "https://surrounded-by-girls.online", 1.00,
            "японская база: ◎/◯/☓ рекомендации и тир; дата — 'updated' страницы"),
    "lfru": ("lunafantasy.ru — билды героинь", "RU", "https://lunafantasy.ru", 0.70,
             "RU-сайт: билды в основном переведены с AppMedia + заметки RU-сообщества; дата снимка 2026-10-31"),
    "chatgpt": ("Планы ChatGPT (XLSX оператора, 09.2026)", "RU", "data/kb/imports/chatgpt", 0.30,
                "исторические рекомендации под конкретные пачки; низкая достоверность по правилам импорта"),
    "lfru_grade": ("Класс/редкость предмета на lunafantasy.ru", "RU", "https://lunafantasy.ru", 0.25,
                   "слабый априорный голос: SS/S-класс руны и оружия, редкость карт и питомцев"),
    "class_fit": ("Совпадение класса героини и класса карты", "derived", "data/kb/lfru/entities.json", 0.30,
                  "карта прелестей подписана классами (Маг/Воин/Саппорт/Страж)"),
}


def _v(hero, cat, cand, name_ru, src, date, group="main", pos=1, rating=None, status="lfru_alias", note="",
       url="", name_orig=""):
    return {"hero": hero, "cat": cat, "cand": cand, "name_ru": name_ru, "name_orig": name_orig or name_ru,
            "source": src, "date": date, "group": group, "pos": int(pos), "rating": rating,
            "map_status": status, "note": note, "url": url}


# --------------------------------------------------------------------------------------- AppMedia
def from_appmedia(path: Path | None = None) -> list[dict]:
    p = path or ROOT / "data/kb/appmedia/builds.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for slug, h in d["heroes"].items():
        hero = slug
        date = h.get("date_modified") or h.get("date_published") or d["snapshot"]
        url = h["url"]
        if h.get("tier"):
            out.append(_v(hero, "tier", hero, h["tier"], "appmedia", date, rating=h["tier"], url=url, name_orig=h["tier"]))
        for t in h["talents"]:
            ru, st, note = T.talent_from_jp(t["name_jp"])
            out.append(_v(hero, "sigil", ru, ru, "appmedia", date, t["group"], t["pos"], None, st, note, url, t["name_jp"]))
        for lb in h["limbs"]:
            suf, ru, st, note = T.limb_from_jp(lb["name_jp"])
            r = lb["stars"] / lb["stars_max"] if lb.get("stars") and lb.get("stars_max") else None
            out.append(_v(hero, "limb", suf, ru, "appmedia", date, "main", lb["pos"], r, st, note, url, lb["name_jp"]))
        for slot, stats in h.get("substats", {}).items():
            cat = "substat_13" if "1" in slot and "3" in slot else "substat_24" if "2" in slot else None
            if not cat:
                continue
            for i, s in enumerate(stats, 1):
                ru, st = T.SUBSTAT_JP.get(s.strip(), (s.strip(), "unmapped"))
                out.append(_v(hero, cat, ru, ru, "appmedia", date, "list", i, None, st, "", url, s.strip()))
        for pt in h["pets"]:
            suf, ru, st, note = T.entity_from_name("pet", pt["name_jp"], T.PET_JP)
            out.append(_v(hero, "pet", suf, ru, "appmedia", date, "list", pt["pos"], None, st, note, url, pt["name_jp"]))
    return out


# --------------------------------------------------------------------------------------- SBG
_SPLIT = re.compile(r"[、，,／/・\s]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _SPLIT.split(re.sub(r"[（(][^）)]*[）)]", " ", text)) if t]


def _sbg_talent_line(line: str) -> list[tuple[str, str, int]]:
    """-> [(jp_term, group, tier_pos)]; understands ◎/◯/☓ blocks and 'A、B ＞ C、D' priority chains."""
    res = []
    marks = re.findall(r"([◎◯○☓×✕])\s*(?:推奨|非推奨)?\s*[：:]\s*([^◎◯○☓×✕]*)", line)
    if marks:
        for m, body in marks:
            grp = "main" if m == "◎" else "avoid" if m in "☓×✕" else "candidate"
            for tok in _tokens(body):
                res.append((tok, grp, 1))
        return res
    body = line.split("：", 1)[1] if "：" in line else line.split(":", 1)[1] if ":" in line else line
    tiers = re.split(r"[＞>]", body)
    if len(tiers) == 1 and "推奨" not in line and "構成" not in line:
        return []
    for i, tier in enumerate(tiers, 1):
        for tok in _tokens(tier):
            res.append((tok, "main" if i == 1 else "candidate", i))
    return res


def from_sbg(path: Path | None = None) -> list[dict]:
    p = path or ROOT / "data/kb/sbg/characters.json"
    xr = {r["sbg_slug"]: r for r in json.loads((ROOT / "data/kb/crossref_heroes.json").read_text(encoding="utf-8"))}
    out = []
    for c in json.loads(p.read_text(encoding="utf-8")):
        if not c.get("is_character", True):
            continue
        r = xr.get(c["slug"], {})
        h = T.hero_from_name(r.get("lfru_ru") or "") if r.get("lfru_ru") else None
        hero = h[0] if h else (T.hero_from_name(c["slug"]) or (c["slug"], ""))[0]
        date = (c.get("dates") or {}).get("updated") or (c.get("dates") or {}).get("published") or "2026-10-31"
        url = c["url"]
        if c.get("rank"):
            out.append(_v(hero, "tier", hero, c["rank"], "sbg", date, rating=c["rank"], url=url, name_orig=c["rank"]))
        b = c.get("build") or {}
        seen = set()
        for line in b.get("おすすめ刻印＆ルーン考察", []):
            for tok, grp, tpos in _sbg_talent_line(line):
                if tok not in T.TALENT_JP and re.sub(r"[（(].*", "", tok) not in T.TALENT_JP:
                    continue                                     # prose, not a talent name
                ru, st, note = T.talent_from_jp(tok)
                if (ru, grp) in seen:
                    continue
                seen.add((ru, grp))
                out.append(_v(hero, "sigil", ru, ru, "sbg", date, grp, tpos, None, st, note, url, tok))
        limb_lines = b.get("おすすめ戒魔", [])[:1]
        pos = 0
        for line in limb_lines:
            for tok in _tokens(line):
                suf, ru, st, note = T.limb_from_jp(tok)
                if st == "unmapped":
                    continue
                pos += 1
                out.append(_v(hero, "limb", suf, ru, "sbg", date, "list", pos, None, st, note, url, tok))
        pos = 0
        for line in b.get("おすすめペット", [])[:1]:
            for tok in _tokens(line):
                suf, ru, st, note = T.entity_from_name("pet", tok, T.PET_JP)
                if st == "unmapped":
                    continue
                pos += 1
                out.append(_v(hero, "pet", suf, ru, "sbg", date, "list", pos, None, st, note, url, tok))
        pos = 0
        for line in b.get("おすすめアクセサリー", []):
            if line.count("、") < 2:
                continue
            for tok in _tokens(line):
                suf, ru, st, note = T.entity_from_name("accessory", tok, T.ACCESSORY_JP)
                if st == "unmapped":
                    continue
                pos += 1
                out.append(_v(hero, "accessory", suf, ru, "sbg", date, "list", pos, None, st, note, url, tok))
    return out


# --------------------------------------------------------------------------------------- lunafantasy.ru
_RATING = re.compile(r"(\d)\s*/\s*5")


def from_lfru(path: Path | None = None, date: str = "2026-10-31") -> list[dict]:
    p = path or ROOT / "data/kb/lfru/builds.json"
    out = []
    builds = json.loads(p.read_text(encoding="utf-8"))
    acc_lists = {tuple(v["accessories"]) for v in builds.values() if v["accessories"]}
    generic_acc = len(acc_lists) == 1          # the same list for every heroine is a catalogue, not a recommendation
    for hero, b in builds.items():
        url = f"https://lunafantasy.ru/characters/{hero}"
        for s in b["sigils"]:
            ru, st, note = T.talent_from_lfru_id(s["id"])
            out.append(_v(hero, "sigil", ru, ru, "lfru", date, "main", 1, None, st, f"{s.get('group', '')}; {note}".strip("; "),
                          url, s["id"].split(":", 1)[1]))
        for s in b["personal_talents"]:
            ru, st, note = T.talent_from_lfru_id(s["id"])
            out.append(_v(hero, "personal", ru, ru, "lfru", date, "main", 1, None, st, note, url, s["id"].split(":", 1)[1]))
        for i, lb in enumerate(b["limbs"], 1):
            suf = lb["id"].split(":", 1)[1]
            ru = next((x["title"] for x in T.entities() if x["id"] == lb["id"]), suf)
            lab = lb.get("label", "")
            m = _RATING.search(lab)
            r = int(m.group(1)) / 5 if m else (1.0 if "БИС" in lab else None)
            out.append(_v(hero, "limb", suf, ru, "lfru", date, "main", i, r, "lfru_alias", lab[:80], url, ru))
        for i, pt in enumerate(b["pets"], 1):
            suf = pt["id"].split(":", 1)[1]
            ru = next((x["title"] for x in T.entities() if x["id"] == pt["id"]), suf)
            out.append(_v(hero, "pet", suf, ru, "lfru", date, "list", i, None, "lfru_alias", "", url, ru))
        if not generic_acc:
            for i, a in enumerate(b["accessories"], 1):
                suf = a.split(":", 1)[1]
                ru = next((x["title"] for x in T.entities() if x["id"] == a), suf)
                out.append(_v(hero, "accessory", suf, ru, "lfru", date, "list", i, None, "lfru_alias", "", url, ru))
    return out


# --------------------------------------------------------------------------------------- ChatGPT plans
def _header_index(rows: list[list], first: str) -> int | None:
    return next((i for i, r in enumerate(rows) if r and str(r[0]).strip() == first), None)


def from_chatgpt(path: Path | None = None) -> list[dict]:
    p = path or ROOT / "data/kb/imports/chatgpt/xlsx_dump.json"
    if not p.exists():
        return []
    out, seen = [], set()
    for f in json.loads(p.read_text(encoding="utf-8")):
        date = f.get("plan_date") or "2026-09-01"
        url = f"data/kb/imports/chatgpt/xlsx/{f['file']}"
        for sname, rows in f["sheets"].items():
            h = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()
            if (sname, h) in seen or not rows:
                continue                          # identical sheet already counted from another file
            seen.add((sname, h))
            note = f"{f['file'][:8]} / {sname}"
            if sname.startswith("01_Сигилы"):
                hi = _header_index(rows, "Дева")
                for r in rows[hi + 1:] if hi is not None else []:
                    hh = T.hero_from_name(str(r[0]))
                    if not hh or len(r) < 8:
                        if not hh and r and r[0] and str(r[0]).startswith("Примечание"):
                            break
                        continue
                    for j, cat in ((2, "sigil"), (3, "sigil"), (4, "sigil"), (5, "sigil"), (6, "personal"), (7, "personal")):
                        if str(r[j]).strip():
                            ru, st, nt = T.talent_from_ru(str(r[j]))
                            out.append(_v(hh[0], cat, ru, ru, "chatgpt", date, "main", 1, None, st, f"{note}; {nt}".strip("; "),
                                          url, str(r[j]).strip()))
            elif sname.startswith("02_Лимбы"):
                hi = _header_index(rows, "Герой")
                done = set()
                for r in rows[hi + 1:] if hi is not None else []:
                    hh = T.hero_from_name(str(r[0]))
                    if not hh or len(r) < 12:
                        continue
                    if hh[0] not in done:
                        suf, ru, st, nt = T.entity_from_name("limb", str(r[2]))
                        out.append(_v(hh[0], "limb", suf, ru, "chatgpt", date, "main", 1, None, st, note, url, str(r[2])))
                        done.add(hh[0])
                    slot = str(r[4]).strip()
                    if slot in ("1", "2"):                         # slots 3/4 repeat 1/2
                        cat = "substat_13" if slot == "1" else "substat_24"
                        for k in range(3):
                            for grp, base in (("main", 6), ("candidate", 9)):
                                val = str(r[base + k]).strip() if len(r) > base + k else ""
                                stat = re.sub(r"\s*[+\-]?\d[\d,.]*\s*%?\s*$", "", val).strip()
                                if stat:
                                    out.append(_v(hh[0], cat, stat, stat, "chatgpt", date, grp, k + 1, None, "meaning",
                                                  note, url, val))
            elif sname.startswith("03_Аксессуары"):
                hi = _header_index(rows, "Дева")
                for r in rows[hi + 1:] if hi is not None else []:
                    hh = T.hero_from_name(str(r[0]))
                    if not hh or not str(r[1]).strip().isdigit():
                        continue
                    suf, ru, st, nt = T.entity_from_name("accessory", str(r[2]))
                    out.append(_v(hh[0], "accessory", suf, ru, "chatgpt", date, "list", int(r[1]), None, st, note, url, str(r[2])))
            elif sname.startswith("05_Карты"):
                hi = _header_index(rows, "Дева")
                for r in rows[hi + 1:] if hi is not None else []:
                    hh = T.hero_from_name(str(r[0]))
                    if not hh:
                        if r and str(r[0]).isupper():
                            break
                        continue
                    suf, ru, st, nt = T.entity_from_name("charm-card", str(r[1]))
                    out.append(_v(hh[0], "card", suf, ru, "chatgpt", date, "main", 1, None, st, note, url, str(r[1])))
            elif sname.startswith("08_Питомцы"):
                hi = _header_index(rows, "Дева")
                for r in rows[hi + 1:] if hi is not None else []:
                    hh = T.hero_from_name(str(r[0]))
                    if not hh or len(r) < 6:
                        continue
                    for k in range(4):
                        nm = str(r[2 + k]).strip()
                        if nm and len(nm) <= 40:
                            suf, ru, st, nt = T.entity_from_name("pet", nm)
                            out.append(_v(hh[0], "pet", suf, ru, "chatgpt", date, "list", k + 1, None, st, note, url, nm))
            elif sname.startswith("11_Руны") or sname.startswith("09_Руны"):
                hi = _header_index(rows, "Слот")
                for r in rows[hi + 1:] if hi is not None else []:
                    if not str(r[0]).strip().isdigit():
                        break
                    suf, ru, st, nt = T.entity_from_name("rune", str(r[1]))
                    out.append(_v(TEAM, "rune", suf, ru, "chatgpt", date, "list", int(r[0]), None, st, note, url, str(r[1])))
            elif sname.startswith("12_Оружие"):
                hi = _header_index(rows, "Место")
                for r in rows[hi + 1:] if hi is not None else []:
                    if not str(r[0]).strip().isdigit():
                        break
                    suf, ru, st, nt = T.entity_from_name("princess-weapon", str(r[1]))
                    out.append(_v(TEAM, "pw", suf, ru, "chatgpt", date, "list", int(r[0]), None, st, note, url, str(r[1])))
    return out


# --------------------------------------------------------------------------------------- weak priors
GRADE = {"SSS": 1.0, "SS": 1.0, "S": 0.8, "A": 0.6, "B": 0.4, "C": 0.25}
RARITY = {"UR": 1.0, "SSR": 0.7, "SR": 0.5, "Миф": 1.0, "Лег": 0.8, "Эпич": 0.6}
CLASS_CARD = {"Поддержка": "Саппорт", "Страж": "Страж", "Маг": "Маг", "Воин": "Воин"}


def hero_class(hero: str) -> str | None:
    for x in T.entities():
        if x["kind"] == "character" and T.hero_slug(x) == hero:
            parts = [p.strip() for p in (x.get("subtitle") or "").split("·")]
            return parts[-1] if parts else None
    return None


def priors(team_heroes: list[str], date: str = "2026-10-31") -> list[dict]:
    out = []
    for x in T.entities():
        suf = x["id"].split(":", 1)[1]
        sub = x.get("subtitle") or ""
        if x["kind"] == "rune":
            g = next((GRADE[t] for t in [p.strip() for p in sub.split("·")][::-1] if t in GRADE), None)
            if g:
                out.append(_v(TEAM, "rune", suf, x["title"], "lfru_grade", date, "list", 1, g, "lfru_alias", sub, "https://lunafantasy.ru/runes"))
        elif x["kind"] == "princess-weapon":
            m = re.match(r"(SSS|SS|S|A|B)-оружие", sub)
            if m:
                out.append(_v(TEAM, "pw", suf, x["title"], "lfru_grade", date, "list", 1, GRADE[m.group(1)], "lfru_alias", sub,
                              "https://lunafantasy.ru/princess-weapons"))
        elif x["kind"] == "charm-card":
            rar = next((RARITY[t] for t in RARITY if t in sub), 0.6)
            for hero in team_heroes:
                cls = hero_class(hero)
                if cls and CLASS_CARD.get(cls, cls) in sub:
                    out.append(_v(hero, "card", suf, x["title"], "class_fit", date, "list", 1, rar, "lfru_alias",
                                  f"класс {cls} ↔ {sub}", "https://lunafantasy.ru/charm-cards"))
        elif x["kind"] == "pet":
            rar = next((RARITY[t] for t in RARITY if sub.startswith(t)), None)
            if rar:
                for hero in team_heroes:
                    out.append(_v(hero, "pet", suf, x["title"], "lfru_grade", date, "list", 1, rar, "lfru_alias", sub,
                                  "https://lunafantasy.ru/pets"))
    return out


def collect_all(team_heroes: list[str]) -> list[dict]:
    vs = from_appmedia() + from_sbg() + from_lfru() + from_chatgpt() + priors(team_heroes)
    for v in vs:
        v["date"] = str(v["date"])[:10]
        dt.date.fromisoformat(v["date"])          # validate
    return vs
