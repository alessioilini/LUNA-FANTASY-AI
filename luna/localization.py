"""RU/EN/JP/KR glossary with per-term verification status.

`ru_status`: user_stated (operator gave the RU-client term) | generic (plain translation,
NOT confirmed as the in-game label) | missing.  `jp_status`: name_match | hypothesis | search_snippet.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

GLOSSARY = Path(__file__).resolve().parents[1] / "data" / "glossary.json"
LANGS = ("ru", "en", "jp", "kr")


@lru_cache(maxsize=1)
def _load(path: str = str(GLOSSARY)) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    index = {}
    for e in data["entries"]:
        index[e["key"]] = e
    return {"entries": data["entries"], "index": index}


def term(key: str, lang: str = "ru", fallback: str = "en") -> str:
    e = _load()["index"].get(key)
    if not e:
        return key
    return e.get(lang) or e.get(fallback) or key


def lookup(text: str) -> list[dict]:
    """Find entries whose name in any language (or alias) equals text (case-insensitive)."""
    t = text.strip().lower()
    out = []
    for e in _load()["entries"]:
        names = [e.get(l) for l in LANGS] + e.get("aliases_ru", [])
        if any(n and n.lower() == t for n in names):
            out.append(e)
    return out


def resolve_hero(text: str) -> str | None:
    hits = [e for e in lookup(text) if e["category"] == "hero"]
    return hits[0]["key"].split(".", 1)[1] if hits else None


def unverified_terms() -> list[dict]:
    return [e for e in _load()["entries"] if e.get("ru_status") != "user_stated"]


def label(key: str) -> str:
    """'RU (EN)' label for UI; marks generic translations with '*'."""
    e = _load()["index"].get(key)
    if not e:
        return key
    ru = e.get("ru") or e.get("en")
    star = "" if e.get("ru_status") == "user_stated" else "*"
    return f"{ru}{star}" if ru == e.get("en") else f"{ru}{star} ({e.get('en')})"
