"""Meta intelligence (stage 10): regional changes, tier lists, popular teams, RU release forecast.

Every entry is one of: confirmed (official/in-game) | community (guide, tier list, forum) | hypothesis (ours).
A heroine first seen outside RU is NEVER marked available in RU without an RU source.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "data" / "meta" / "entries.jsonl"
KINDS = {"new_hero", "skill_change", "item_change", "combo", "tier_list", "popular_team", "version_diff",
         "ru_release_forecast", "event"}
STATUSES = {"confirmed", "community", "hypothesis"}


class MetaError(ValueError):
    pass


def validate_entry(e: dict) -> dict:
    e = dict(e)
    if e.get("kind") not in KINDS:
        raise MetaError(f"kind must be one of {sorted(KINDS)}")
    if e.get("status") not in STATUSES:
        raise MetaError(f"status must be one of {sorted(STATUSES)}")
    if e["status"] != "hypothesis" and not e.get("source"):
        raise MetaError("non-hypothesis entries need a source")
    region = e.get("region", "RU")
    if region != "RU":
        if e.get("ru_available") is True and not e.get("ru_source"):
            raise MetaError("ru_available=True for a non-RU entry requires ru_source (RU client / lunafantasy.ru)")
        e.setdefault("ru_available", False if e["kind"] == "new_hero" else None)
    e.setdefault("date", dt.date.today().isoformat())
    e.setdefault("id", f"{region}:{e['kind']}:{e.get('subject', '')}:{e['date']}")
    return e


def add(entry: dict, path: Path = META) -> dict:
    e = validate_entry(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def load(path: Path = META) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def query(region=None, kind=None, status=None, path: Path = META) -> list[dict]:
    return [e for e in load(path) if (region is None or e.get("region") == region)
            and (kind is None or e["kind"] == kind) and (status is None or e["status"] == status)]


def forecast_ru(path: Path = META) -> list[dict]:
    """Heroes released in other regions and not confirmed in RU -> hypothesis list (never availability)."""
    ru_conf = {e.get("subject") for e in load(path) if e.get("region") == "RU" and e["kind"] == "new_hero"}
    out = []
    for e in load(path):
        if e["kind"] == "new_hero" and e.get("region") != "RU" and e.get("subject") not in ru_conf:
            out.append({"subject": e["subject"], "first_seen_region": e["region"], "first_seen": e["date"],
                        "status": "hypothesis", "ru_available": False,
                        "note": "Возможный будущий релиз в RU. Не считать доступной до подтверждения в RU-клиенте."})
    return out


def region_diff(kb) -> dict:
    """Which hero attributes are known per region (from the KB) - shows where RU data is missing."""
    by = {}
    for f in kb.query("hero."):
        hid = f.key.split(".")[1]
        attr = f.key.split(".", 2)[2]
        by.setdefault(hid, {}).setdefault(attr, set()).add(f.region.value)
    rows = []
    for hid, attrs in sorted(by.items()):
        for attr, regs in sorted(attrs.items()):
            rows.append({"hero": hid, "attr": attr, "regions": sorted(regs), "missing_in_RU": "RU" not in regs})
    return {"rows": rows, "summary": Counter(tuple(r["regions"]) for r in rows)}
