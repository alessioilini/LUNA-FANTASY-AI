"""Tiny builders for mechanic tests. All numbers are synthetic."""
from luna.engine.assumptions import AssumptionSet
from luna.engine.battle import Battle
from luna.engine.state import Unit

BASE = {"ATK": 100.0, "HP": 1000.0, "DEF": 0.0, "SPD": 100.0}


def basic(coef=1.0, dtype="physical", target="enemy_single", aid="basic", **kw):
    eff = dict({"op": "damage", "target": target, "coef": coef, "dtype": dtype}, **kw)
    return {"id": aid, "kind": "basic", "effects": [eff], "tags": [dtype]}


def U(uid, stats=None, abilities=None, pos=None, hero=None, tags=()):
    side = uid[0]
    pos = int(uid[1:]) if pos is None else pos
    s = dict(BASE)
    s.update(stats or {})
    u = Unit(uid=uid, side=side, pos=pos, hero_id=hero or uid, name=uid, stats=s,
             abilities=abilities if abilities is not None else [basic()])
    u.tags.update(tags)
    return u


def team_source(side, abilities):
    u = Unit(uid=f"{side}T", side=side, pos=99, hero_id="__team__", name="team", stats={"ATK": 100.0, "HP": 1.0},
             abilities=abilities, is_team_source=True)
    return u


def asm(**over):
    stacking = over.pop("stacking", {})
    a = AssumptionSet.preset("exploratory_v1", stacking=stacking)
    a.values.update(over)
    return a


def fight(A, B, seed=1, log=True, **over):
    b = Battle(A, B, asm(**over), seed=seed, log=log)
    res = b.run()
    return b, res


def run_round(A, B, seed=1, **over):
    """Run exactly one round (max_rounds=1)."""
    return fight(A, B, seed=seed, **dict({"battle.max_rounds": 1}, **over))


def events(res, t):
    return [e for e in res.log if e["t"] == t]
