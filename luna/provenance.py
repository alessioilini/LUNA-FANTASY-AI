"""Provenance layer: every fact in the knowledge base carries its origin.

Rules enforced here (see tests/test_provenance.py):
  * a Fact without region, source and confidence is rejected;
  * facts from different (region, balance_version) pairs are never merged;
  * a numeric value may be the UNKNOWN sentinel - it is never silently replaced.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class _Unknown:
    """Sentinel for a value that no source confirms. Truthiness raises to stop accidental math."""

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "UNKNOWN"

    def __bool__(self):
        raise ValueError("UNKNOWN value used in a boolean/numeric context - supply a sourced value or an explicit assumption")

    def __float__(self):
        raise ValueError("UNKNOWN value cannot be converted to a number")

    __int__ = __float__

    def __reduce__(self):
        return (_Unknown, ())


UNKNOWN = _Unknown()


def is_unknown(v: Any) -> bool:
    return v is UNKNOWN or v == "UNKNOWN"


def to_json_value(v: Any) -> Any:
    return "UNKNOWN" if v is UNKNOWN else v


def from_json_value(v: Any) -> Any:
    return UNKNOWN if v == "UNKNOWN" else v


class Region(str, Enum):
    RU = "RU"          # Luna Fantasy (lunafantasy.ru community KB; RU client)
    JP = "JP"          # やばい！少女に囲まれた！
    EN = "EN"          # Tales of Angels
    SEA = "SEA"        # Maidens Fantasy: LUST | SEA
    KR = "KR"          # 각성소녀: 욕망의 여정 (not confirmed by any fetched source yet)
    RR = "RR"          # Realm Rush: Bonded Maidens (Vietnamese, QooApp 132451)
    GLOBAL = "GLOBAL"  # "グローバル版/海外版" texts as quoted by JP guides (exact client not specified)
    TW = "TW"          # 完蛋！我被美少女攻略了 (traditional Chinese)
    OTHER = "OTHER"
    SYNTHETIC = "SYNTHETIC"  # test fixtures only - never game data


class Confidence(str, Enum):
    CONFIRMED = "confirmed"        # official source or in-game screenshot
    HIGH = "high"                  # reputable guide with numbers, cross-checked
    MEDIUM = "medium"              # single guide / store page
    LOW = "low"                    # search snippet, forum post, community claim
    USER_STATED = "user_stated"    # stated by the operator in a prompt, not yet verified
    HYPOTHESIS = "hypothesis"      # our own assumption
    SYNTHETIC = "synthetic"        # test fixture


class RuStatus(str, Enum):
    VERIFIED_IN_RU_CLIENT = "verified_in_ru_client"
    UNVERIFIED = "unverified"
    NOT_IN_RU = "not_in_ru"
    CONTRADICTED = "contradicted"
    NOT_APPLICABLE = "n/a"


@dataclass(frozen=True)
class Source:
    url: str
    title: str = ""
    accessed: str = ""          # ISO date the source was read
    kind: str = "web"           # web | search_snippet | screenshot | user_prompt | in_game | fixture
    note: str = ""


@dataclass
class Fact:
    """One sourced statement about the game."""

    key: str                    # e.g. "hero.kira.stat.SPD@lvl240"
    value: Any
    region: Region
    source: Source
    confidence: Confidence
    balance_version: str = "UNKNOWN"   # client version / patch label
    version_date: str = "UNKNOWN"      # date of that patch or of the source page
    ru_name: str | None = None
    original_name: str | None = None
    ru_status: RuStatus = RuStatus.UNVERIFIED
    notes: str = ""

    def __post_init__(self):
        if not self.key:
            raise ValueError("Fact.key is required")
        if not isinstance(self.region, Region):
            self.region = Region(self.region)
        if not isinstance(self.confidence, Confidence):
            self.confidence = Confidence(self.confidence)
        if not isinstance(self.ru_status, RuStatus):
            self.ru_status = RuStatus(self.ru_status)
        if isinstance(self.source, dict):
            self.source = Source(**self.source)
        if not self.source or not self.source.url:
            raise ValueError(f"Fact {self.key!r} has no source URL/identifier")
        if self.region == Region.SYNTHETIC and self.confidence != Confidence.SYNTHETIC:
            raise ValueError("SYNTHETIC region facts must have SYNTHETIC confidence")
        if self.confidence == Confidence.SYNTHETIC and self.region != Region.SYNTHETIC:
            raise ValueError("SYNTHETIC confidence is only allowed for SYNTHETIC region")
        self.value = from_json_value(self.value)

    @property
    def balance_key(self) -> tuple[str, str]:
        return (self.region.value, self.balance_version)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["value"] = to_json_value(self.value)
        d["region"] = self.region.value
        d["confidence"] = self.confidence.value
        d["ru_status"] = self.ru_status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Fact":
        return cls(**d)


class MixedBalanceError(ValueError):
    pass


def ensure_single_balance(facts: list[Fact]) -> tuple[str, str] | None:
    """Raise if a computation would mix facts from different region/balance versions."""
    keys = {f.balance_key for f in facts if f.region != Region.SYNTHETIC}
    if len(keys) > 1:
        raise MixedBalanceError(f"facts come from several balance versions: {sorted(keys)}")
    return next(iter(keys), None)
