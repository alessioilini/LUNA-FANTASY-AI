"""Knowledge base: sourced facts per region and balance version.

Storage: data/kb/facts/<REGION>.jsonl - one Fact per line (see luna.provenance.Fact).
User-imported facts go to data/kb/facts/<REGION>.user.jsonl so seeds can be regenerated.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .provenance import Fact, Region, Confidence, UNKNOWN, ensure_single_balance, is_unknown

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FACTS_DIR = DATA / "kb" / "facts"

CONF_RANK = {c: i for i, c in enumerate([
    Confidence.SYNTHETIC, Confidence.HYPOTHESIS, Confidence.LOW, Confidence.USER_STATED,
    Confidence.MEDIUM, Confidence.HIGH, Confidence.CONFIRMED])}


@dataclass
class KnowledgeBase:
    facts: list[Fact] = field(default_factory=list)

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, path: Path | None = None, regions: Iterable[str] | None = None) -> "KnowledgeBase":
        path = path or FACTS_DIR
        kb = cls()
        wanted = set(regions) if regions else None
        for f in sorted(Path(path).glob("*.jsonl")):
            region = f.name.split(".")[0]
            if wanted and region not in wanted:
                continue
            for line_no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    kb.facts.append(Fact.from_dict(json.loads(line)))
                except Exception as e:  # pragma: no cover - surfaced to the user
                    raise ValueError(f"{f}:{line_no}: invalid fact: {e}") from e
        return kb

    def add(self, fact: Fact, persist: bool = False, path: Path | None = None) -> None:
        self.facts.append(fact)
        if persist:
            p = Path(path or FACTS_DIR) / f"{fact.region.value}.user.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(fact.to_dict(), ensure_ascii=False) + "\n")

    # --------------------------------------------------------------- query
    def query(self, prefix: str = "", region: str | None = None, balance_version: str | None = None,
              min_confidence: Confidence | None = None) -> list[Fact]:
        out = []
        for f in self.facts:
            if prefix and not f.key.startswith(prefix):
                continue
            if region and f.region.value != region:
                continue
            if balance_version and f.balance_version != balance_version:
                continue
            if min_confidence and CONF_RANK[f.confidence] < CONF_RANK[min_confidence]:
                continue
            out.append(f)
        return out

    def best(self, key: str, region: str, balance_version: str | None = None):
        """Highest-confidence value for key within ONE region (never falls back to another region)."""
        cands = self.query(key, region=region, balance_version=balance_version)
        cands = [f for f in cands if f.key == key]
        if not cands:
            return UNKNOWN, None
        cands.sort(key=lambda f: CONF_RANK[f.confidence], reverse=True)
        top = cands[0]
        return top.value, top

    def conflicts(self) -> list[dict]:
        """Same key + same region + same balance version but different values."""
        groups: dict[tuple, list[Fact]] = defaultdict(list)
        for f in self.facts:
            groups[(f.key, f.region.value, f.balance_version)].append(f)
        out = []
        for (k, r, v), fs in groups.items():
            vals = {json.dumps(x.to_dict()["value"], ensure_ascii=False, sort_keys=True) for x in fs}
            if len(vals) > 1:
                out.append({"key": k, "region": r, "balance_version": v,
                            "values": [x.to_dict()["value"] for x in fs],
                            "sources": [x.source.url for x in fs]})
        return out

    def hero_ids(self) -> list[str]:
        ids = set()
        for f in self.facts:
            if f.key.startswith("hero."):
                ids.add(f.key.split(".")[1])
        return sorted(ids)

    def hero_card(self, hero_id: str) -> dict:
        """All facts about one hero grouped by region - regions are NEVER merged."""
        card: dict = {"id": hero_id, "regions": {}}
        for f in self.query(f"hero.{hero_id}."):
            attr = f.key[len(f"hero.{hero_id}."):]
            card["regions"].setdefault(f.region.value, {})[attr] = {
                "value": f.to_dict()["value"], "confidence": f.confidence.value,
                "source": f.source.url, "ru_status": f.ru_status.value,
                "balance_version": f.balance_version, "notes": f.notes}
        return card

    def coverage_report(self) -> dict:
        """What is known vs missing for the P0 hero model in the RU region."""
        required = ["name.ru", "element", "class", "role", "stat.ATK", "stat.HP", "stat.DEF", "stat.SPD", "skills"]
        rows = {}
        for hid in self.hero_ids():
            ru = {f.key.split(".", 2)[2] for f in self.query(f"hero.{hid}.", region="RU")}
            rows[hid] = {
                "ru_known": sorted(ru),
                "ru_missing": [r for r in required if r not in ru],
                "other_regions": sorted({f.region.value for f in self.query(f"hero.{hid}.") if f.region != Region.RU}),
            }
        return {"heroes": rows,
                "facts_by_region": {r.value: len(self.query(region=r.value)) for r in Region},
                "facts_by_confidence": {c.value: sum(1 for f in self.facts if f.confidence == c) for c in Confidence},
                "conflicts": self.conflicts()}

    def numeric(self, key: str, region: str, balance_version: str | None = None):
        v, fact = self.best(key, region, balance_version)
        if is_unknown(v):
            return UNKNOWN
        if fact is not None:
            ensure_single_balance([fact])
        return v
