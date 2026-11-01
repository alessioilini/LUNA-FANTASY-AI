"""Name resolution for build recommendations: JP guide terms and free-text RU names -> canonical candidates.

Canonical candidate = (category, key, RU display name):
  talents   -> RU client name of the talent (lunafantasy.ru 'sigil-talent' cards, verified on client screenshots)
  limbs     -> lunafantasy.ru limb set id      pets -> pet id      accessories -> accessory id
  cards / runes / princess weapons -> lunafantasy.ru ids

Every JP -> RU mapping carries a status that becomes a weight factor in the workbook:
  lfru_alias  - the JP name is listed as an alias on lunafantasy.ru (or is the id of its card)
  meaning     - unambiguous translation of the term (same effect wording); not yet confirmed by the operator
  hypothesis  - plausible but ambiguous; listed on the sheet «Сопоставление_JP_RU» for approval
Nothing is merged silently: an unmapped term is kept as its own candidate with status 'unmapped' (weight 0).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ---- talents (刻印 / タレント). Canonical = RU client name.
TALENT_JP: dict[str, tuple[str, str, str]] = {
    # jp: (ru_canonical, status, note)
    "魔法連擊": ("Маг комбо", "lfru_alias", "lfru: «Магическая серия» = клиентское «Маг комбо»"),
    "魔法連撃": ("Маг комбо", "lfru_alias", "вариант написания"),
    "魔連": ("Маг комбо", "meaning", "сокращение 魔法連撃 на SBG"),
    "物理連擊": ("Физ комбо", "lfru_alias", "lfru: «Физическая серия»"),
    "物理連撃": ("Физ комбо", "lfru_alias", "вариант написания"),
    "会心": ("Крит", "lfru_alias", ""),
    "会心率": ("Крит", "meaning", "шанс крита"),
    "会心ダメージ": ("Крит урон", "lfru_alias", ""),
    "会心ダメ": ("Крит урон", "meaning", "сокращение"),
    "貫通": ("Пробитие", "lfru_alias", "lfru: «Пробивание»"),
    "強欲": ("Жадность", "lfru_alias", ""),
    "回復薬": ("Предмет исцеления", "lfru_alias", ""),
    "生存": ("Выживание", "lfru_alias", ""),
    "浄化": ("Очищение", "lfru_alias", ""),
    "戦意": ("Воинственность", "lfru_alias", ""),
    "鈍化": ("Медлительность", "lfru_alias", ""),
    "抹殺": ("Уничтожение", "lfru_alias", ""),
    "吸収": ("Поглощение", "lfru_alias", ""),
    "回避": ("УКЛ", "lfru_alias", "lfru: «Уклонение»; в клиенте «УКЛ»"),
    "魔力": ("МС", "lfru_alias", "lfru: «Маг. сила»"),
    "解除": ("Рассеивание", "lfru_alias", ""),
    "集中": ("Внимание", "lfru_alias", ""),
    "精密": ("Точность", "lfru_alias", ""),
    "生命力": ("Жизненная сила", "lfru_alias", ""),
    "会心耐性": ("Крит СОПР", "lfru_alias", ""),
    "会心抵抗": ("Крит СОПР", "meaning", "вариант названия"),
    "制御": ("Контроль", "lfru_alias", ""),
    "波動": ("Волна", "lfru_alias", ""),
    "波動（超級）": ("Волна", "meaning", "超級 = высший уровень таланта"),
    "波動超級": ("Волна", "meaning", "超級 = высший уровень таланта"),
    "戒律": ("Дисциплина", "meaning", "戒律 = дисциплина"),
    "再生": ("Регенерация", "meaning", "再生 = регенерация"),
    "追撃": ("Преследование", "hypothesis", "追撃 = преследование/добивание"),
    "神の赦し": ("Прощение", "hypothesis", "神の赦し = божье прощение"),
    "ダメージ軽減": ("Защита", "hypothesis", "«снижение урона»; в клиенте возможно «Защита»"),
    # ambiguous: lunafantasy.ru card title differs from the client name used in RU builds -> operator approval
    "迅速": ("Ловкость", "hypothesis", "lfru-карточка: «Быстрота» (+СКР); в RU-билдах lfru/ChatGPT это «Ловкость»; альтернатива «СКР»"),
    "神護": ("Святое благословение", "hypothesis", "lfru-карточка: «Божественная защита»; в RU-билдах на том же месте «Святое благословение»"),
    "庇護": ("Покровительство", "hypothesis", "lfru-карточка: «Иммунитет к урону»; в RU-билдах ChatGPT на этом месте «Покровительство»"),
    "強靭": ("Упорство", "hypothesis", "lfru-карточка: «Стойкость»; в RU-билдах «Упорство» (tenacity)"),
    "減速": ("Медлительность", "hypothesis", "減速 = замедление; возможно другой талант, чем 鈍化"),
    "滅魂": ("Похититель душ", "hypothesis", "滅魂 = уничтожение души; по описанию оператора «Похититель душ» блокирует воскрешение"),
    "魂消滅": ("Похититель душ", "hypothesis", "то же, что 滅魂"),
    "精霊": ("Рассеяние духа", "hypothesis", "精霊 = дух; соответствие не подтверждено"),
    "聖霊": ("Святость", "hypothesis", "聖霊 = святой дух; соответствие не подтверждено"),
    "SPDダウン": ("Медлительность", "hypothesis", "снижение СКР"),
    "追擊": ("Преследование", "hypothesis", "追擊 = преследование/добивание"),
    "バトルソウル": ("Душа войны", "meaning", "battle soul"),
    "会心抵抗率": ("Крит СОПР", "meaning", ""),
    "戦力": ("Мощь", "hypothesis", "戦力 = боевая мощь"),
    "栄光": ("Доблесть", "hypothesis", "栄光 = слава; соответствие не подтверждено"),
    "反射": ("Контр-урон", "hypothesis", "反射 = отражение урона"),
    "喜怒楽": ("Восторг", "hypothesis", "喜怒楽 = эмоции; соответствие не подтверждено"),
    "フラッシュ": ("Душа молнии", "hypothesis", "flash; соответствие не подтверждено"),
}

# ---- pets (JP guide names -> lunafantasy.ru pet ids)
PET_JP: dict[str, tuple[str, str, str]] = {
    "夢女魅る枕": ("pet_dream_pillow", "meaning", "枕 = подушка"),
    "夢みる枕": ("pet_dream_pillow", "meaning", ""),
    "スターユニコーン": ("pet_star_unicorn", "meaning", "star unicorn"),
    "チェシャタートルウサギ": ("pet_cheshire_rabbit", "meaning", "Cheshire rabbit"),
    "チェシャ": ("pet_cheshire_rabbit", "meaning", ""),
    "パラダイスゴースト": ("pet_paradise_ghost", "meaning", "paradise ghost"),
    "ナイトレオプリンス": ("pet_leopard_prince", "meaning", "leo prince"),
    "グリフォン": ("pet_sacred_griffin", "meaning", ""),
    "聖殿のグリフォン": ("pet_sacred_griffin", "meaning", "храмовый грифон = Священный грифон"),
    "キャッスルフェニックス": ("pet_royal_phoenix", "hypothesis", "castle phoenix -> Королевский феникс"),
    "めぇめぇ": ("pet_dream_sheep", "hypothesis", "«мее-мее» = овцы"),
    "焔鱗谷の赤竜": ("pet_scaled_drake", "hypothesis", "красный дракон долины огненной чешуи -> Чешуйчатый дрейк"),
    "ケンタウロス": ("pet_shining_hoof", "hypothesis", "кентавр -> «Сияющее копыто»?"),
    "聖光のケンタウロス": ("pet_shining_hoof", "hypothesis", "кентавр священного света -> «Сияющее копыто»?"),
    "トリプルパンティ": ("pet_pantsu", "hypothesis", "triple panty -> «Панцу»"),
    "月の三頭狼": ("pet_lunar_three_headed_wolf", "meaning", ""),
}

# ---- accessories seen on JP guides (SBG uses short descriptive names)
ACCESSORY_JP: dict[str, tuple[str, str, str]] = {
    "ヒスイペンダント": ("accessory_jade_necklace", "meaning", "jade pendant"),
    "ヒスイのペンダント": ("accessory_jade_necklace", "meaning", ""),
    "ダイヤペンダント": ("accessory_diamond_necklace", "meaning", ""),
    "ダイヤのペンダント": ("accessory_diamond_necklace", "meaning", ""),
    "ダイヤヘアクリップ": ("accessory_diamond_hairpin", "meaning", ""),
    "ダイヤのヘアクリップ": ("accessory_diamond_hairpin", "meaning", ""),
    "ヒスイ氷種ヘアクリップ": ("accessory_jade_ice_hairpin", "meaning", ""),
    "ダイヤリング": ("accessory_diamond_cluster_ring", "hypothesis", "diamond ring -> кольцо с группой бриллиантов"),
    "ダイヤのリング": ("accessory_diamond_cluster_ring", "hypothesis", ""),
    "ダイヤのブレスレット": ("accessory_small_diamond_bracelet", "hypothesis", "есть два «Браслета с мелкими бриллиантами»"),
    "ヒスイの氷種ブレスレット": ("accessory_jade_ice_bracelet", "meaning", ""),
    "ヒスイ精緻なティアラ": ("accessory_jade_carved_crown", "hypothesis", "精緻 = изысканная/резная тиара из нефрита"),
    "ヒスイの精緻なティアラ": ("accessory_jade_carved_crown", "hypothesis", ""),
    "ヒスイバングル": ("accessory_jade_cuff", "hypothesis", "нефритовый браслет-бэнгл -> наруч с нефритовой окантовкой"),
    "金バングル": ("accessory_gold_smooth_bracelet", "hypothesis", "gold bangle"),
    "金のバングル": ("accessory_gold_smooth_bracelet", "hypothesis", ""),
    "金髪飾り": ("accessory_gold_pattern_headpiece", "hypothesis", "золотое украшение для волос"),
    "金の髪飾り": ("accessory_gold_pattern_headpiece", "hypothesis", ""),
    "金のアームレット": ("accessory_gold_carved_bracelet", "hypothesis", "armlet"),
    "金のビーズアンクレット": ("accessory_gold_anklet_beads", "meaning", "gold bead anklet"),
}

# ---- limb sub-stats (AppMedia 'スロット1・3 / 2・4')
SUBSTAT_JP: dict[str, tuple[str, str]] = {
    "ATK": ("АТК", "meaning"), "SPD": ("СКР", "meaning"), "HP": ("ОЗ", "meaning"), "DEF": ("ЗАЩ", "meaning"),
    "被回復率": ("Получаемое лечение", "meaning"), "回復率": ("Лечение", "meaning"),
    "物理ダメ軽減": ("Снижение физ. урона", "meaning"), "魔法ダメ軽減": ("Снижение маг. урона", "meaning"),
    "物理ダメ": ("Физ. урон", "meaning"), "魔法ダメ": ("Маг. урон", "meaning"),
    "会心率": ("Шанс крита", "meaning"), "会心ダメ": ("Крит. урон", "meaning"), "会心耐性": ("Крит. СОПР", "meaning"),
    "回避率": ("Уклонение", "meaning"), "命中率": ("Точность", "meaning"), "命中": ("Точность", "meaning"),
    "光抵抗": ("Сопр. Свету", "meaning"), "闇抵抗": ("Сопр. Тьме", "meaning"), "火抵抗": ("Сопр. Огню", "meaning"),
    "風抵抗": ("Сопр. Ветру", "meaning"), "氷抵抗": ("Сопр. Льду", "meaning"),
    "状態異常": ("Шанс контроля", "hypothesis"), "制御率": ("Шанс контроля", "hypothesis"),
}

# free-text RU names (ChatGPT plans, lfru labels) -> canonical talent names
TALENT_RU_ALIASES = {
    "маг комбо": "Маг комбо", "магическая серия": "Маг комбо", "физ комбо": "Физ комбо", "физическая серия": "Физ комбо",
    "мс": "МС", "маг сила": "МС", "укл": "УКЛ", "уклонение": "УКЛ", "пробивание": "Пробитие",
    "крит сопр": "Крит СОПР", "критсопр": "Крит СОПР", "крит урон": "Крит урон", "критический урон": "Крит урон",
    "имм к урону": "Имм к урону", "иммунитет к урону": "Имм к урону", "стойкость": "Упорство",
    "быстрота": "Ловкость", "божественная защита": "Святое благословение", "жизненная сила": "Жизненная сила",
    "выживание": "Выживание", "самосохранение": "Самосохранение",
}


def norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = re.sub(r"[+*.,:;!?\"«»'’`—–\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=1)
def entities() -> list[dict]:
    return json.loads((ROOT / "data/kb/lfru/entities.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def entity_index() -> dict:
    """kind -> {normalized title/alias/id-suffix -> (id_suffix, title)}"""
    idx: dict[str, dict] = {}
    for x in entities():
        kind = x["kind"]
        suf = x["id"].split(":", 1)[1]
        d = idx.setdefault(kind, {})
        for k in [x["title"], suf, *x.get("aliases", [])]:
            d.setdefault(norm(k), (suf, x["title"]))
    return idx


@lru_cache(maxsize=1)
def talent_names() -> dict[str, str]:
    """normalized -> canonical RU client talent name"""
    out = {}
    for x in entities():
        if x["kind"] == "sigil-talent":
            out[norm(x["title"])] = x["title"]
    for a, c in TALENT_RU_ALIASES.items():
        out.setdefault(norm(a), c)
    return out


def talent_from_lfru_id(full_id: str) -> tuple[str, str, str]:
    """lunafantasy.ru build ids: 'sigil-talent:talent_advanced_pierce' or 'sigil:庇護' or 'sigil:крит-сопр'."""
    kind, suf = full_id.split(":", 1)
    if kind == "sigil-talent":
        t = next((x["title"] for x in entities() if x["id"] == full_id), suf)
        return t, "lfru_alias", ""
    if suf in TALENT_JP:
        return TALENT_JP[suf]
    return talent_from_ru(suf.replace("-", " "))


def talent_from_ru(name: str) -> tuple[str, str, str]:
    n = norm(name)
    names = talent_names()
    if n in names:
        return names[n], "lfru_alias", ""
    # «Жизненная сила / Выживание» -> first alternative
    for part in re.split(r"/| или ", name):
        if norm(part) in names:
            return names[norm(part)], "meaning", f"из «{name.strip()}» взят первый вариант"
    return name.strip(), "unmapped", "нет в справочнике талантов lunafantasy.ru"


def talent_from_jp(name: str) -> tuple[str, str, str]:
    n = name.strip()
    if n in TALENT_JP:
        return TALENT_JP[n]
    n2 = re.sub(r"[（(].*?[)）]", "", n)
    if n2 in TALENT_JP:
        return TALENT_JP[n2]
    return n, "unmapped", "JP-термин без RU-соответствия"


def entity_from_name(kind: str, name: str, jp_table: dict | None = None) -> tuple[str, str, str, str]:
    """-> (id_suffix, ru_title, status, note)"""
    if jp_table and name.strip() in jp_table:
        suf, st, note = jp_table[name.strip()]
        title = next((x["title"] for x in entities() if x["id"] == f"{kind}:{suf}"), suf)
        return suf, title, st, note
    idx = entity_index().get(kind, {})
    n = norm(name)
    if n in idx:
        suf, title = idx[n]
        return suf, title, "lfru_alias", ""
    # loose: unique entity whose normalized title is contained in / contains the name
    hits = {v for k, v in idx.items() if k and (k in n or n in k) and min(len(k), len(n)) >= 4}
    if len(hits) == 1:
        suf, title = hits.pop()
        return suf, title, "meaning", f"частичное совпадение названия «{name.strip()}»"
    return norm(name) or name, name.strip(), "unmapped", f"нет в справочнике {kind}"


def limb_from_jp(name: str) -> tuple[str, str, str, str]:
    return entity_from_name("limb", name)


def hero_slug(x: dict) -> str:
    """lunafantasy.ru character slug as used in URLs and builds.json (/characters/<slug>)."""
    h = x.get("href") or ""
    return h.rstrip("/").split("/")[-1] if h.startswith("/characters/") else x["id"].split("_", 1)[1]


@lru_cache(maxsize=1)
def hero_index() -> dict[str, tuple[str, str]]:
    """normalized RU/JP name or slug -> (lfru_slug, RU title)"""
    idx = {}
    for x in entities():
        if x["kind"] != "character":
            continue
        slug = hero_slug(x)
        for k in [x["title"], slug, x["id"].split("_", 1)[1], *x.get("aliases", [])]:
            idx.setdefault(norm(k), (slug, x["title"]))
    xr = json.loads((ROOT / "data/kb/crossref_heroes.json").read_text(encoding="utf-8"))
    for r in xr:
        if r.get("lfru_slug"):
            t = idx.get(norm(r["lfru_slug"]), (r["lfru_slug"], r.get("lfru_ru") or r["lfru_slug"]))
            for k in [r.get("name_jp"), r.get("sbg_slug"), r.get("global_name")]:
                if k:
                    idx.setdefault(norm(k), t)
    # operator-confirmed RU names that lunafantasy.ru spells differently or lists under another slug
    for ru, slug in {"сеньерен": "seneren", "мяоинь": "hymelle", "верафиэль": "nurse-girl", "юки юки": "yuki",
                     "тессарион": "teselien", "кира": "kira", "хлоя": "chloe", "клим": "kurimu"}.items():
        if norm(slug) in idx:
            idx.setdefault(ru, idx[norm(slug)])
        else:
            idx.setdefault(ru, (slug, ru.capitalize()))
    return idx


def hero_from_name(name: str) -> tuple[str, str] | None:
    n = norm(name)
    idx = hero_index()
    if n in idx:
        return idx[n]
    first = n.split(" ")[0] if n else ""
    return idx.get(first)
