"""Kits of the operator's main team: Тессарион, Виньетта, Сеньерен, Люцифер, Иллюсия, Мяоинь.

Sources: surrounded-by-girls.online skill texts (version not stated on the page for the first five; JP+GLOBAL
for Мяоинь), cross-checked with the Russian texts of lunafantasy.ru. Awakening-dependent numbers
("X/ Y" on the JP page, thresholds A5/A20/A25) are chosen by the heroine's awakening level.
"""
from __future__ import annotations

from . import KitBuilder, aw, st

SBG = "https://surrounded-by-girls.online/character/"
LFRU = "https://lunafantasy.ru/characters/"


# ------------------------------------------------------------------------------------------- Тессарион
def teselien(a, asm):
    k = KitBuilder("teselien", "Поддержка", asm)
    k.basic()
    k.notes.append("Кристалл Апокалипсиса: «発動/CT: なし» -> применяется каждый ход вместо обычной атаки")
    k.notes.append("Шанс заморозки: базовые 16% (варианты 堕20%/耀25% относятся к особым веткам развития - не применены)")
    k.active("apoc", "Кристалл Апокалипсиса", [
        {"op": "damage", "target": "enemy_all", "coef": aw(a, 1.34, (5, 1.59)), "dtype": "magic"},
        {"op": "status", "target": "hit", "chance": 0.16,
         "status": st("freeze", control="stun", duration=1, freeze_break_hits=2)}], prio=5, tags=["magic"])
    k.passive("coffin_revive", "Возрожденный Ледяной гроб (воскрешение)", k.round_event,
              [{"op": "revive", "target": "dead_ally_random", "count": 1, "hp_atk_pct": 1.8}],
              dead_ally_ge=1, cooldown=3)
    k.passive("coffin_heal", "Возрожденный Ледяной гроб (лечение)", "damaged",
              [{"op": "heal", "target": "event_target", "coef": 0.30}],
              relation="ally_or_self", per_subject_per_round=2, while_dead=True, attack_only=True)
    k.constitution([{"stat": "HP", "value": 0.45, "mode": "pct"}, {"stat": "ATK", "value": 0.25, "mode": "pct"},
                    {"stat": "CTRL_RES", "value": 0.20}], "Природа Синего дракона")
    k.passive("nature", "Природа Синего дракона", "battle_start", [
        {"op": "status", "target": "self", "status": st("bd_haste", kind="buff", duration=3, tick="round_end",
                                                         immune_control=True, mods=[{"stat": "SPD", "value": 0.30, "mode": "pct"}])},
        {"op": "status", "target": "ally_all", "status": st("bd_aura", kind="buff", undispellable=True,
                                                             mods=[{"stat": "ATK", "value": 0.15, "mode": "pct"},
                                                                   {"stat": "CRIT_DMG", "value": 0.30}])}])
    k.passive("aura_off", "Аура Синего дракона пропадает", "self_death",
              [{"op": "remove_status", "target": "ally_all", "key": "bd_aura"}])
    cold = st("cold", kind="debuff", stacking="stack", max_stacks=5, duration=2, undispellable=True,
              mods=[{"stat": "ATK", "value": -0.04, "mode": "pct"}, {"stat": "DR", "value": -0.04}],
              dot={"pct_max_hp": 0.02, "cap_src_max_hp_pct": 0.04, "dtype": "true"}, dot_timing="owner_turn_start")
    k.passive("cold_start", "Ледяной холод", "battle_start", [{"op": "status", "target": "enemy_all", "status": cold}])
    k.passive("cold_hit", "Ледяной холод (ответ)", "damaged", [{"op": "status", "target": "attacker", "status": cold}],
              relation="ally_or_self", chance=0.20, attack_only=True)
    k.passive("cold_act", "Ледяной холод (после действия)", "action",
              [{"op": "status", "target": "enemy_random:1", "status": cold}], relation="ally_or_self", chance=0.70)
    return k.build([SBG + "blue-dragon/", LFRU + "teselien"])


# ------------------------------------------------------------------------------------------- Виньетта
def vinette(a, asm):
    k = KitBuilder("vinette", "Поддержка", asm)
    k.notes.append("Обычная атака по 3 целям (enemy_first:3); множитель обычной атаки не опубликован -> kit.basic_coef")
    k.basic([{"op": "damage", "target": "enemy_first:3", "coef": float(asm.get("kit.basic_coef")), "dtype": "magic"},
             {"op": "damage", "target": "same", "coef": 0.0, "pct_self_max_hp": 0.06, "cap_atk_mult": 1.5, "dtype": "true"},
             {"op": "heal", "target": "ally_lowest_hp:1", "coef": 1.21}], name_ru="Обычная атака (Бонус леди)")
    k.active("love", "Оружие любви", [
        {"op": "damage", "target": "enemy_all", "coef": 0.98, "dtype": "magic",
         "ignore_def_per_res": {"name": "mark", "per": 0.07}},
        {"op": "status", "target": "hit", "chance": 0.70,
         "status": st("armor_break", kind="debuff", duration=2, mods=[{"stat": "DEF", "value": -0.20, "mode": "pct"}])},
        {"op": "heal", "target": "ally_all", "coef": 0.69},
        {"op": "status", "target": "ally_all", "status": st("breath", kind="buff", duration=2,
                                                             mods=[{"stat": "DMG_BONUS", "value": 0.25}, {"stat": "CRIT", "value": 0.15}])},
        {"op": "res", "target": "self", "name": "mark", "add": 1, "cap": 9}], ct=2, first=1, prio=7, tags=["magic"])
    k.notes.append("Жизненная связь: урон делится поровну между связанными (link.share); перезарядка «CT 3T» относится "
                   "к пассивке целиком в JP-тексте, в RU-тексте её нет -> не применена")
    k.passive("link", "Страсть (связь)", k.round_event, [
        {"op": "link", "target": "ally_link", "reset": True,
         "status": st("life_link", kind="buff", duration=2, undispellable=True,
                      mods=[{"stat": "MAGIC_DR", "value": 0.20}, {"stat": "CRIT_RES", "value": 0.15}])}])
    # up to 3 revives in one action start (9 marks max); marks are spent only if the revive succeeded
    eff = []
    for _ in range(3):
        eff += [{"op": "revive", "target": "dead_ally_random", "count": 1, "hp_atk_pct": 1.8,
                 "cond": {"res_ge": {"mark": 3}, "dead_ally_ge": 1}},
                {"op": "link", "target": "same", "cond": {"prev_nonempty": True}},
                {"op": "res", "target": "self", "name": "mark", "add": -3, "cond": {"prev_nonempty": True}}]
    k.passive("revive", "Страсть (воскрешение за 3 [Печати]/[Метки])", "action_start", eff, relation="self",
              dead_ally_ge=1, res_ge={"mark": 3})
    k.passive("link_heal", "Страсть (лечение связанных)", "action", [{"op": "heal", "target": "link_members", "coef": 0.46}],
              relation="self")
    k.passive("link_death", "Страсть (+1 [Метка] за гибель связанного)", "ally_death",
              [{"op": "res", "target": "self", "name": "mark", "add": 1, "cap": 9}], subject_linked=True)
    k.constitution([{"stat": "HP", "value": 0.45, "mode": "pct"}, {"stat": "ATK", "value": 0.25, "mode": "pct"},
                    {"stat": "CTRL_RES", "value": 0.20}], "Тело человека")
    k.passive("human_cleanse", "Тело человека (очищение)", "round_end", [{"op": "cleanse", "target": "ally_all", "count": 1}])
    k.passive("lady_start", "Бонус леди (старт)", "battle_start", [
        {"op": "res", "target": "self", "name": "mark", "add": 4, "cap": 9},
        {"op": "res_stat", "target": "self", "stat": "HEAL_BONUS", "name": "mark", "per": 0.03}])
    k.passive("lady_death", "Бонус леди (при смерти)", "self_death", [
        {"op": "revive", "target": "dead_allies_revivable", "hp_pct": 0.40},
        {"op": "link", "target": "ally_all"},
        {"op": "status", "target": "ally_all", "status": st("lady_atk", kind="buff", mods=[{"stat": "ATK", "value": 0.20, "mode": "pct"}])}],
        per_battle=1)
    k.notes.append("Бонус леди при смерти: воскрешает павших союзников, не себя (自身以外)")
    return k.build([SBG + "vignette/", LFRU + "vinette"])


# ------------------------------------------------------------------------------------------- Сеньерен
def seneren(a, asm):
    k = KitBuilder("seneren", "Поддержка", asm)
    k.basic()
    k.notes.append("Багровая трапеза: «CD なし» -> каждый ход; потолок 200% ATK применяется по цели (drain.cap_scope)")
    meal = [{"op": "drain", "target": "enemy_all", "pct_cur_hp": aw(a, 0.12, (5, 0.13)), "cap_atk_mult": 2.0,
             "heal_target": "ally_lowest_hp:3", "overflow_shield": "crimson_blessing", "shield_duration": 2}]
    k.active("meal", "Багровая трапеза", meal, prio=5)
    psn = st("deadly_poison", kind="debuff", duration=2, stacking="stack", max_stacks=5,
             mods=[{"stat": "MAGIC_DR", "value": -0.05}], dot={"pct_max_hp": 0.05, "cap_src_atk_mult": 1.0, "dtype": "true"})
    oath = [
        {"op": "status", "target": "ally_class:Воин", "status": st("oath_warrior", kind="buff", undispellable=True,
                                                                     ramp_missing_hp=aw(a, 0.04, (20, 0.045)),
                                                                     mods=[{"stat": "ATK", "value": 0.20, "mode": "pct"}, {"stat": "CRIT", "value": 0.10}])},
        {"op": "status", "target": "ally_class:Маг", "status": st("oath_mage", kind="buff", undispellable=True,
                                                                   mods=[{"stat": "DMG_BONUS", "value": 0.20}, {"stat": "CRIT_DMG", "value": 0.20}])},
        {"op": "status", "target": "ally_class:Страж", "status": st("oath_guard", kind="buff", undispellable=True,
                                                                     mods=[{"stat": "DR", "value": 0.20}, {"stat": "HEAL_RECV", "value": 0.10}])},
        {"op": "status", "target": "ally_class:Поддержка", "status": st("oath_support", kind="buff", undispellable=True,
                                                                         mods=[{"stat": "HEAL_BONUS", "value": 0.20}, {"stat": "CRIT_RES", "value": 0.10}])}]
    k.passive("oath", "Клятва ночного рода", k.round_event, oath, round=1)
    k.passive("oath_mage_poison", "Клятва: маги отравляют", "after_attack", [
        {"op": "status", "target": "event_hits", "chance": aw(a, 0.40, (20, 0.50)), "status": psn},
        {"op": "detonate", "target": "event_hits", "keys": ["deadly_poison"], "factor": 0.30,
         "tcond": {"stacks_ge": ["deadly_poison", aw(a, 3, (20, 4))]}, "cond": {"chance": aw(a, 0.50, (20, 0.80))}}],
        relation="ally_or_self", subject_has="oath_mage")
    k.passive("oath_guard_def", "Клятва: стражи снижают ЗАЩ атакующего", "damaged", [
        {"op": "status", "target": "attacker", "status": st("oath_def_down", kind="debuff", duration=2, undispellable=True,
                                                             stacking="stack", max_stacks=2,
                                                             mods=[{"stat": "DEF", "value": -0.10, "mode": "pct"}])}],
        relation="ally_or_self", subject_has="oath_guard", chance=aw(a, 0.80, (20, 0.90)), attack_only=True)
    k.passive("oath_support_heal", "Клятва: поддержка лечит", "action", [
        {"op": "heal", "target": "ally_lowest_hp:2", "coef": aw(a, 1.00, (20, 1.07))}],
        relation="ally_or_self", subject_has="oath_support", per_round=1)
    k.notes.append("Клятва: лечение «поддержки» ограничено 1 разом за ход на всю команду (各ターンにつき最大1回) - per_round=1")
    k.passive("bat_rebirth", "Клятва: возрождение летучей мыши", "self_death", [
        {"op": "revive", "target": "self", "hp_pct": 0.40}, {"op": "cast", "ability": "seneren:meal", "ignore_control": True}],
        per_battle=1)
    k.constitution([{"stat": "HP", "value": 0.45, "mode": "pct"}, {"stat": "ATK", "value": 0.25, "mode": "pct"},
                    {"stat": "CTRL_RES", "value": 0.20}], "Вампирская Конституция")
    k.passive("vamp_turn", "Вампирская Конституция (ход)", k.round_event, [
        {"op": "cleanse", "target": "self", "count": 99},
        {"op": "res_count", "target": "self", "name": "alive_allies", "count": "alive_allies"}])
    k.passive("vamp_dr", "Вампирская Конституция (снижение урона)", "battle_start", [
        {"op": "res_stat", "target": "self", "stat": "DR", "name": "alive_allies", "per": 0.05}])
    k.notes.append("Снижение урона +5% за каждого живого союзника: считаю включая саму Сеньерен (味方の生存者)")
    grant = [st("styx_immune", kind="buff", duration=2, immune_debuff=True, immune_control=True),
             st("parry_shield", kind="buff", block_hits=aw(a, 1, (25, 2)))]
    k.passive("styx_one", "Обратное течение Стикса", "action_start", [
        {"op": "revive", "target": "dead_ally_random", "count": 1, "hp_atk_pct": aw(a, 1.99, (25, 2.17)), "grant": grant}],
        relation="self", dead_ally_ge=1, dead_ally_lt=4, cooldown=3)
    k.passive("styx_all", "Обратное течение Стикса (4+ павших)", "action_start", [
        {"op": "revive", "target": "dead_allies_revivable", "hp_atk_pct": aw(a, 2.77, (25, 2.97)), "grant": grant},
        {"op": "heal", "target": "ally_all", "coef": aw(a, 1.50, (25, 1.61))},
        {"op": "status", "target": "ally_all", "status": grant[0]}], relation="self", dead_ally_ge=4, per_battle=1, priority=5)
    return k.build([SBG + "senerin/", LFRU + "seneren"])


# ------------------------------------------------------------------------------------------- Люцифер
def lucifer(a, asm):
    k = KitBuilder("lucifer", "Маг", asm)
    k.basic()
    psn = st("deadly_poison", kind="debuff", duration=2, stacking="stack", max_stacks=5,
             mods=[{"stat": "MAGIC_DR", "value": -0.05}], dot={"pct_max_hp": 0.05, "cap_src_atk_mult": 1.0, "dtype": "true"})
    flame = st("hell_flame", kind="debuff", duration=2, stacking="stack", max_stacks=3, undispellable=True,
               mods=[{"stat": "HEAL_RECV", "value": -0.20}], dot={"pct_max_hp": 0.05, "cap_src_atk_mult": 1.0, "dtype": "true"})
    k.notes.append("[Адское пламя]: снижение лечения 20% не складывается - моделирую как мод на статусе (стаки только урона)")
    decadence = [
        {"op": "damage", "target": "enemy_all", "coef": 0.95, "dtype": "magic", "bonus_per_debuff": {"per": 0.05, "cap": 0.40}},
        {"op": "status", "target": "hit", "chance": 0.60, "status": psn},
        {"op": "damage", "target": "enemy_all", "coef": 0.30, "dtype": "magic", "ignore_def": 1.0, "tcond": {"has": "devour"}},
        {"op": "status", "target": "hit", "chance": 0.80, "status": flame}]
    k.active("yuuda", "Декаданс", decadence, ct=2, first=1, prio=6, tags=["magic"])
    devour = st("devour", kind="debuff", undispellable=True, persist_on_death=False, mods=[{"stat": "DOT_TAKEN_RED", "value": -0.15}])
    love = [
        {"op": "status", "target": "enemy_without:devour", "status": devour},
        {"op": "damage", "target": "enemy_all", "coef": 1.40, "dtype": "magic"},
        {"op": "detonate", "target": "enemy_all", "tcond": {"has": "devour"}, "factor": 1.0}]
    k.active("love", "Любовь и наказание", love, ct=4, first=2, prio=8, tags=["magic"])
    k.notes.append("Любовь и наказание: «восстанавливает 30% от урона детонации, излишек -> щит» - НЕ закодировано "
                   "(нет операции «лечение от урона детонации»); помечено как пробел модели")
    k.constitution([{"stat": "ATK", "value": 0.45, "mode": "pct"}, {"stat": "HP", "value": 0.25, "mode": "pct"},
                    {"stat": "DMG_BONUS", "value": 0.15}], "Тело падшего ангела")
    k.passive("angel", "Тело падшего ангела", "battle_start", [
        {"op": "status", "target": "ally_all", "status": st("dot_ward", kind="buff", undispellable=True,
                                                             mods=[{"stat": "DOT_TAKEN_RED", "value": 0.15}])},
        {"op": "status", "target": "self", "status": st("dark_cover", kind="buff", duration=2, stealth=True)}])
    k.passive("gift_mark", "Подарок коррупции (метка)", "battle_start",
              [{"op": "status", "target": "enemy_highest_atk_lowest_hp", "status": devour}])
    k.passive("gift_stack", "Подарок коррупции (+[Печаль])", "action",
              [{"op": "res", "target": "self", "name": "sorrow", "add": 1}], relation="enemy", subject_has="devour", per_round=8)
    k.passive("gift_cast", "Подарок коррупции (доп. Декаданс)", "resource", [
        {"op": "res", "target": "self", "name": "sorrow", "add": -5},
        {"op": "cast", "ability": "lucifer:yuuda", "ignore_control": True}], resource="sorrow", res_ge={"sorrow": 5})
    k.passive("six", "Каждый 6-й Декаданс -> Любовь и наказание", "cast",
              [{"op": "cast", "ability": "lucifer:love", "ignore_control": True}], ability_id="lucifer:yuuda", every_n_casts=6)
    return k.build([SBG + "lucifer/", LFRU + "lucifer"])


# ------------------------------------------------------------------------------------------- Иллюсия
def illusia(a, asm):
    k = KitBuilder("illusia", "Страж", asm)
    venom = st("snake_venom", kind="debuff", duration=2, stacking="stack", max_stacks=9, undispellable=True,
               mods=[{"stat": "DEF", "value": -0.05, "mode": "pct"}], dot={"pct_src_max_hp": 0.05, "dtype": "true"},
               dot_on_expire=True)
    k.notes.append("[Змеиный яд]: максимум стаков 4 в тексте навыка и 9 в тексте пассивки - взято 9; урон 5% HP заклинателя "
                   "при истечении (2ターン後)")
    bite = [{"op": "damage", "target": "enemy_single", "coef": 0.60, "dtype": "physical"},
            {"op": "status", "target": "hit", "chance": 0.5, "status": venom},
            {"op": "damage", "target": "same", "coef": 0.60, "dtype": "physical"},
            {"op": "status", "target": "hit", "chance": 0.5, "status": venom},
            {"op": "damage", "target": "same", "coef": 0.0, "pct_self_max_hp": 0.05, "dtype": "true"},
            {"op": "status", "target": "same", "chance": 0.15, "cond": {"res_ge": {"venom_fluid": 5}},
             "status": st("provoked", kind="debuff", duration=2, provoke=True)},
            {"op": "res", "target": "self", "name": "venom_fluid", "add": 1, "cap": 15}]
    k.notes.append("[Укус змеи]: 120% физ. урона распределено на 2 удара по 60%; 5% HP - чистым уроном отдельно")
    k.basic(bite, name_ru="Укус змеи")
    k.active("barrier", "Барьер змеиной чешуи", [
        {"op": "barrier", "pct_max_hp": 0.90, "share": 0.50,
         "collapse": {"pct_of_total": 0.12, "target": "enemy_first:3", "dtype": "true"}},
        {"op": "heal", "target": "ally_lowest_hp:3", "tcond": {"hp_lt": 0.40}, "pct_self_max_hp": 0.10}], ct=2, first=1, prio=6)
    breath = [
        {"op": "status", "target": "enemy_all", "status": venom},
        {"op": "status", "target": "enemy_all", "chance": 0.90, "status": venom, "cond": {"res_ge": {"venom_fluid": 10}}},
        {"op": "damage", "target": "enemy_all", "coef": 1.13, "dtype": "physical", "pct_self_max_hp": 0.08, "lifesteal": 0.5,
         "per_res": {"status": "snake_venom", "pct_self_max_hp": 0.02}, "cond": {"res_lt": {"venom_fluid": 10}}},
        {"op": "damage", "target": "enemy_all", "coef": 1.13, "dtype": "physical", "lifesteal": 0.5, "cond": {"res_ge": {"venom_fluid": 10}}},
        {"op": "damage", "target": "enemy_all", "coef": 0.0, "dtype": "true", "pct_self_max_hp": 0.08,
         "per_res": {"status": "snake_venom", "pct_self_max_hp": 0.02}, "cond": {"res_ge": {"venom_fluid": 10}}}]
    k.notes.append("Дыхание: лечение 50% от урона смоделировано как вампиризм 0.5 основного удара; при 10 [Яде] доп. урон - чистый")
    k.active("breath", "Дыхание", breath, ct=2, first=2, prio=7)
    k.constitution([{"stat": "HP", "value": 0.45, "mode": "pct"}, {"stat": "ATK", "value": 0.25, "mode": "pct"},
                    {"stat": "DR", "value": 0.20}], "Тело синей змеи")
    k.passive("snake_regen", "Тело синей змеи (реген)", "damaged", [{"op": "heal", "target": "self", "pct_max_hp": 0.015}],
              attack_only=True)
    k.passive("snake_speed", "Тело синей змеи (скорость)", "battle_start", [
        {"op": "status", "target": "ally_all", "status": st("snake_speed", kind="buff", undispellable=True,
                                                             mods=[{"stat": "SPD", "value": 0.05, "mode": "pct"}])}])
    k.passive("counter", "Нейротоксин (контратака)", "damaged", [{"op": "extra_attack", "ability": "basic", "chance": 0.80}],
              attack_only=True)
    feast = [{"op": "damage", "target": "enemy_all", "coef": 1.54, "dtype": "physical"},
             {"op": "detonate", "target": "enemy_all", "keys": ["snake_venom"], "factor": 1.0, "consume": True}]
    k.active("feast", "Пир десяти тысяч ядов", feast, on="manual", prio=0)
    k.passive("feast15", "Нейротоксин (15 [Яда])", "resource", [
        {"op": "res", "target": "self", "name": "venom_fluid", "set": 0},
        {"op": "cast", "ability": "illusia:feast", "ignore_control": True}], resource="venom_fluid", res_ge={"venom_fluid": 15})
    k.notes.append("После 15 [Яда] счётчик сбрасывается в 0 (в тексте не указано) - допущение кита")
    k.passive("first_death", "Нейротоксин (первая смерть)", "self_death", [
        {"op": "revive", "target": "self", "hp_pct": 0.40, "ignore_revive_ban": True},
        {"op": "cast", "ability": "illusia:feast", "ignore_control": True}], per_battle=1)
    return k.build([SBG + "elsia/", LFRU + "illusia"])


# ------------------------------------------------------------------------------------------- Мяоинь
def miaoyin(a, asm):
    k = KitBuilder("sbg:hymelle", "Маг", asm)
    k.basic()
    k.notes.append("Мяоинь: числа глобальной версии; [Суд призрачного журавля] 194% и безмолвие 1 ход - проверено оператором в RU-клиенте")
    phys = aw(a, 3.17, (5, 3.42))
    phys_ext = aw(a, 0.06, (5, 0.08))
    ghost = aw(a, 1.34, (5, 1.59))
    ghost_ext = aw(a, 0.10, (5, 0.15))
    fire = st("damnation_fire", kind="debuff", duration=2, stacking="stack", max_stacks=5,
              dot={"coef": 0.15, "stat": "ATK", "dtype": "magic"})
    crane = [
        # physical form (form == 0)
        {"op": "damage", "target": "enemy_lowest_hp", "coef": phys, "dtype": "magic", "cond": {"res_lt": {"form": 1}}},
        {"op": "status", "target": "same", "cond": {"res_lt": {"form": 1}},
         "status": st("atk_drain", kind="debuff", duration=2, mods=[{"stat": "ATK", "value": -0.15, "mode": "pct"}])},
        {"op": "damage", "target": "same", "coef": 0.0, "pct_max_hp": phys_ext, "dtype": "magic", "tcond": {"hp_ge": 0.5},
         "cond": {"res_lt": {"form": 1}}},
        {"op": "res", "target": "self", "name": "styx", "add": 1, "cond": {"res_lt": {"form": 1}}},
        # ghost form (form == 1)
        {"op": "damage", "target": "enemy_all", "coef": ghost, "dtype": "magic", "bonus_if_target_hp_ge": {"thr": 0.5, "bonus": ghost_ext},
         "cond": {"res_ge": {"form": 1}}},
        {"op": "status", "target": "hit", "status": fire, "cond": {"res_ge": {"form": 1}}},
        {"op": "res", "target": "self", "name": "bodhi", "add": 1, "cond": {"res_ge": {"form": 1}}}]
    k.active("crane", "Две стороны журавля", crane, prio=5, tags=["magic"])
    k.passive("to_ghost", "Круговорот инь и ян (в призрака)", "resource", [
        {"op": "res", "target": "self", "name": "styx", "set": 0},
        {"op": "res", "target": "self", "name": "form", "set": 1},
        {"op": "heal", "target": "self", "pct_max_hp": 0.30},
        {"op": "status", "target": "self", "status": st("ghost_stealth", kind="buff", duration=1, stealth=True)},
        {"op": "status", "target": "self", "status": st("ghost_dr", kind="buff", duration=2, mods=[{"stat": "DR", "value": 0.10}])},
        {"op": "res", "target": "self", "name": "rebirth", "add": 1}], resource="styx", res_ge={"styx": 1})
    verdict = [
        {"op": "damage", "target": "enemy_all", "coef": 1.94, "dtype": "true", "bonus_if_target_hp_ge": {"thr": 0.5, "bonus": 0.10}},
        {"op": "status", "target": "hit", "status": st("silence", control="silence", duration=1)}]
    k.notes.append("Суд призрачного журавля: чистый урон 194% + 10% по целям с HP≥50% (бонус из текста навыка применяется к истинному урону)")
    k.active("verdict", "Суд призрачного журавля", verdict, on="manual", prio=0)
    k.passive("to_phys", "Круговорот инь и ян (в тело)", "resource", [
        {"op": "res", "target": "self", "name": "bodhi", "set": 0},
        {"op": "res", "target": "self", "name": "form", "set": 0},
        {"op": "cast", "ability": "sbg:hymelle:verdict"},
        {"op": "res", "target": "self", "name": "rebirth", "add": 1}], resource="bodhi", res_ge={"bodhi": 1})
    k.constitution([{"stat": "ATK", "value": 0.45, "mode": "pct"}, {"stat": "HP", "value": 0.25, "mode": "pct"},
                    {"stat": "CRIT", "value": 0.20}], "Тело белого журавля")
    k.passive("crane_reflect", "Тело белого журавля (отражение)", "battle_start", [
        {"op": "status", "target": "self", "status": st("crane_mirror", kind="buff", duration=4, tick="round_end",
                                                         reflect=0.30 * 0.5)}])
    k.notes.append("Отражение 30% урона с шансом 50% моделируется как ожидаемое значение 15% (НЕ точная механика: допущение кита)")
    k.passive("karma_atk", "Тысячеликая карма (ATK за печать)", "battle_start", [
        {"op": "res_stat", "target": "self", "stat": "ATK", "name": "rebirth", "per": aw(a, 0.06, (25, 0.09)), "mode": "pct"}])
    ashen = [
        {"op": "damage", "target": "enemy_all", "coef": aw(a, 2.01, (25, 2.39)), "dtype": "true"},
        {"op": "execute", "target": "enemy_all", "thr": aw(a, 0.20, (25, 0.22)), "mode": "threshold", "cap_atk_mult": 4.0,
         "on_kill_status": [st("soul_snatch", kind="debuff", revive_ban=True)]},
        {"op": "status", "target": "enemy_all", "tcond": {"hp_lt": aw(a, 0.20, (25, 0.22))},
         "status": st("soul_snatch", kind="debuff", revive_ban=True, persist_on_death=True)},
        {"op": "status", "target": "self", "status": st("karma_hot", kind="buff", duration=2, hot={"coef": 0.10, "stat": "ATK"})},
        {"op": "cleanse", "target": "self", "count": 99},
        {"op": "status", "target": "self", "status": st("flawless_glaze", kind="buff", duration=2, immune_debuff=True, immune_control=True)}]
    k.active("ashen", "Всё обратится в прах", ashen, on="manual", prio=0)
    k.passive("karma", "Тысячеликая карма", "resource", [
        {"op": "res", "target": "self", "name": "rebirth", "set": 0},
        {"op": "cast", "ability": "sbg:hymelle:ashen", "ignore_control": True}], resource="rebirth", res_ge={"rebirth": 2})
    k.notes.append("«Пожиратель душ» (Soul Snatcher): цели с HP<20% после «Всё обратится в прах» не могут быть воскрешены")
    return k.build([SBG + "hymelle/"])


KITS = {"teselien": teselien, "vinette": vinette, "seneren": seneren, "lucifer": lucifer, "illusia": illusia,
        "sbg:hymelle": miaoyin}
