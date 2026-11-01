"""Event-driven 6x6 combat engine.

Flow per battle:
  battle_start triggers -> for each round: round_start triggers, pet phase (if round_start),
  action order (order.mode / order.tie_break) -> every unit takes a turn; after each action the
  reaction queue is drained (priority key: depth, event rank, -priority, speed order, seq) ->
  round_end: DoT/HoT, pet phase, round_end triggers, end-of-round extra actions, status ticks.

Every formula that is not confirmed reads its form from AssumptionSet (see assumptions.py).
"""
from __future__ import annotations

import heapq
import itertools
import random
from collections import defaultdict
from dataclasses import dataclass, field

from .assumptions import AssumptionSet
from .state import Unit, Status, CONTROL_SKIP, CONTROL_SILENCE

DEFAULT_RELATION = {
    "damaged": "self", "dodged": "self", "healed": "self", "controlled": "self", "revived": "self",
    "after_attack": "self", "crit": "self", "kill": "self", "self_death": "self",
    "ally_death": "ally", "enemy_death": "enemy", "action": "ally",
    "battle_start": "any", "round_start": "any", "round_end": "any", "pet_phase": "any",
    "shield_broken": "self", "status_applied": "self",
}
ATTACK_OPS = {"damage", "extra_attack", "extra_action"}


@dataclass
class Pending:
    unit: Unit
    ability: dict
    ctx: dict
    depth: int
    kind: str = "trigger"      # trigger | extra_attack | extra_action


@dataclass
class BattleResult:
    winner: str
    rounds: int
    seed: int
    units: list
    deaths: list
    round_damage: dict
    first_round: dict
    assumptions_used: list
    end_reason: str
    hp_left: dict
    log: list | None = None

    def unit(self, uid: str) -> dict:
        return next(u for u in self.units if u["uid"] == uid)


class Battle:
    def __init__(self, units_a: list[Unit], units_b: list[Unit], asm: AssumptionSet, seed: int = 0, log: bool = True):
        self.rng = random.Random(seed)
        self.seed = seed
        self.asm = asm
        self.units = units_a + units_b
        self.round = 0
        self.q: list = []
        self.seq = itertools.count()
        self.log: list | None = [] if log else None
        self.deaths: list = []
        self.eor_extras: list[Pending] = []
        self.order_index: dict[str, int] = {u.uid: i for i, u in enumerate(self.units)}
        self.round_damage = {"A": defaultdict(float), "B": defaultdict(float)}
        self.first_round = {"order": [], "controls": 0, "deaths": [], "damage": {"A": 0.0, "B": 0.0}}
        self._sseq = 0
        self.winner: str | None = None
        self.end_reason = ""
        self.max_depth = int(asm.get("react.max_depth"))
        self._cd_fresh: set = set()
        self.barriers: dict = {}          # side -> team barrier (Illusia-type shared shield)
        self._cd_set_round: dict = {}

        self.listeners = defaultdict(list)
        for u in self.units:
            for ab in u.abilities:
                kind = ab.get("kind", "passive")
                if kind in ("basic", "active"):
                    continue
                on = ab.get("trigger", {}).get("on")
                if on:
                    self.listeners[on].append((u, ab))
            for ab in u.abilities:
                self._init_timing(ab)
                c0 = ab.get("trigger", {}).get("initial_cooldown")
                if c0:
                    u.cooldowns[ab["id"]] = int(c0)
        self.fatal_listeners = list(self.listeners.pop("fatal", []))

    # ================================================================ helpers
    def _init_timing(self, ab: dict):
        """Raw skill text 'activation K / CT N' -> engine cooldown counters, per cd.model (critical, unconfirmed)."""
        t = ab.get("trigger", {})
        if "ct" not in t and "first" not in t:
            return
        model = self.asm.get("cd.model")
        ct, first = t.get("ct"), t.get("first", 1)
        if ct:
            t["cooldown"] = ct - 1 if model == "A_cycle" else ct
        if first and first > 1:
            t["initial_cooldown"] = first - 1
        t["_timing"] = {"model": model, "ct": ct, "first": first}

    def _set_cd(self, u: Unit, ab: dict):
        cd = ab.get("trigger", {}).get("cooldown")
        if cd:
            u.cooldowns[ab["id"]] = int(cd)
            self._cd_fresh.add((u.uid, ab["id"]))
            self._cd_set_round[(u.uid, ab["id"])] = self.round

    def _tick_cd(self, u: Unit):
        """A cooldown is never decremented in the round in which it was started."""
        for k in list(u.cooldowns):
            if u.cooldowns[k] > 0 and self._cd_set_round.get((u.uid, k)) != self.round:
                u.cooldowns[k] -= 1

    def _next_sseq(self) -> int:
        self._sseq += 1
        return self._sseq

    def _log(self, **e):
        if self.log is not None:
            e["r"] = self.round
            self.log.append(e)

    def fighters(self, side: str | None = None, alive: bool | None = True) -> list[Unit]:
        return [u for u in self.units if not u.is_team_source and (side is None or u.side == side)
                and (alive is None or u.alive == alive)]

    @staticmethod
    def other(side: str) -> str:
        return "B" if side == "A" else "A"

    def _check_end(self) -> bool:
        if self.winner:
            return True
        a, b = bool(self.fighters("A")), bool(self.fighters("B"))
        if a and b:
            return False
        self.winner = "A" if a else "B" if b else "draw"
        self.end_reason = "wipe" if self.winner != "draw" else "mutual_wipe"
        return True

    # ================================================================ targeting
    def select(self, u: Unit, sel: str, ctx: dict) -> list[Unit]:
        side = u.side
        enemies = sorted(self.fighters(self.other(side)), key=lambda x: x.pos)
        allies = sorted(self.fighters(side), key=lambda x: x.pos)
        front = set(self.asm.get("formation.front"))
        name, _, arg = sel.partition(":")
        n = int(arg) if arg.isdigit() else 1
        if name == "self":
            return [] if u.is_team_source else [u]
        if name == "same":
            return [t for t in ctx.get("_prev_targets", []) if t.alive]
        if name == "hit":
            return [t for t in ctx.get("_prev_hit", []) if t.alive]
        if name == "attacker":
            a = ctx.get("attacker")
            return [a] if a is not None and a.alive and not a.is_team_source else []
        if name == "actor":
            a = ctx.get("actor")
            return [a] if a is not None and a.alive and not a.is_team_source else []
        if name == "event_target":
            t = ctx.get("target")
            return [t] if t is not None else []
        if name == "link_members":
            return [m for m in (u.link_group or {}).get("members", []) if m.alive]
        if name == "event_hits":
            return [t for t in ctx.get("targets_hit", []) if t.alive]
        if name == "event_subject":
            s_ = ctx.get("subject")
            return [s_] if s_ is not None and s_.alive else []
        if name == "dead_allies_revivable":
            return [x for x in self.fighters(side, alive=False) if not x.revive_banned()]
        if name in ("dead_allies", "dead_ally_random"):
            dead = [x for x in self.fighters(side, alive=False)]
            if name == "dead_ally_random":
                self.rng.shuffle(dead)
            return dead[:n] if arg else dead
        if name.startswith("enemy"):
            pool = enemies
            visible = [e for e in pool if not e.flag("stealth")] or pool      # stealth: not selectable while others are
            taunters = [e for e in visible if any(s.key == "taunt" for s in e.statuses)]
            if name == "enemy_first":
                order = taunters + [e for e in self._single_order(visible) if e not in taunters]
                return order[:n]
            if name == "enemy_without":
                cand = [e for e in visible if not e.has_status(arg)] or visible
                return self._single_order(cand)[:1]
            if name == "enemy_highest_atk_lowest_hp":
                return sorted(visible, key=lambda x: (-x.stat("ATK"), x.hp, x.pos))[:1]
            pool_single = visible
            forced = u.flag("forced_target") if not u.is_team_source else None
            if forced is not None:
                ft = next((e for e in visible if e.uid == forced.flags["forced_target"]), None)
                if ft is not None and name in ("enemy_single", "enemy_lowest_hp", "enemy_highest_atk", "enemy_first"):
                    return [ft]
            if name == "enemy_single":
                if taunters:
                    return [taunters[0]]
                return self._single_order(pool_single)[:1]
            if name == "enemy_all":
                return pool
            if name == "enemy_front":
                return [e for e in pool if e.pos in front] or pool
            if name == "enemy_back":
                return [e for e in pool if e.pos not in front] or pool
            if name == "enemy_random":
                return self.rng.sample(pool_single, min(n, len(pool_single)))
            if name == "enemy_lowest_hp":
                return sorted(pool_single, key=lambda x: (x.hp_frac(), x.pos))[:n]
            if name == "enemy_highest_atk":
                return sorted(pool_single, key=lambda x: (-x.stat("ATK"), x.pos))[:n]
            if name == "enemy_highest_spd":
                return sorted(pool, key=lambda x: (-x.stat("SPD"), x.pos))[:n]
            if name == "enemy_role":
                return [e for e in pool if f"role:{arg}" in e.tags]
            raise ValueError(f"unknown selector {sel}")
        if name.startswith("ally"):
            pool = allies
            if name == "ally_all":
                return pool
            if name == "ally_others":
                return [a for a in pool if a is not u]
            if name == "ally_lowest_hp":
                return sorted(pool, key=lambda x: (x.hp_frac(), x.pos))[:n]
            if name == "ally_random":
                return self.rng.sample(pool, min(n, len(pool)))
            if name == "ally_highest_atk":
                return sorted(pool, key=lambda x: (-x.stat("ATK"), x.pos))[:n]
            if name == "ally_class":
                return [a for a in pool if f"class:{arg}" in a.tags]
            if name == "ally_link":
                others = [a for a in pool if a is not u] or pool
                return sorted(others, key=lambda x: (x.hp_frac(), -x.stat("ATK"), x.pos))[:1]
            if name == "ally_lowest_hp_unshielded":
                return sorted(pool, key=lambda x: (x.shield > 0, x.hp_frac(), x.pos))[:n]
            if name == "ally_highest_atk_with_self":
                best = max(pool, key=lambda x: x.stat("ATK")) if pool else None
                return list(dict.fromkeys([u] + ([best] if best else []))) if not u.is_team_source else ([best] if best else [])
            if name == "ally_front":
                return [a for a in pool if a.pos in front] or pool
            if name == "ally_back":
                return [a for a in pool if a.pos not in front] or pool
            raise ValueError(f"unknown selector {sel}")
        raise ValueError(f"unknown selector {sel}")

    # ================================================================ triggers
    def _relation_ok(self, u: Unit, ab: dict, event: str, ctx: dict) -> bool:
        rel = ab.get("trigger", {}).get("relation") or DEFAULT_RELATION.get(event, "any")
        subject = ctx.get("subject")
        if rel == "any" or subject is None:
            return True
        if rel == "self":
            return subject is u
        if rel == "ally":
            return subject is not u and subject.side == u.side
        if rel == "ally_or_self":
            return subject.side == u.side
        if rel == "enemy":
            return subject.side != u.side
        return False

    def _conditions_ok(self, u: Unit, ab: dict, ctx: dict, consume: bool = True) -> bool:
        t = ab.get("trigger", {})
        aid = ab["id"]
        if u.cooldowns.get(aid, 0) > 0:
            return False
        if "round" in t and self.round != t["round"]:
            return False
        if "round_ge" in t and self.round < t["round_ge"]:
            return False
        if "first_n_rounds" in t and self.round > t["first_n_rounds"]:
            return False
        if "every_n_rounds" in t and (self.round % t["every_n_rounds"]) != 0:
            return False
        if "hp_below" in t and u.hp_frac() >= t["hp_below"]:
            return False
        if "ally_hp_below" in t and not any(a.hp_frac() < t["ally_hp_below"] for a in self.fighters(u.side)):
            return False
        if "dead_ally_ge" in t and len(self.select(u, "dead_allies_revivable", {})) < t["dead_ally_ge"]:
            return False
        for rname, need in (t.get("res_ge") or {}).items():
            if u.res[rname] < need:
                return False
        if "self_has" in t and not u.has_status(t["self_has"]):
            return False
        if "self_not" in t and u.has_status(t["self_not"]):
            return False
        if "ability_id" in t and (ctx.get("ability") or {}).get("id") != t["ability_id"]:
            return False
        if "every_n_casts" in t:
            src_id = (ctx.get("ability") or {}).get("id")
            if not src_id or u.cast_counts[src_id] % int(t["every_n_casts"]) != 0:
                return False
        if "resource" in t and ctx.get("name") != t["resource"]:
            return False
        if "subject_has" in t and (ctx.get("subject") is None or not ctx["subject"].has_status(t["subject_has"])):
            return False
        if t.get("attack_only") and (ctx.get("dot") or ctx.get("attacker") is None or ctx["attacker"].is_team_source):
            return False
        if "dead_ally_lt" in t and len(self.select(u, "dead_allies_revivable", {})) >= t["dead_ally_lt"]:
            return False
        if t.get("subject_linked") and (ctx.get("subject") is None or u.link_group is None
                                        or ctx["subject"] not in u.link_group["members"]):
            return False
        if t.get("per_subject_per_round") is not None and ctx.get("subject") is not None:
            k = (aid, ctx["subject"].uid)
            if u.trig_round[k] >= t["per_subject_per_round"]:
                return False
            if consume:
                u.trig_round[k] += 1
        if "ability_tag" in t:
            src_ab = ctx.get("ability") or {}
            if t["ability_tag"] not in src_ab.get("tags", []):
                return False
        if "dtype" in t and ctx.get("dtype") != t["dtype"]:
            return False
        if t.get("per_round") is not None and u.trig_round[aid] >= t["per_round"]:
            return False
        if t.get("per_battle") is not None and u.trig_battle[aid] >= t["per_battle"]:
            return False
        if "chance" in t and self.rng.random() >= t["chance"]:
            return False
        if consume:
            u.trig_round[aid] += 1
            u.trig_battle[aid] += 1
        return True

    def _event_rank(self, event: str) -> int:
        order = self.asm.get("death.trigger_order")
        if event not in ("kill", "enemy_death", "self_death", "ally_death"):
            return 0
        if order == "by_priority":
            return 0
        killer_side = event in ("kill", "enemy_death")
        if order == "kill_effects_first":
            return 0 if killer_side else 1
        return 1 if killer_side else 0

    def emit(self, event: str, depth: int, **ctx):
        if depth > self.max_depth:
            self._log(t="depth_cap", ev=event)
            return
        rank = self._event_rank(event)
        for u, ab in self.listeners.get(event, ()):
            if not u.alive and not (event == "self_death" and ctx.get("subject") is u) \
                    and not ab.get("trigger", {}).get("while_dead"):
                continue
            if not self._relation_ok(u, ab, event, ctx):
                continue
            if (not u.is_team_source and u.has_control() and depth > 0
                    and not self.asm.get("ctrl.controlled_can_react")
                    and any(e.get("op") in ATTACK_OPS for e in ab.get("effects", []))):
                continue
            if not self._conditions_ok(u, ab, ctx):
                continue
            prio = ab.get("priority", 0) - ab.get("rune_order", 0)
            heapq.heappush(self.q, ((depth, rank, -prio, self.order_index[u.uid], next(self.seq)),
                                    Pending(u, ab, dict(ctx, event=event), depth)))

    def drain(self):
        """Resolve every pending reaction. Victory is checked only once the queue is empty, so
        death reactions (self-revive, revive-ban on kill) always resolve before the battle ends."""
        while self.q and not self.winner:
            _, p = heapq.heappop(self.q)
            if not p.unit.alive and p.kind != "trigger":
                continue
            if p.kind == "trigger":
                if not p.unit.alive and p.ctx.get("event") != "self_death" \
                        and not p.ability.get("trigger", {}).get("while_dead"):
                    continue
                self.execute(p.unit, p.ability, p.ctx, p.depth)
                self._set_cd(p.unit, p.ability)
            else:
                self._run_extra(p)
        self._check_end()

    # ================================================================ effects
    def execute(self, u: Unit, ab: dict, ctx: dict, depth: int):
        ctx = dict(ctx)
        ctx.setdefault("chain", 0)
        st = u.st.by_ability[ab["id"]]
        st["casts"] += 1
        self._log(t="cast", src=u.uid, ab=ab["id"], ev=ctx.get("event", "turn"), d=depth)
        did_attack = False
        hit_any = []
        for eff in ab.get("effects", []):
            if self.winner:
                break
            if "chance" in eff and eff["op"] not in ("status", "extra_attack") and self.rng.random() >= eff["chance"]:
                continue
            op = eff["op"]
            if not self._eff_cond_ok(u, eff.get("cond"), ctx):
                continue
            targets = self.select(u, eff.get("target", "enemy_single" if op == "damage" else "self"), ctx)
            targets = [t for t in targets if self._target_cond_ok(t, eff.get("tcond"))]
            ctx["_prev_targets"] = targets
            if op == "damage":
                did_attack = True
                hit = []
                if eff.get("split_total"):
                    eff = dict(eff, coef=eff.get("coef", 0.0) / max(1, len(targets)))
                for t in targets:
                    for _h in range(int(eff.get("hits", 1))):
                        if not t.alive:
                            break
                        r = self.deal(u, t, eff, ab, depth, ctx)
                        if r and r["hit"]:
                            hit.append(t)
                ctx["_prev_hit"] = hit
                hit_any += hit
            elif op == "heal":
                for t in targets:
                    self.heal(u, t, eff, ab, depth)
            elif op == "shield":
                for t in targets:
                    self.shield(u, t, eff, ab)
            elif op == "status":
                for t in targets:
                    self.apply_status(u, t, eff, ab, depth)
            elif op == "cleanse":
                for t in targets:
                    self.remove_statuses(u, t, "debuff", int(eff.get("count", 1)), ab)
            elif op == "dispel":
                for t in targets:
                    self.remove_statuses(u, t, "buff", int(eff.get("count", 1)), ab)
            elif op == "revive":
                revived = []
                for t in self.select(u, eff.get("target", "dead_ally_random"), ctx)[: int(eff.get("count", 99 if eff.get("target") == "dead_allies_revivable" else 1))]:
                    if self.revive(u, t, eff, ab, depth):
                        revived.append(t)
                ctx["_prev_targets"] = revived
            elif op in ("extra_attack", "extra_action"):
                self.schedule_extra(u, eff, ab, ctx, depth)
            elif op == "remove_status":
                for t in targets:
                    t.statuses = [s_ for s_ in t.statuses if s_.key != eff["key"]]
            elif op == "res_stat":
                for t in (targets or [u]):
                    t.res_stats.append((eff["stat"], eff["name"], eff["per"], eff.get("mode", "flat")))
            elif op == "res_count":
                cnt = {"alive_allies": len(self.fighters(u.side))}.get(eff["count"], 0)
                for t in (targets or [u]):
                    self.change_res(t, eff["name"], set_to=cnt + eff.get("offset", 0), depth=depth)
            elif op == "res":
                for t in (targets or ([u] if not u.is_team_source else [])):
                    self.change_res(t, eff["name"], eff.get("add", 0), eff.get("cap"), eff.get("set"), depth)
            elif op == "drain":
                self.drain_hp(u, targets, eff, ab, depth)
            elif op == "detonate":
                for t in targets:
                    self.detonate(u, t, eff, ab, depth)
            elif op == "barrier":
                self.make_barrier(u, eff, ab, depth)
            elif op == "link":
                for t in targets:
                    self.make_link(u, t, eff, ab, depth)
            elif op == "cast":
                self.schedule_cast(u, eff, ab, ctx, depth)
            elif op == "execute":
                for t in targets:
                    self.execute_kill(u, t, eff, ab, depth)
            elif op == "cooldown":
                for t in targets:
                    for k in list(t.cooldowns):
                        t.cooldowns[k] = max(0, t.cooldowns[k] + int(eff.get("delta", -1)))
            else:
                raise ValueError(f"unknown op {op} in {ab['id']}")
        # nested runes: each rolls independently after the parent rune resolved
        for nest in ab.get("nested", []):
            if self.rng.random() < nest.get("prob", 0):
                self._log(t="nested_rune", src=u.uid, ab=nest.get("id"))
                self.execute(u, {"id": f"{ab['id']}>{nest.get('id', 'nested')}", "effects": nest.get("effects", []),
                                 "tags": ["rune"]}, ctx, depth)
        if did_attack and not self.winner:
            self.emit("after_attack", depth + 1, subject=u, actor=u, ability=ab, targets_hit=hit_any,
                      chain=ctx.get("chain", 0), is_extra=ctx.get("is_extra", False))

    # ---------------------------------------------------------------- damage
    def deal(self, src: Unit, tgt: Unit, spec: dict, ab: dict, depth: int, ctx: dict) -> dict | None:
        a = self.asm
        dtype = spec.get("dtype", "physical")
        if not tgt.alive:
            return None
        can_miss = spec.get("can_dodge", True) and (dtype in ("physical", "magic") or (dtype == "true" and a.get("dmg.true_can_miss")))
        if can_miss and a.get("dmg.hit_formula") == "dodge_minus_acc":
            p_miss = min(1.0, max(0.0, tgt.stat("DODGE") - src.stat("ACC")))
            if p_miss > 0 and self.rng.random() < p_miss:
                src.st.misses += 1
                tgt.st.dodges += 1
                self._log(t="miss", src=src.uid, tgt=tgt.uid, ab=ab["id"])
                self.emit("dodged", depth + 1, subject=tgt, attacker=src, ability=ab)
                return {"hit": False}
        pmh = spec.get("pct_max_hp", 0.0) * tgt.max_hp
        if spec.get("pct_max_hp_cap_atk") is not None:
            pmh = min(pmh, spec["pct_max_hp_cap_atk"] * src.stat("ATK"))
        base = (spec.get("coef", 0.0) * src.stat(spec.get("stat", "ATK")) + spec.get("flat", 0.0)
                + pmh + spec.get("pct_cur_hp", 0.0) * tgt.hp + spec.get("pct_self_max_hp", 0.0) * src.max_hp)
        if spec.get("per_res"):
            r = spec["per_res"]
            base += r.get("pct_self_max_hp", 0.0) * src.max_hp * tgt.status_stacks(r["status"]) if "status" in r else 0.0
        if spec.get("cap_atk_mult") is not None:
            base = min(base, spec["cap_atk_mult"] * src.stat("ATK"))
        if "amount" in spec:
            base += spec["amount"]
        crit = False
        if dtype in ("physical", "magic"):
            def_stat = "DEF" if dtype == "physical" else a.get("dmg.magic_def_stat")
            D = tgt.stat(def_stat) if def_stat != "none" else 0.0
            ign_res = 0.0
            if spec.get("ignore_def_per_res"):
                r = spec["ignore_def_per_res"]
                ign_res = src.res[r["name"]] * r["per"]
            ign = min(1.0, max(0.0, src.stat("IGNORE_DEF") + spec.get("ignore_def", 0.0) + ign_res))
            D_eff = D * (1 - ign)
            fam = a.get("dmg.family")
            if fam == "divisive":
                k = float(a.get("dmg.k_def"))
                dmg = base * k / (k + D_eff)
            elif fam == "ratio":
                dmg = base * base / (base + D_eff) if base > 0 else 0.0
            elif fam == "subtractive":
                dmg = base - float(a.get("dmg.sub_c")) * D_eff
            else:
                raise ValueError(fam)
            dmg = max(dmg, base * float(a.get("dmg.min_fraction")))
            bonuses = [src.stat("DMG_BONUS"), src.stat("PHYS_DMG_BONUS" if dtype == "physical" else "MAGIC_DMG_BONUS"),
                       spec.get("bonus", 0.0)]
            for key, b in spec.get("bonus_vs_status", {}).items():
                if any(s.key == key for s in tgt.statuses):
                    bonuses.append(b)
            if spec.get("bonus_per_debuff"):
                bp = spec["bonus_per_debuff"]
                bonuses.append(min(bp.get("cap", 1.0), bp["per"] * tgt.debuff_stacks()))
            ramp = src.flag("ramp_missing_hp")
            if ramp is not None:
                bonuses.append(ramp.flags["ramp_missing_hp"] * int((1 - tgt.hp_frac()) * 10 + 1e-9))
            if spec.get("bonus_if_target_hp_ge"):
                bh = spec["bonus_if_target_hp_ge"]
                if tgt.hp_frac() >= bh["thr"]:
                    bonuses.append(bh["bonus"])
            if a.get("dmg.bonus_stacking") == "additive":
                dmg *= max(0.0, 1 + sum(bonuses))
            else:
                for b in bonuses:
                    dmg *= max(0.0, 1 + b)
            crit, dmg = self._crit(src, tgt, spec, dmg)
            typed_dr = tgt.stat("MAGIC_DR") if dtype == "magic" else tgt.stat("PHYS_DR")
            dmg *= 1 - min(max(0.0, tgt.stat("DR") + typed_dr), float(a.get("dmg.dr_cap")))
        elif dtype == "true":
            dmg = base
            bh = spec.get("bonus_if_target_hp_ge")       # explicit skill-text bonus still applies to true damage
            if bh and tgt.hp_frac() >= bh["thr"]:
                dmg *= 1 + bh["bonus"]
            if a.get("dmg.true_can_crit"):
                crit, dmg = self._crit(src, tgt, spec, dmg)
        elif dtype == "fixed":
            dmg = base
        else:
            raise ValueError(f"unknown dtype {dtype}")
        if dtype != "fixed":
            dmg *= max(0.0, 1 + tgt.stat("DMG_TAKEN"))
        v = float(a.get("dmg.variance"))
        if v > 0:
            dmg *= 1 + self.rng.uniform(-v, v)
        out = self.apply_damage(src, tgt, max(0.0, dmg), dtype, ab, depth, crit=crit)
        out["hit"] = True
        return out

    def _crit(self, src, tgt, spec, dmg):
        if not spec.get("can_crit", True):
            return False, dmg
        p = src.stat("CRIT")
        if self.asm.get("dmg.crit_formula") == "crit_minus_crit_res":
            p -= tgt.stat("CRIT_RES")
        if p > 0 and self.rng.random() < p:
            mult = src.stat("CRIT_DMG") or float(self.asm.get("dmg.base_crit_dmg"))
            src.st.crits += 1
            return True, dmg * mult
        return False, dmg

    def apply_damage(self, src: Unit, tgt: Unit, dmg: float, dtype: str, ab: dict, depth: int,
                     crit: bool = False, reflected: bool = False, dot: bool = False) -> dict:
        raw = dmg
        absorbed = 0.0
        blk = tgt.flag("block_hits") if not dot and dmg > 0 else None
        if blk is not None:
            blk.flags["block_hits"] -= 1
            if blk.flags["block_hits"] <= 0:
                tgt.statuses.remove(blk)
            self._log(t="blocked", src=src.uid, tgt=tgt.uid, ab=ab["id"], v=round(dmg, 2))
            return {"raw": raw, "hp": 0.0, "absorbed": dmg, "crit": crit, "blocked": True}
        bar = self.barriers.get(tgt.side)
        if bar and bar["amount"] > 0 and dmg > 0 and tgt is not None and not tgt.is_team_source:
            take = min(dmg * bar["share"], bar["amount"])
            bar["amount"] -= take
            dmg -= take
            absorbed += take
            bar["owner"].st.by_ability[bar["ability"]]["shield_absorbed"] += take
            if bar["amount"] <= 1e-9:
                self.collapse_barrier(tgt.side, depth)
        frz = next((s for s in tgt.statuses if s.flags.get("freeze_break_hits")), None)
        if frz is not None and not dot:
            frz.flags["hits"] = frz.flags.get("hits", 0) + 1
            if frz.flags["hits"] >= frz.flags["freeze_break_hits"]:
                tgt.statuses.remove(frz)
                self._log(t="freeze_broken", tgt=tgt.uid)
        if tgt.shields() and (dtype in ("physical", "magic") or self.asm.get("shield.absorbs_true")):
            for sh in sorted(tgt.shields(), key=lambda s: s.seq):
                take = min(sh.shield_amount, dmg)
                sh.shield_amount -= take
                dmg -= take
                absorbed += take
                if sh.shield_amount <= 1e-9:
                    tgt.statuses.remove(sh)
                    self.emit("shield_broken", depth + 1, subject=tgt, attacker=src)
                if dmg <= 0:
                    break
        if tgt.link_group and dmg > 0 and not dot:
            mates = [m for m in tgt.link_group["members"] if m.alive and m is not tgt]
            if mates:                                   # link.share: damage split equally (assumption)
                part = dmg / (len(mates) + 1)
                dmg = part
                for m in mates:
                    self._raw_hp_loss(src, m, part, ab, depth)
        hp_loss = min(dmg, tgt.hp)
        overkill = dmg - hp_loss
        if hp_loss >= tgt.hp - 1e-9 and self._try_fatal_save(tgt, src, depth):
            hp_loss = 0.0
            overkill = 0.0
        tgt.hp -= hp_loss
        s = src.st
        s.dmg_raw += raw
        s.dmg_effective += hp_loss
        s.dmg_to_shield += absorbed
        s.overkill += overkill
        tgt.st.dmg_taken_hp += hp_loss
        tgt.st.dmg_absorbed_by_own_shield += absorbed
        s.by_ability[ab["id"]]["dmg"] += hp_loss
        s.by_ability[ab["id"]]["dmg_to_shield"] += absorbed
        if src.side != tgt.side:
            self.round_damage[src.side][self.round] += hp_loss + absorbed
            if self.round == 1:
                self.first_round["damage"][src.side] += hp_loss + absorbed
        self._log(t="dmg", src=src.uid, tgt=tgt.uid, ab=ab["id"], dt=dtype, raw=round(raw, 2),
                  hp=round(hp_loss, 2), sh=round(absorbed, 2), crit=crit, refl=reflected, dot=dot)
        # lifesteal
        ls = src.stat("LIFESTEAL") if not reflected and not dot and not src.is_team_source else 0.0
        if ls > 0 and src.alive:
            self.heal_amount(src, src, (hp_loss + absorbed) * ls, {"id": "lifesteal"}, depth)
        # reflect
        rp = tgt.reflect_pct()
        if rp > 0 and not reflected and not dot and src.alive and not src.is_team_source and (hp_loss + absorbed) > 0:
            amount = (hp_loss + absorbed) * rp
            rtype = "true" if self.asm.get("reflect.dtype") == "true" else dtype
            tgt.st.reflected += amount
            self.apply_damage(tgt, src, amount, rtype, {"id": "reflect"}, depth + 1, reflected=True)
        if (hp_loss + absorbed) > 0 and (not reflected or self.asm.get("reflect.triggers_on_hit")):
            self.emit("damaged", depth + 1, subject=tgt, attacker=src, target=tgt, ability=ab, dtype=dtype,
                      amount=hp_loss + absorbed, dot=dot)
            if crit:
                self.emit("crit", depth + 1, subject=src, actor=src, target=tgt, ability=ab)
        if tgt.hp <= 1e-9 and tgt.alive:
            self.kill(tgt, src, ab, dtype, overkill, depth)
        return {"raw": raw, "hp": hp_loss, "absorbed": absorbed, "crit": crit}

    def kill(self, tgt: Unit, killer: Unit, ab: dict, dtype: str, overkill: float, depth: int):
        tgt.alive = False
        tgt.hp = 0.0
        tgt.st.deaths += 1
        if killer.side != tgt.side:
            killer.st.kills += 1
        rec = {"round": self.round, "uid": tgt.uid, "hero": tgt.hero_id, "killer": killer.uid,
               "killer_hero": killer.hero_id, "ability": ab["id"], "dtype": dtype, "overkill": round(overkill, 2)}
        self.deaths.append(rec)
        if self.round == 1:
            self.first_round["deaths"].append(tgt.uid)
        self._log(t="death", **{k: v for k, v in rec.items() if k != "round"})
        if self.asm.get("death.clear_statuses"):
            tgt.statuses = [s for s in tgt.statuses if s.persist_on_death]
        self.emit("kill", depth + 1, subject=killer, actor=killer, target=tgt, ability=ab)
        self.emit("enemy_death", depth + 1, subject=tgt, target=tgt, killer=killer)
        self.emit("self_death", depth + 1, subject=tgt, target=tgt, killer=killer)
        self.emit("ally_death", depth + 1, subject=tgt, target=tgt, killer=killer)

    # ---------------------------------------------------------------- heal / shield
    def heal(self, src: Unit, tgt: Unit, spec: dict, ab: dict, depth: int):
        if not tgt.alive:
            return
        amount = (spec.get("coef", 0.0) * src.stat(spec.get("stat", "ATK")) + spec.get("pct_max_hp", 0.0) * tgt.max_hp
                  + spec.get("flat", 0.0) + spec.get("pct_self_max_hp", 0.0) * src.max_hp)
        self.heal_amount(src, tgt, amount, ab, depth)

    def heal_amount(self, src: Unit, tgt: Unit, amount: float, ab: dict, depth: int):
        if not tgt.alive or amount <= 0:
            return
        amount *= (1 + src.stat("HEAL_BONUS")) * (1 + tgt.stat("HEAL_RECV"))
        amount = max(0.0, amount)
        eff = min(amount, tgt.max_hp - tgt.hp)
        tgt.hp += eff
        src.st.heal_effective += eff
        src.st.overheal += amount - eff
        src.st.by_ability[ab["id"]]["heal"] += eff
        self._log(t="heal", src=src.uid, tgt=tgt.uid, ab=ab["id"], v=round(eff, 2), over=round(amount - eff, 2))
        if eff > 0:
            self.emit("healed", depth + 1, subject=tgt, actor=src, amount=eff)

    def shield(self, src: Unit, tgt: Unit, spec: dict, ab: dict):
        if not tgt.alive:
            return
        amount = (spec.get("coef", 0.0) * src.stat(spec.get("stat", "ATK")) + spec.get("pct_max_hp", 0.0) * tgt.max_hp
                  + spec.get("flat", 0.0))
        key = spec.get("key", f"shield:{ab['id']}")
        existing = next((s for s in tgt.statuses if s.key == key), None)
        if existing and spec.get("stacking", "refresh") == "refresh":
            existing.shield_amount = max(existing.shield_amount, amount)
            existing.duration = spec.get("duration")
        else:
            tgt.statuses.append(Status(key=key, kind="buff", source=src.uid, shield_amount=amount,
                                       duration=spec.get("duration"), seq=self._next_sseq(), ability=ab["id"],
                                       undispellable=spec.get("undispellable", False)))
        src.st.shield_given += amount
        src.st.by_ability[ab["id"]]["shield"] += amount
        self._log(t="shield", src=src.uid, tgt=tgt.uid, ab=ab["id"], v=round(amount, 2))

    # ---------------------------------------------------------------- statuses
    def apply_status(self, src: Unit, tgt: Unit, eff: dict, ab: dict, depth: int):
        spec = dict(eff["status"])
        if not tgt.alive and not (spec.get("revive_ban") or spec.get("persist_on_death")):
            return
        chance = eff.get("chance", 1.0)
        if spec.get("kind", "debuff") == "debuff" and tgt.flag("immune_debuff") and src.side != tgt.side:
            self._log(t="immune", tgt=tgt.uid, key=spec.get("key"))
            return
        if spec.get("control"):
            src.st.ctrl_attempts += 1
            if any(s.key == "control_immune" for s in tgt.statuses) or tgt.flag("immune_control"):
                p = 0.0
            else:
                p = chance * (1 + src.stat("CTRL_HIT") - tgt.stat("CTRL_RES"))
            p = min(1.0, max(0.0, p))
            if self.rng.random() >= p:
                src.st.ctrl_resisted += 1
                self._log(t="ctrl_resist", src=src.uid, tgt=tgt.uid, ab=ab["id"], c=spec["control"])
                return
            src.st.ctrl_landed += 1
            if self.round == 1:
                self.first_round["controls"] += 1
        elif chance < 1.0 and self.rng.random() >= chance:
            return
        key = spec["key"]
        policy = spec.get("stacking") or self.asm.get("stack.same_status_default")
        existing = [s for s in tgt.statuses if s.key == key]
        dot = spec.get("dot")
        if dot and self.asm.get("dot.snapshot"):
            dot = dict(dot, snap=src.stat(dot.get("stat", "ATK")))
        new = Status(key=key, kind=spec.get("kind", "debuff"), source=src.uid, mods=spec.get("mods", []),
                     duration=spec.get("duration"), max_stacks=spec.get("max_stacks", 1), stacking=policy,
                     control=spec.get("control"), dot=dot, hot=spec.get("hot"), revive_ban=spec.get("revive_ban", False),
                     reflect=spec.get("reflect", 0.0), undispellable=spec.get("undispellable", False),
                     persist_on_death=spec.get("persist_on_death", spec.get("revive_ban", False)),
                     tick=spec.get("tick"), seq=self._next_sseq(), ability=ab["id"],
                     flags={k: spec[k] for k in ("stealth", "immune_debuff", "immune_control", "block_hits",
                                                 "freeze_break_hits", "dot_timing", "ramp_missing_hp", "dot_on_expire")
                            if k in spec} | ({"forced_target": src.uid} if spec.get("provoke") else {}))
        if existing and policy == "refresh":
            ex = existing[0]
            ex.duration = new.duration if new.duration is None or ex.duration is None else max(ex.duration, new.duration)
            ex.mods, ex.source = new.mods, new.source
        elif existing and policy == "stack":
            ex = existing[0]
            ex.stacks = min(ex.stacks + 1, max(ex.max_stacks, new.max_stacks))
            ex.duration = new.duration
        else:
            tgt.statuses.append(new)
        self._log(t="status", src=src.uid, tgt=tgt.uid, ab=ab["id"], key=key, ctrl=spec.get("control"))
        if spec.get("control"):
            self.emit("controlled", depth + 1, subject=tgt, actor=src, control=spec["control"])
        self.emit("status_applied", depth + 1, subject=tgt, actor=src, key=key)

    def remove_statuses(self, src: Unit, tgt: Unit, kind: str, count: int, ab: dict):
        cands = [s for s in tgt.statuses if s.kind == kind and not s.undispellable]
        cands.sort(key=lambda s: -s.seq)          # newest first
        for s in cands[:count]:
            tgt.statuses.remove(s)
            if kind == "debuff":
                src.st.cleansed += 1
            else:
                src.st.dispelled += 1
            self._log(t="cleanse" if kind == "debuff" else "dispel", src=src.uid, tgt=tgt.uid, key=s.key, ab=ab["id"])

    def revive(self, src: Unit, tgt: Unit, eff: dict, ab: dict, depth: int):
        if tgt.alive or tgt.is_team_source:
            return False
        if tgt.revive_banned() and not eff.get("ignore_revive_ban"):
            tgt.st.revive_blocked += 1
            self._log(t="revive_blocked", src=src.uid, tgt=tgt.uid, ab=ab["id"])
            return False
        tgt.alive = True
        tgt.hp = max(1.0, tgt.max_hp * eff.get("hp_pct", 0.3))
        if self.asm.get("revive.cleanse_on_revive"):
            tgt.statuses = []
        tgt.st.revived_times += 1
        src.st.revives_done += 1
        rr = self.asm.get("cd.reset_on_revive")
        if rr == "clear":
            tgt.cooldowns = {}
        elif rr == "reset_to_initial":
            tgt.cooldowns = {}
            for a_ in tgt.abilities:
                c0 = a_.get("trigger", {}).get("initial_cooldown")
                if c0:
                    tgt.cooldowns[a_["id"]] = int(c0)
        if not self.asm.get("revive.can_act_same_round"):
            tgt.tags.add("_revived_this_round")
        if eff.get("hp_atk_pct"):
            tgt.hp = min(tgt.max_hp, max(1.0, eff["hp_atk_pct"] * src.stat("ATK")))
        self._log(t="revive", src=src.uid, tgt=tgt.uid, ab=ab["id"], hp=round(tgt.hp, 2))
        for g in eff.get("grant", []):
            self.apply_status(src, tgt, {"status": g}, ab, depth)
        self.emit("revived", depth + 1, subject=tgt, actor=src)
        return True

    # ---------------------------------------------------------------- extra actions / combo
    def schedule_extra(self, u: Unit, eff: dict, ab: dict, ctx: dict, depth: int):
        chain = ctx.get("chain", 0) if ctx.get("is_extra") else 0
        if eff["op"] == "extra_attack" and ctx.get("is_extra"):
            if chain > int(self.asm.get("extra.combo_chain_max")):
                self._log(t="combo_chain_cap", src=u.uid, ab=ab["id"])
                return
        if "chance" in eff and self.rng.random() >= eff["chance"]:
            return
        actor = u
        if eff.get("actor") == "event_actor" and ctx.get("actor") is not None:
            actor = ctx["actor"]
        if actor.is_team_source or not actor.alive:
            return
        if actor.extra_this_round >= int(self.asm.get("extra.per_unit_per_round_max")):
            self._log(t="extra_cap", src=actor.uid)
            return
        actor.extra_this_round += 1
        p = Pending(actor, {"id": eff.get("ability", "basic"), "by": ab["id"]},
                    {"chain": chain + 1, "is_extra": True, "parent": ab["id"], "target_hint": eff.get("target")},
                    depth + 1, kind=eff["op"])
        timing = self.asm.get("extra.timing")
        if eff["op"] == "extra_attack":
            actor.st.combo_triggers += 1
        if timing == "immediate":
            heapq.heappush(self.q, ((depth + 1, 0, -100, self.order_index[actor.uid], next(self.seq)), p))
        else:
            self.eor_extras.append(p)
        self._log(t="extra_scheduled", src=actor.uid, kind=eff["op"], by=ab["id"], timing=timing)

    def _run_extra(self, p: Pending):
        u = p.unit
        if not u.alive or (u.has_control() and not p.ctx.get("ignore_control")):
            return
        u.st.extra_actions += 1
        if p.kind == "cast":
            ab = next((a for a in u.abilities if a["id"] == p.ability["id"]), None)
            if ab is None:
                return
            self.execute(u, ab, dict(p.ctx, event="extra_cast"), 0)
            if self.asm.get("cd.extra_cast_sets_cd"):
                self._set_cd(u, ab)
            self.after_cast(u, ab, 1)
            return
        if p.kind == "extra_action":
            ab = self.choose_ability(u)
        else:
            want = p.ability["id"]
            ab = self.basic(u) if want == "basic" else next((a for a in u.abilities if a["id"] == want), None)
        if ab is None:
            return
        # an out-of-queue action is a new action: its reactions start at depth 0 again;
        # loops are bounded by extra.combo_chain_max and extra.per_unit_per_round_max instead
        self.execute(u, ab, dict(p.ctx), 0)
        self.emit("action", 1, subject=u, actor=u, ability=ab, is_extra=True, chain=p.ctx.get("chain", 1))

    # ---------------------------------------------------------------- turns
    @staticmethod
    def basic(u: Unit) -> dict | None:
        return next((a for a in u.abilities if a.get("kind") == "basic"), None)

    def choose_ability(self, u: Unit) -> dict | None:
        silenced = u.has_control(CONTROL_SILENCE)
        if not silenced:
            actives = [a for a in u.abilities if a.get("kind") == "active" and a.get("trigger", {}).get("on", "turn") == "turn"]
            if self.asm.get("cd.priority") == "longer_ct_first":
                actives.sort(key=lambda a: (-(a.get("trigger", {}).get("ct") or 0), -a.get("priority", 0)))
            else:
                actives.sort(key=lambda a: -a.get("priority", 0))
            for a in actives:
                if self._conditions_ok(u, a, {}, consume=True):
                    return a
        return self.basic(u)

    def take_turn(self, u: Unit):
        if not u.alive:
            return
        if "_revived_this_round" in u.tags:
            return
        self.tick_periodic(u, "owner_turn_start")
        if not u.alive or self._check_end():
            return
        self.emit("turn_start", 0, subject=u)
        self.drain()
        if not u.alive or self.winner:
            return
        self._cd_fresh = set()
        turn_mark = self._sseq
        c = u.has_control()
        if c:
            u.st.skipped_turns += 1
            u.st.turns_controlled += 1
            self._log(t="skip", src=u.uid, c=c)
        else:
            self.emit("action_start", 0, subject=u)
            self.drain()
            ab = self.choose_ability(u) if u.alive and not self.winner else None
            if ab is not None:
                u.st.actions += 1
                self.execute(u, ab, {"chain": 0}, 0)
                self._set_cd(u, ab)
                self.after_cast(u, ab, 1)
                if not self.winner:
                    self.emit("action", 1, subject=u, actor=u, ability=ab, is_extra=False, chain=0)
        self.drain()
        # cooldown.tick: decrement at the owner's turn end, except cooldowns set during this turn
        if self.asm.get("cd.clock") == "own_turn" and (not c or self.asm.get("cd.tick_while_controlled")):
            self._tick_cd(u)
        self._cd_fresh = set()
        self.tick_statuses(u, "owner_turn_end", applied_before=turn_mark)

    def tick_periodic(self, u: Unit, phase: str | None = None):
        default = self.asm.get("dot.timing")
        for s in list(u.statuses):
            if not u.alive:
                break
            if phase is not None and (s.flags.get("dot_timing") or default) != phase:
                continue
            if s.flags.get("dot_on_expire"):
                continue
            if s.dot:
                srcu = next((x for x in self.units if x.uid == s.source), u)
                d = s.dot
                base = (d.get("snap", srcu.stat(d.get("stat", "ATK"))) * d.get("coef", 0.0) + d.get("pct_max_hp", 0.0) * u.max_hp
                        + d.get("pct_src_max_hp", 0.0) * srcu.max_hp)
                if d.get("cap_src_atk_mult") is not None:
                    base = min(base, d["cap_src_atk_mult"] * srcu.stat("ATK"))
                if d.get("cap_src_max_hp_pct") is not None:
                    base = min(base, d["cap_src_max_hp_pct"] * srcu.max_hp)
                base *= s.stacks if s.stacking == "stack" else 1
                base *= max(0.0, 1 + srcu.stat("DOT_BONUS") + sum(b for k, b in d.get("bonus_vs_status", {}).items() if u.has_status(k)))
                base *= max(0.0, 1 - u.stat("DOT_TAKEN_RED"))
                dtype = d.get("dtype", "true")
                if dtype in ("physical", "magic"):
                    self.deal(srcu, u, {"coef": 0, "amount": base, "dtype": dtype, "can_crit": False, "can_dodge": False},
                              {"id": s.ability or s.key}, 0, {})
                else:
                    self.apply_damage(srcu, u, base, dtype, {"id": s.ability or s.key}, 0, dot=True)
            if s.hot and u.alive:
                srcu = next((x for x in self.units if x.uid == s.source), u)
                h = s.hot
                amt = srcu.stat(h.get("stat", "ATK")) * h.get("coef", 0.0) + h.get("pct_max_hp", 0.0) * u.max_hp
                self.heal_amount(srcu, u, amt, {"id": s.ability or s.key}, 0)
        self.drain()

    def tick_statuses(self, u: Unit, phase: str, applied_before: int | None = None):
        """Decrement durations. On the owner's turn end, statuses applied during that same turn are
        not decremented (duration N = N full owner turns)."""
        default = self.asm.get("status.tick")
        keep = []
        for s in u.statuses:
            tick = s.tick or default
            fresh = applied_before is not None and s.seq > applied_before
            if s.duration is not None and tick == phase and not fresh:
                s.duration -= 1
                if s.duration <= 0:
                    self._log(t="expire", tgt=u.uid, key=s.key)
                    if s.flags.get("dot_on_expire") and s.dot and u.alive:
                        self.detonate(u, u, {"keys": [s.key], "factor": 1.0}, {"id": s.ability or s.key}, 0)
                    continue
            keep.append(s)
        u.statuses = keep

    # ================================================================ v2 mechanics
    def _single_order(self, pool: list[Unit]) -> list[Unit]:
        """Order for single-target picks (target.default_single); taunt is handled by callers."""
        mode = self.asm.get("target.default_single")
        front = set(self.asm.get("formation.front"))
        if mode == "lowest_hp":
            return sorted(pool, key=lambda x: (x.hp_frac(), x.pos))
        if mode == "random":
            p = list(pool)
            self.rng.shuffle(p)
            return p
        fr = sorted([e for e in pool if e.pos in front], key=lambda x: x.pos)
        bk = sorted([e for e in pool if e.pos not in front], key=lambda x: x.pos)
        if mode == "front_first_random":
            self.rng.shuffle(fr)
            self.rng.shuffle(bk)
        return fr + bk

    def _eff_cond_ok(self, u: Unit, c: dict | None, ctx: dict) -> bool:
        if not c:
            return True
        if "self_has" in c and not u.has_status(c["self_has"]):
            return False
        if "self_not" in c and u.has_status(c["self_not"]):
            return False
        for k, v in (c.get("res_ge") or {}).items():
            if u.res[k] < v:
                return False
        for k, v in (c.get("res_lt") or {}).items():
            if u.res[k] >= v:
                return False
        if "dead_ally_ge" in c and len(self.select(u, "dead_allies_revivable", {})) < c["dead_ally_ge"]:
            return False
        if "dead_ally_lt" in c and len(self.select(u, "dead_allies_revivable", {})) >= c["dead_ally_lt"]:
            return False
        if c.get("prev_nonempty") and not ctx.get("_prev_targets"):
            return False
        if "chance" in c and self.rng.random() >= c["chance"]:
            return False
        return True

    @staticmethod
    def _target_cond_ok(t: Unit, c: dict | None) -> bool:
        if not c:
            return True
        if "has" in c and not t.has_status(c["has"]):
            return False
        if "not" in c and t.has_status(c["not"]):
            return False
        if "hp_ge" in c and t.hp_frac() < c["hp_ge"]:
            return False
        if "hp_lt" in c and t.hp_frac() >= c["hp_lt"]:
            return False
        if "stacks_ge" in c and t.status_stacks(c["stacks_ge"][0]) < c["stacks_ge"][1]:
            return False
        return True

    def change_res(self, t: Unit, name: str, add: float = 0, cap: float | None = None, set_to: float | None = None,
                   depth: int = 0):
        before = t.res[name]
        val = set_to if set_to is not None else before + add
        if cap is not None:
            val = min(val, cap)
        t.res[name] = max(0.0, val)
        self._log(t="res", tgt=t.uid, name=name, v=t.res[name])
        if t.res[name] != before:
            self.emit("resource", depth + 1, subject=t, name=name, value=t.res[name])

    def after_cast(self, u: Unit, ab: dict, depth: int):
        u.cast_counts[ab["id"]] += 1
        if not self.winner:
            self.emit("cast", depth, subject=u, actor=u, ability=ab)

    def schedule_cast(self, u: Unit, eff: dict, ab: dict, ctx: dict, depth: int):
        actor = u if not u.is_team_source else None
        if actor is None or not actor.alive:
            return
        p = Pending(actor, {"id": eff["ability"], "by": ab["id"]},
                    {"chain": 0, "is_extra": True, "ignore_control": eff.get("ignore_control", False), "parent": ab["id"]},
                    depth + 1, kind="cast")
        actor.st.extra_actions += 1
        heapq.heappush(self.q, ((depth + 1, 0, -90, self.order_index[actor.uid], next(self.seq)), p))
        self._log(t="cast_scheduled", src=actor.uid, ab=eff["ability"], by=ab["id"])

    def _raw_hp_loss(self, src: Unit, tgt: Unit, amount: float, ab: dict, depth: int):
        if not tgt.alive or amount <= 0:
            return
        loss = min(amount, tgt.hp)
        if loss >= tgt.hp - 1e-9 and self._try_fatal_save(tgt, src, depth):
            return
        tgt.hp -= loss
        tgt.st.dmg_taken_hp += loss
        src.st.dmg_effective += loss
        src.st.by_ability[ab["id"]]["dmg"] += loss
        self._log(t="dmg_shared", src=src.uid, tgt=tgt.uid, ab=ab["id"], hp=round(loss, 2))
        if tgt.hp <= 1e-9:
            self.kill(tgt, src, ab, "shared", amount - loss, depth)

    def _try_fatal_save(self, tgt: Unit, src: Unit, depth: int) -> bool:
        """'When receiving fatal damage' passives resolve synchronously, before death."""
        for u, ab in self.fatal_listeners:
            if u is not tgt or not self._conditions_ok(u, ab, {"subject": tgt, "attacker": src}):
                continue
            self._log(t="fatal_save", tgt=tgt.uid, ab=ab["id"])
            tgt.hp = max(1.0, tgt.hp)
            self.execute(u, ab, {"subject": tgt, "attacker": src, "event": "fatal"}, depth + 1)
            return True
        return False

    def drain_hp(self, u: Unit, targets: list[Unit], eff: dict, ab: dict, depth: int):
        cap_scope = self.asm.get("drain.cap_scope")
        cap = eff.get("cap_atk_mult", 1e18) * u.stat("ATK")
        total = 0.0
        for t in targets:
            amt = eff.get("pct_cur_hp", 0.0) * t.hp
            if cap_scope == "per_target":
                amt = min(amt, cap)
            res = self.apply_damage(u, t, amt, "true", ab, depth)
            total += res.get("hp", 0.0) + res.get("absorbed", 0.0)
        if cap_scope == "total":
            total = min(total, cap)
        recv = self.select(u, eff.get("heal_target", "ally_lowest_hp:3"), {})
        if not recv:
            return
        each = total / len(recv)
        for r in recv:
            missing = r.max_hp - r.hp
            self.heal_amount(u, r, each, ab, depth)
            over = max(0.0, each - missing)
            if over > 0 and eff.get("overflow_shield"):
                self.shield(u, r, {"flat": over, "key": eff["overflow_shield"], "duration": eff.get("shield_duration")}, ab)

    def detonate(self, u: Unit, t: Unit, eff: dict, ab: dict, depth: int):
        keys = set(eff.get("keys", []))
        factor = eff.get("factor", 1.0)
        for s in list(t.statuses):
            if not s.dot or (keys and s.key not in keys) or not t.alive:
                continue
            srcu = next((x for x in self.units if x.uid == s.source), u)
            d = s.dot
            base = (srcu.stat(d.get("stat", "ATK")) * d.get("coef", 0.0) + d.get("pct_max_hp", 0.0) * t.max_hp
                    + d.get("pct_src_max_hp", 0.0) * srcu.max_hp)
            if d.get("cap_src_atk_mult") is not None:
                base = min(base, d["cap_src_atk_mult"] * srcu.stat("ATK"))
            base *= s.stacks if s.stacking == "stack" else 1
            base *= max(0.0, 1 + srcu.stat("DOT_BONUS")) * factor
            self._log(t="detonate", src=u.uid, tgt=t.uid, key=s.key)
            self.apply_damage(srcu, t, base, d.get("dtype", "true"), {"id": ab["id"]}, depth, dot=True)
            if eff.get("consume"):
                if s in t.statuses:
                    t.statuses.remove(s)

    def make_barrier(self, u: Unit, eff: dict, ab: dict, depth: int):
        old = self.barriers.get(u.side)
        if old and old["amount"] > 0:
            self.collapse_barrier(u.side, depth)          # re-cast overwrites: old barrier collapses
        amount = eff.get("pct_max_hp", 0.0) * u.max_hp
        self.barriers[u.side] = {"amount": amount, "total": amount, "share": eff.get("share", 0.5), "owner": u,
                                 "ability": ab["id"], "collapse": eff.get("collapse")}
        u.st.shield_given += amount
        u.st.by_ability[ab["id"]]["shield"] += amount
        self._log(t="barrier", src=u.uid, v=round(amount, 2))

    def collapse_barrier(self, side: str, depth: int):
        bar = self.barriers.pop(side, None)
        if not bar or not bar.get("collapse"):
            return
        c = bar["collapse"]
        owner = bar["owner"]
        amount = c.get("pct_of_total", 0.0) * bar["total"]
        self._log(t="barrier_collapse", src=owner.uid, v=round(amount, 2))
        for t in self.select(owner, c.get("target", "enemy_first:3"), {}):
            self.apply_damage(owner, t, amount, c.get("dtype", "true"), {"id": bar["ability"] + ":collapse"}, depth + 1)

    def make_link(self, u: Unit, t: Unit, eff: dict, ab: dict, depth: int):
        grp = u.link_group or {"members": [u], "owner": u}
        if eff.get("reset") and len(grp["members"]) > 1:
            for m in grp["members"]:
                if m is not u:
                    m.link_group = None
            grp = {"members": [u], "owner": u}
        if t not in grp["members"]:
            grp["members"].append(t)
        for m in grp["members"]:
            m.link_group = grp
        if eff.get("status"):
            for m in grp["members"]:
                self.apply_status(u, m, {"status": eff["status"]}, ab, depth)
        self._log(t="link", src=u.uid, members=[m.uid for m in grp["members"]])

    def execute_kill(self, u: Unit, t: Unit, eff: dict, ab: dict, depth: int):
        if not t.alive or t.hp_frac() >= eff.get("thr", 0.0):
            return
        if eff.get("mode") == "kill":
            amount = t.hp
        else:                                             # 'threshold': remove thr*maxHP, capped
            amount = min(eff["thr"] * t.max_hp, eff.get("cap_atk_mult", 1e18) * u.stat("ATK"))
        self._log(t="execute", src=u.uid, tgt=t.uid, v=round(amount, 2))
        self.apply_damage(u, t, amount, "true", ab, depth)
        if not t.alive:
            for g in eff.get("on_kill_status", []):
                self.apply_status(u, t, {"status": g}, ab, depth)

    def action_order(self) -> list[Unit]:
        mode = self.asm.get("order.mode")
        alive = self.fighters()
        if mode == "fixed_position":
            return sorted(alive, key=lambda u: (u.pos, u.side))
        ties = self.asm.get("order.tie_break")
        rnd = {u.uid: self.rng.random() for u in alive}

        def key(u):
            k = [-u.stat("SPD")]
            for t in ties:
                if t == "attacker_first":
                    k.append(0 if u.side == "A" else 1)
                elif t == "defender_first":
                    k.append(0 if u.side == "B" else 1)
                elif t == "position":
                    k.append(u.pos)
                elif t == "random":
                    k.append(rnd[u.uid])
                elif t == "base_spd":
                    k.append(-float(u.stats.get("SPD", 0)))
            k.append(self.order_index[u.uid])
            return tuple(k)

        return sorted(alive, key=key)

    # ================================================================ main loop
    def run(self) -> BattleResult:
        self.round = 0
        self.emit("battle_start", 0, subject=None)
        self.drain()
        max_rounds = int(self.asm.get("battle.max_rounds"))
        pet_timing = self.asm.get("pet.timing")
        while not self._check_end():
            self.round += 1
            if self.round > max_rounds:
                self.round = max_rounds
                self._timeout()
                break
            for u in self.units:
                u.trig_round.clear()
                u.extra_this_round = 0
                u.tags.discard("_revived_this_round")
                if u.is_team_source:
                    for k in list(u.cooldowns):
                        u.cooldowns[k] = max(0, u.cooldowns[k] - 1)
            self.emit("round_start", 0, subject=None)
            if pet_timing == "round_start":
                self.emit("pet_phase", 0, subject=None)
            self.drain()
            if self._check_end():
                break
            order = self.action_order()
            if self.round == 1:
                self.first_round["order"] = [(u.uid, u.hero_id, round(u.stat("SPD"), 2)) for u in order]
            i = 0
            while i < len(order):
                u = order[i]
                i += 1
                self.take_turn(u)
                if self._check_end():
                    break
                if self.asm.get("order.resort_mid_round") and i < len(order):
                    rest = [x for x in self.action_order() if x in order[i:]]
                    order = order[:i] + rest
            if self.winner:
                break
            # ---- round end
            for u in self.fighters():
                self.tick_periodic(u, "round_end")
                if self._check_end():
                    break
            if self.winner:
                break
            if pet_timing == "round_end":
                self.emit("pet_phase", 0, subject=None)
            self.emit("round_end", 0, subject=None)
            self.drain()
            extras, self.eor_extras = self.eor_extras, []
            for p in extras:
                if self.winner:
                    break
                self._run_extra(p)
                self.drain()
            for u in self.units:
                self.tick_statuses(u, "round_end")
            if self.asm.get("cd.clock") == "round":
                for u in self.fighters():
                    if self.asm.get("cd.tick_while_controlled") or not u.has_control():
                        self._tick_cd(u)
                self._cd_fresh = set()
        return self.result()

    def _timeout(self):
        rule = self.asm.get("battle.draw_result")
        self.end_reason = "round_limit"
        if rule == "defender_wins":
            self.winner = "B"
        elif rule == "hp_percent":
            fa = sum(u.hp for u in self.fighters("A")) / max(1e-9, sum(u.max_hp for u in self.fighters("A", None)))
            fb = sum(u.hp for u in self.fighters("B")) / max(1e-9, sum(u.max_hp for u in self.fighters("B", None)))
            self.winner = "A" if fa > fb else "B" if fb > fa else "draw"
        else:
            self.winner = "draw"

    def result(self) -> BattleResult:
        units = []
        for u in self.units:
            if u.is_team_source:
                d = {"uid": u.uid, "side": u.side, "hero": "__team__", "team_source": True}
            else:
                d = {"uid": u.uid, "side": u.side, "hero": u.hero_id, "pos": u.pos, "alive": u.alive,
                     "hp": round(u.hp, 2), "max_hp": u.max_hp, "team_source": False}
            s = u.st
            d.update({k: getattr(s, k) for k in s.__dataclass_fields__ if k != "by_ability"})
            d["by_ability"] = {k: dict(v) for k, v in s.by_ability.items()}
            units.append(d)
        hp_left = {}
        for side in "AB":
            mx = sum(u.max_hp for u in self.fighters(side, None))
            hp_left[side] = round(sum(u.hp for u in self.fighters(side)) / mx, 4) if mx else 0.0
        return BattleResult(winner=self.winner or "draw", rounds=self.round, seed=self.seed, units=units,
                            deaths=self.deaths, round_damage={k: dict(v) for k, v in self.round_damage.items()},
                            first_round=self.first_round, assumptions_used=sorted(self.asm.used),
                            end_reason=self.end_reason or "wipe", hp_left=hp_left, log=self.log)
