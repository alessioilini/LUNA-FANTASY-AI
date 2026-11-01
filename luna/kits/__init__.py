"""Hero kits encoded from skill texts (stage 'real kits').

Every kit function takes the heroine's awakening level and an AssumptionSet and returns
{"class": ..., "abilities": [...], "notes": [...], "sources": [...]}. Values that change with
awakening are written as aw(level, base, (threshold, value), ...). Interpretation choices are listed in
`notes` with the assumption id they depend on - nothing is silently approximated.

Text priority (operator decision V1, 2026-11-01): GLOBAL numbers by default; values the operator verified
in the RU client override (Мяоинь: 194% / безмолвие 1 ход; Кира: 5%).
"""
from __future__ import annotations

from ..engine.assumptions import AssumptionSet


def aw(level, base, *steps):
    """Value by awakening level: aw(24, 134, (5, 159)) -> 159."""
    v = base
    for thr, val in steps:
        if level is not None and level >= thr:
            v = val
    return v


class KitBuilder:
    def __init__(self, hero_id: str, cls: str, asm: AssumptionSet):
        self.hero_id = hero_id
        self.cls = cls
        self.asm = asm
        self.abilities: list[dict] = []
        self.notes: list[str] = []

    # ------------------------------------------------------------------ helpers

    def basic(self, effects=None, aid="basic", name_ru="Обычная атака", dtype=None):
        if dtype is None:
            dtype = "magic" if self.cls in ("Маг", "Поддержка") else "physical"
        coef = float(self.asm.get("kit.basic_coef"))
        effects = effects or [{"op": "damage", "target": "enemy_single", "coef": coef, "dtype": dtype}]
        self.abilities.append({"id": f"{self.hero_id}:{aid}", "kind": "basic", "name_ru": name_ru, "tags": [dtype, "basic"],
                               "effects": effects})
        return f"{self.hero_id}:{aid}"

    def active(self, aid, name_ru, effects, ct=None, first=1, prio=5, tags=(), on="turn"):
        trig = {"on": on}
        if ct:
            trig["ct"] = ct            # raw skill-text values; the engine applies cd.model / cd.clock
        if first:
            trig["first"] = first
        full = f"{self.hero_id}:{aid}"
        self.abilities.append({"id": full, "kind": "active", "name_ru": name_ru, "priority": prio, "trigger": trig,
                               "effects": effects, "tags": list(tags)})
        return full

    def passive(self, aid, name_ru, on, effects, **trig):
        full = f"{self.hero_id}:{aid}"
        self.abilities.append({"id": full, "kind": "passive", "name_ru": name_ru, "trigger": dict({"on": on}, **trig),
                               "effects": effects})
        return full

    def constitution(self, mods: list[dict], name_ru: str):
        """'Тело …' passive: % bonuses. If kit.constitution_in_panel, they are already in the panel sample."""
        if self.asm.get("kit.constitution_in_panel"):
            self.notes.append(f"{name_ru}: бонусы {mods} считаются уже учтёнными в панельных статах (kit.constitution_in_panel)")
            return
        self.passive("constitution", name_ru, "battle_start",
                     [{"op": "status", "target": "self", "status": {"key": f"{self.hero_id}:const", "kind": "buff",
                                                                     "undispellable": True, "mods": mods}}])

    @property
    def round_event(self):
        return "round_start" if self.asm.get("kit.turn_means_round") else "turn_start"

    def build(self, sources):
        return {"class": self.cls, "abilities": self.abilities, "notes": self.notes, "sources": sources}


def st(key, **kw):
    return dict({"key": key}, **kw)


from .main_team import KITS  # noqa: E402  (registry)
