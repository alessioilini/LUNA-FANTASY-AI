"""Runtime battle state: units, statuses, per-unit statistics."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..model import FRACTION_STATS

CONTROL_SKIP = {"stun", "freeze", "sleep", "petrify"}
CONTROL_SILENCE = {"silence"}


@dataclass
class Status:
    key: str
    kind: str                       # buff | debuff
    source: str                     # uid of applier
    mods: list = field(default_factory=list)   # [{stat, value, mode}]
    duration: int | None = None     # None = permanent
    stacks: int = 1
    max_stacks: int = 1
    stacking: str | None = None     # refresh | stack | independent
    control: str | None = None
    dot: dict | None = None
    hot: dict | None = None
    revive_ban: bool = False
    reflect: float = 0.0
    shield_amount: float = 0.0
    undispellable: bool = False
    persist_on_death: bool = False
    tick: str | None = None         # owner_turn_end | round_end (override)
    seq: int = 0
    ability: str = ""


@dataclass
class UnitStats:
    actions: int = 0
    extra_actions: int = 0
    combo_triggers: int = 0
    skipped_turns: int = 0
    dmg_raw: float = 0.0          # damage computed before shields
    dmg_effective: float = 0.0    # HP actually removed (no overkill, no shield)
    dmg_to_shield: float = 0.0
    overkill: float = 0.0
    dmg_taken_hp: float = 0.0
    dmg_absorbed_by_own_shield: float = 0.0
    heal_effective: float = 0.0
    overheal: float = 0.0
    shield_given: float = 0.0
    ctrl_attempts: int = 0
    ctrl_landed: int = 0
    ctrl_resisted: int = 0
    turns_controlled: int = 0
    revives_done: int = 0
    revived_times: int = 0
    revive_blocked: int = 0
    deaths: int = 0
    kills: int = 0
    crits: int = 0
    misses: int = 0
    dodges: int = 0
    reflected: float = 0.0
    cleansed: int = 0
    dispelled: int = 0
    by_ability: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))  # ability -> {dmg, heal, shield, casts}


@dataclass
class Unit:
    uid: str
    side: str            # A | B
    pos: int
    hero_id: str
    name: str
    stats: dict          # final out-of-battle stats
    abilities: list
    max_hp: float = 0.0
    hp: float = 0.0
    alive: bool = True
    statuses: list = field(default_factory=list)
    cooldowns: dict = field(default_factory=dict)
    trig_round: dict = field(default_factory=lambda: defaultdict(int))
    trig_battle: dict = field(default_factory=lambda: defaultdict(int))
    extra_this_round: int = 0
    is_team_source: bool = False
    st: UnitStats = field(default_factory=UnitStats)
    death_log: list = field(default_factory=list)
    tags: set = field(default_factory=set)

    def __post_init__(self):
        self.max_hp = float(self.stats.get("HP", 0))
        self.hp = self.max_hp

    # ------------------------------------------------------------ stats
    def stat(self, key: str) -> float:
        base = float(self.stats.get(key, 0.0) or 0.0)
        flat = pct = 0.0
        for s in self.statuses:
            for m in s.mods:
                if m["stat"] != key:
                    continue
                v = m["value"] * (s.stacks if s.stacking == "stack" else 1)
                if m.get("mode", "flat") == "pct" and key not in FRACTION_STATS:
                    pct += v
                else:
                    flat += v
        if key in FRACTION_STATS:
            return base + flat
        return max(0.0, base * (1 + pct) + flat)

    @property
    def shield(self) -> float:
        return sum(s.shield_amount for s in self.statuses if s.shield_amount > 0)

    def shields(self) -> list:
        return [s for s in self.statuses if s.shield_amount > 0]

    def has_control(self, kinds=CONTROL_SKIP) -> str | None:
        for s in self.statuses:
            if s.control in kinds:
                return s.control
        return None

    def revive_banned(self) -> bool:
        return any(s.revive_ban for s in self.statuses)

    def reflect_pct(self) -> float:
        return sum(s.reflect * (s.stacks if s.stacking == "stack" else 1) for s in self.statuses)

    def hp_frac(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 0.0
