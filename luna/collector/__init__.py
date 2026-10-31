"""Data collector for lunafantasy.ru and regional guides.

Online fetching respects robots.txt and caches pages under data/cache/html. In this environment
lunafantasy.ru, appmedia.jp, surrounded-by-girls.online and qoo-app.com were blocked by the
network policy (2026-10-31), so the supported path is OFFLINE ingestion: save pages from a
browser and run `luna collect --offline-dir <dir>`. Parsed values become *pending* facts that must
be reviewed (`luna kb accept`) before they enter the knowledge base.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "html"
PENDING = ROOT / "data" / "kb" / "pending"

SOURCES = {
    "RU": {"base": "https://lunafantasy.ru/", "sections": ["Персонажи", "Билды", "Таланты", "Сигилы", "Лимбы", "Украшения",
                                                           "Питомцы", "Руны", "Оружие принцессы", "Карты прелестей", "Реликты",
                                                           "Бой и формации", "Команды", "Ссылки на региональные источники"]},
    "JP": {"base": "https://appmedia.jp/yabasyoujyo", "title": "やばい！少女に囲まれた！"},
    "EN": {"base": "https://m-apps.qoo-app.com/en-US/app/78580", "title": "Tales of Angels"},
    "SEA": {"base": "https://m-apps.qoo-app.com/en-US/app/78074", "title": "Maidens Fantasy: LUST | SEA"},
    "COMMUNITY": {"base": "https://surrounded-by-girls.online/", "title": "community character pages"},
}

STAT_PATTERNS = {
    "ATK": r"(?:атака|атк|atk|攻撃力?)", "HP": r"(?:здоровье|hp|хп|体力|ＨＰ)", "DEF": r"(?:защита|def|防御力?)",
    "SPD": r"(?:скр|скорость|spd|速度|素早さ)", "CRIT": r"(?:шанс крит[\w.]*(?:\s+удар\w*)?|крит\.? шанс|crit(?:ical)? (?:rate|chance)|会心率)",
    "CRIT_DMG": r"(?:крит\.? урон|урон крит\w*|crit(?:ical)? dmg|crit(?:ical)? damage|会心ダメージ)",
    "ACC": r"(?:точность|accuracy|命中)", "DODGE": r"(?:уклонение|dodge|evasion|回避)",
    "DR": r"(?:снижение урона|damage reduction|ダメージ軽減)", "IGNORE_DEF": r"(?:пробитие|игнор\w* защиты|ignore def\w*|防御無視)",
    "CTRL_RES": r"(?:сопротивление контролю|control res\w*|状態異常耐性)", "HEAL_BONUS": r"(?:бонус лечения|healing bonus|回復量)",
}
NUM = r"([-+]?\d[\d\s.,]*\s*%?)"


def _num(s: str):
    s = s.strip().replace(" ", "").replace(" ", "")
    pct = s.endswith("%")
    s = s.rstrip("%")
    if s.count(",") and not s.count("."):
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100 if pct else v


def fetch(url: str, timeout: int = 20) -> dict:
    """Fetch + cache one page. Returns {'status': ok|blocked|error, ...}."""
    import requests
    from urllib import robotparser
    CACHE.mkdir(parents=True, exist_ok=True)
    pr = urlparse(url)
    rp = robotparser.RobotFileParser()
    try:
        r = requests.get(f"{pr.scheme}://{pr.netloc}/robots.txt", timeout=timeout)
        rp.parse(r.text.splitlines() if r.ok else [])
        if r.ok and not rp.can_fetch("luna-fantasy-ai", url):
            return {"status": "disallowed_by_robots", "url": url}
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "luna-fantasy-ai/0.1 (research; contact via repo)"})
    except Exception as e:  # network policy, DNS, TLS
        return {"status": "blocked_or_unreachable", "url": url, "error": str(e)[:300]}
    if not resp.ok:
        return {"status": "error", "url": url, "http": resp.status_code}
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    p = CACHE / f"{h}.html"
    p.write_text(resp.text, encoding="utf-8")
    (CACHE / f"{h}.json").write_text(json.dumps({"url": url, "fetched": dt.datetime.now().isoformat(timespec="seconds")}))
    return {"status": "ok", "url": url, "path": str(p)}


def parse_page(html: str, url: str, region: str = "RU") -> dict:
    """Generic extraction: page title, tables, stat lines. Output = candidate facts (status pending)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    title = (soup.find("h1") or soup.find("title"))
    title = title.get_text(" ", strip=True) if title else ""
    tables = []
    for t in soup.find_all("table"):
        rows = []
        for tr in t.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    stats = {}
    text_lines = [l.strip() for l in soup.get_text("\n").splitlines() if l.strip()]
    for rows in tables:
        for cells in rows:
            if len(cells) >= 2:
                text_lines.append(f"{cells[0]}: {cells[1]}")
    for line in text_lines:
        for stat, pat in STAT_PATTERNS.items():
            m = re.match(rf"^\s*{pat}\s*[:：\-–]?\s*{NUM}\s*$", line, flags=re.I)
            if m and stat not in stats:
                v = _num(m.group(1))
                if v is not None:
                    stats[stat] = v
    return {"url": url, "region": region, "title": title, "tables": tables, "stats": stats}


def to_pending_facts(parsed: dict, hero_id: str | None, source_url: str, accessed: str | None = None) -> list[dict]:
    accessed = accessed or dt.date.today().isoformat()
    hid = hero_id or re.sub(r"\W+", "_", parsed["title"].lower()).strip("_") or "unknown"
    facts = []
    for stat, v in parsed["stats"].items():
        facts.append({"key": f"hero.{hid}.stat.{stat}", "value": v, "region": parsed["region"],
                      "source": {"url": source_url, "title": parsed["title"], "accessed": accessed, "kind": "web"},
                      "confidence": "medium", "ru_status": "unverified", "balance_version": "UNKNOWN",
                      "notes": "auto-parsed; level/stars of the displayed stats must be checked during review"})
    return facts


def ingest_offline_dir(directory: str | Path, region: str = "RU", url_map: dict | None = None) -> dict:
    """Parse saved HTML pages -> data/kb/pending/<region>.jsonl (not yet trusted)."""
    directory = Path(directory)
    PENDING.mkdir(parents=True, exist_ok=True)
    out = PENDING / f"{region}.jsonl"
    n_pages = n_facts = 0
    with open(out, "a", encoding="utf-8") as fh:
        for p in sorted(directory.glob("**/*.htm*")):
            html = p.read_text(encoding="utf-8", errors="replace")
            url = (url_map or {}).get(p.name) or f"offline:{p.name}"
            parsed = parse_page(html, url, region)
            facts = to_pending_facts(parsed, p.stem, url)
            for f in facts:
                fh.write(json.dumps(f, ensure_ascii=False) + "\n")
            n_pages += 1
            n_facts += len(facts)
    return {"pages": n_pages, "pending_facts": n_facts, "file": str(out)}


def import_hero_csv(path: str | Path) -> list[dict]:
    """Manual template: hero_id,name_ru,stat,value,level,stars,source_url,date,confidence,region,balance_version"""
    import csv
    facts = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            key = f"hero.{r['hero_id']}.stat.{r['stat']}" if r.get("stat") else f"hero.{r['hero_id']}.name.ru"
            val = _num(r["value"]) if r.get("stat") else r.get("name_ru")
            note = f"level={r.get('level')} stars={r.get('stars')}"
            facts.append({"key": key, "value": val, "region": r.get("region") or "RU",
                          "source": {"url": r["source_url"], "accessed": r.get("date", ""), "kind": r.get("kind", "manual")},
                          "confidence": r.get("confidence") or "medium", "balance_version": r.get("balance_version") or "UNKNOWN",
                          "ru_name": r.get("name_ru") or None, "ru_status": r.get("ru_status") or "unverified", "notes": note})
    return facts
