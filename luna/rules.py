"""Game constraints + build/team validator (P0 "проверка игровых ограничений").

Structural rules come from KB facts (data/kb/facts/RU.jsonl). Every rule keeps its status;
an unverified rule produces a WARN instead of a hard ERROR, so a wrong assumption never
silently rejects a legal in-game build.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .kb import KnowledgeBase
from .model import Catalog, Team, HeroBuild, STAT_KEYS
from .provenance import is_unknown, Confidence

HARD_CONF = {Confidence.CONFIRMED, Confidence.HIGH, Confidence.SYNTHETIC}  # synthetic rules are hard inside the fixture world


@dataclass
class Rule:
    key: str
    value: object
    confidence: str
    source: str

    @property
    def hard(self) -> bool:
        return self.confidence in {c.value for c in HARD_CONF}


@dataclass
class GameRules:
    region: str
    rules: dict = field(default_factory=dict)

    @classmethod
    def from_kb(cls, kb: KnowledgeBase, region: str = "RU") -> "GameRules":
        gr = cls(region=region)
        for f in kb.query("rules.", region=region):
            gr.rules[f.key[len("rules."):]] = Rule(f.key, f.value, f.confidence.value, f.source.url)
        return gr

    def get(self, key: str, default=None):
        r = self.rules.get(key)
        return default if r is None or is_unknown(r.value) else r.value

    def rule(self, key: str) -> Rule | None:
        return self.rules.get(key)


@dataclass
class Issue:
    level: str      # ERROR | WARN | INFO
    code: str
    message: str
    path: str = ""

    def __str__(self):
        return f"[{self.level}] {self.code} {self.path}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    def add(self, level, code, message, path=""):
        self.issues.append(Issue(level, code, message, path))

    @property
    def ok(self) -> bool:
        return not any(i.level == "ERROR" for i in self.issues)

    def codes(self, level: str | None = None) -> list[str]:
        return [i.code for i in self.issues if level is None or i.level == level]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "issues": [i.__dict__ for i in self.issues]}


def _limit(rep: ValidationReport, rules: GameRules, key: str, actual: int, path: str, what: str, exact: bool = False):
    r = rules.rule(key)
    if r is None or is_unknown(r.value):
        rep.add("INFO", "RULE_UNKNOWN", f"лимит для «{what}» неизвестен ({key}) - проверка пропущена", path)
        return
    lim = int(r.value)
    bad = actual != lim if exact else actual > lim
    if bad:
        lvl = "ERROR" if (r.hard or r.confidence == "user_stated") and actual > lim else "WARN"
        if exact and actual < lim:
            lvl = "WARN"
        rep.add(lvl, "SLOT_COUNT", f"«{what}»: {actual}, ожидается {'ровно ' if exact else 'не более '}{lim} "
                f"(правило {key}, достоверность {r.confidence})", path)
    elif not r.hard:
        rep.add("INFO", "RULE_UNVERIFIED", f"лимит «{what}»={lim} не подтверждён в RU-клиенте ({r.confidence})", path)


def validate_hero(hb: HeroBuild, cat: Catalog, rules: GameRules, idx: int = 0,
                  stacking_assumptions: dict | None = None) -> ValidationReport:
    rep = ValidationReport()
    p = f"heroes[{idx}]({hb.hero_id})"
    stacking_assumptions = stacking_assumptions or {}
    if not cat.has("heroes", hb.hero_id):
        rep.add("ERROR", "UNKNOWN_HERO", "героиня отсутствует в каталоге этой версии баланса", p)

    # ---- stats
    for k, v in hb.stats.items():
        if k not in STAT_KEYS:
            rep.add("WARN", "UNKNOWN_STAT", f"неизвестная характеристика {k}", p)
        if is_unknown(v):
            rep.add("WARN", "STAT_UNKNOWN", f"{k}=UNKNOWN - для симуляции нужен априор/допущение", p)
    for k in ("ATK", "HP", "DEF", "SPD"):
        if k not in hb.stats:
            rep.add("WARN", "STAT_MISSING", f"нет значения {k}", p)

    # ---- sigils (2 x 2 talents) - a separate system from personal talents
    _limit(rep, rules, "build.sigil_count", len(hb.sigils), p + ".sigils", "сигилы")
    sigil_talents = []
    for si, s in enumerate(hb.sigils):
        sp = f"{p}.sigils[{si}]"
        if not cat.has("sigils", s.get("id", "")):
            rep.add("ERROR", "UNKNOWN_ITEM", f"сигил {s.get('id')} не найден", sp)
        tl = s.get("talents", [])
        _limit(rep, rules, "build.talents_per_sigil", len(tl), sp, "таланты сигила")
        for t in tl:
            if not cat.has("talents", t):
                rep.add("ERROR", "UNKNOWN_ITEM", f"талант {t} не найден", sp)
                continue
            kind = cat.get("talents", t).get("system", "sigil")
            if kind != "sigil":
                rep.add("ERROR", "SYSTEM_MIX", f"талант {t} относится к системе «{kind}», а не к сигилам", sp)
            sigil_talents.append(t)
    _limit(rep, rules, "build.separate_talent_count", len(hb.talents), p + ".talents", "отдельные таланты")
    for t in hb.talents:
        if not cat.has("talents", t):
            rep.add("ERROR", "UNKNOWN_ITEM", f"талант {t} не найден", p + ".talents")
            continue
        kind = cat.get("talents", t).get("system", "personal")
        if kind != "personal":
            rep.add("ERROR", "SYSTEM_MIX", f"талант {t} относится к системе «{kind}», а не к личным талантам", p + ".talents")

    # duplicate effects: needs an explicit stacking assumption
    effect_keys = []
    for t in sigil_talents + list(hb.talents):
        if cat.has("talents", t):
            effect_keys.append(cat.get("talents", t).get("effect_key", t))
    for key, n in Counter(effect_keys).items():
        if n > 1:
            pol = stacking_assumptions.get(key)
            if pol is None:
                rep.add("WARN", "DUPLICATE_EFFECT",
                        f"эффект {key} встречается {n} раза; правило стакания неизвестно - "
                        f"задайте допущение stacking[{key}] = stack|refresh|unique перед симуляцией", p)
            elif pol == "unique":
                rep.add("INFO", "DUPLICATE_IGNORED", f"{key}: по допущению действует один экземпляр", p)

    # ---- limbs: 4 positions, 2/4 set bonuses
    _limit(rep, rules, "build.limb_slots", len(hb.limbs), p + ".limbs", "лимбы")
    seen_pos = set()
    for li, lid in enumerate(hb.limbs):
        if lid is None:
            continue
        if not cat.has("limbs", lid):
            rep.add("ERROR", "UNKNOWN_ITEM", f"лимб {lid} не найден", f"{p}.limbs[{li}]")
            continue
        pos = cat.get("limbs", lid).get("position")
        if pos is not None and pos != li:
            rep.add("ERROR", "WRONG_POSITION", f"лимб {lid} предназначен для позиции {pos + 1}, стоит в {li + 1}", f"{p}.limbs[{li}]")
        if pos is not None and pos in seen_pos:
            rep.add("ERROR", "POSITION_TAKEN", f"позиция {pos + 1} занята дважды", f"{p}.limbs")
        seen_pos.add(pos)

    # ---- decorations
    _limit(rep, rules, "build.decoration_slots", len(hb.decorations), p + ".decorations", "украшения")
    for d in hb.decorations:
        if d is not None and not cat.has("decorations", d):
            rep.add("ERROR", "UNKNOWN_ITEM", f"украшение {d} не найдено", p + ".decorations")

    # ---- pets: slots depend on rarity (table unknown)
    slots_by_rarity = rules.get("build.pet_slots_by_rarity")
    for pid in hb.pets:
        if not cat.has("pets", pid):
            rep.add("ERROR", "UNKNOWN_ITEM", f"питомец {pid} не найден", p + ".pets")
    if hb.pets:
        if not slots_by_rarity:
            rep.add("WARN", "PET_SLOTS_UNKNOWN", "число слотов питомцев зависит от редкости; таблица не подтверждена", p + ".pets")
        else:
            rarity = cat.get("heroes", hb.hero_id).get("rarity") if cat.has("heroes", hb.hero_id) else None
            lim = slots_by_rarity.get(str(rarity)) if isinstance(slots_by_rarity, dict) else None
            if lim is not None and len(hb.pets) > lim:
                rep.add("ERROR", "SLOT_COUNT", f"питомцев {len(hb.pets)} > {lim} для редкости {rarity}", p + ".pets")

    for c in hb.charm_cards:
        if not cat.has("charm_cards", c):
            rep.add("ERROR", "UNKNOWN_ITEM", f"карта прелестей {c} не найдена", p + ".charm_cards")

    # ---- double counting
    for m in hb.extra_mods:
        if m.get("layer") == "team":
            rep.add("ERROR", "GLOBAL_IN_PERSONAL", f"глобальный бонус {m.get('source_id')} записан в личный слой героини - "
                    "перенесите его в team.global_stats", p)
    if hb.stats_mode == "panel" and (hb.limbs or hb.decorations or hb.extra_mods or hb.sigils or hb.pets):
        rep.add("WARN", "PANEL_STATS", "характеристики взяты с панели (уже включают экипировку): статы предметов НЕ будут "
                "прибавлены повторно, учитываются только их боевые эффекты", p)
    return rep


def validate_team(team: Team, cat: Catalog, rules: GameRules, inventory: dict | None = None,
                  stacking_assumptions: dict | None = None) -> ValidationReport:
    rep = ValidationReport()
    if team.region != cat.region or (cat.balance_version != "UNKNOWN" and team.balance_version not in ("UNKNOWN", cat.balance_version)):
        rep.add("ERROR", "MIXED_BALANCE", f"команда {team.region}/{team.balance_version} vs каталог {cat.region}/{cat.balance_version}")
    _limit(rep, rules, "team.size", len(team.heroes), "team", "героини в команде", exact=True)
    ids = [h.hero_id for h in team.heroes]
    for hid, n in Counter(ids).items():
        if n > 1:
            rep.add("ERROR", "DUPLICATE_HERO", f"{hid} в команде {n} раза", "team")
    # formation
    positions = [team.position_of(h.hero_id, i) for i, h in enumerate(team.heroes)]
    n_pos = int(rules.get("team.size", 6))
    for hid, pos in zip(ids, positions):
        if not 0 <= pos < n_pos:
            rep.add("ERROR", "BAD_POSITION", f"{hid}: позиция {pos} вне 0..{n_pos - 1}", "formation")
    for pos, n in Counter(positions).items():
        if n > 1:
            rep.add("ERROR", "POSITION_TAKEN", f"позиция {pos} занята {n} героинями", "formation")
    for i, h in enumerate(team.heroes):
        rep.issues += validate_hero(h, cat, rules, i, stacking_assumptions).issues

    # runes: 4, ordered
    _limit(rep, rules, "team.rune_count", len(team.runes), "runes", "руны", exact=True)
    for r in team.runes:
        if not cat.has("runes", r):
            rep.add("ERROR", "UNKNOWN_ITEM", f"руна {r} не найдена", "runes")
    if len(set(team.runes)) != len(team.runes):
        rep.add("WARN", "DUPLICATE_RUNE", "повтор руны: допустимость не подтверждена", "runes")
    # princess weapon: 4 positions
    _limit(rep, rules, "team.princess_weapon_positions", len(team.princess_weapon), "princess_weapon", "позиции оружия принцессы")
    for i, part in enumerate(team.princess_weapon):
        if part is None:
            continue
        if not cat.has("princess_weapon_parts", part):
            rep.add("ERROR", "UNKNOWN_ITEM", f"часть оружия {part} не найдена", f"princess_weapon[{i}]")
            continue
        pos = cat.get("princess_weapon_parts", part).get("position")
        if pos is not None and pos != i:
            rep.add("ERROR", "WRONG_POSITION", f"{part} предназначена для позиции {pos + 1}", f"princess_weapon[{i}]")
    for r in team.relics:
        if not cat.has("relics", r):
            rep.add("ERROR", "UNKNOWN_ITEM", f"реликт {r} не найден", "relics")

    # global stats double counting
    team_srcs = Counter(m.get("source_id") for m in team.global_stats + team.faction_bonus if m.get("source_id"))
    for s, n in team_srcs.items():
        if n > 1:
            rep.add("ERROR", "GLOBAL_DOUBLED", f"глобальный бонус {s} указан {n} раза", "global_stats")
    personal_srcs = {m.get("source_id") for h in team.heroes for m in h.extra_mods if m.get("source_id")}
    for s in personal_srcs & set(team_srcs):
        rep.add("ERROR", "GLOBAL_DOUBLED", f"бонус {s} одновременно в личном и командном слое", "global_stats")

    # inventory (each physical item used at most as many times as owned)
    if inventory is not None:
        used = Counter()
        for h in team.heroes:
            used.update(f"heroes:{h.hero_id}" for _ in [0])
            used.update(f"sigils:{s['id']}" for s in h.sigils)
            used.update(f"limbs:{x}" for x in h.limbs if x)
            used.update(f"decorations:{x}" for x in h.decorations if x)
            used.update(f"pets:{x}" for x in h.pets)
            used.update(f"charm_cards:{x}" for x in h.charm_cards)
        used.update(f"runes:{x}" for x in team.runes)
        used.update(f"princess_weapon_parts:{x}" for x in team.princess_weapon if x)
        used.update(f"relics:{x}" for x in team.relics)
        for k, n in used.items():
            have = inventory.get(k, 0)
            if n > have:
                rep.add("ERROR", "NOT_OWNED", f"{k}: требуется {n}, в наличии {have}", "inventory")
    return rep
