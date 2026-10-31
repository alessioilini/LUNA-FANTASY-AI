"""Regenerates data/kb/facts/*.jsonl from the research log of 2026-10-31.

Every fact below was obtained in this session. Network policy blocked direct fetches of
lunafantasy.ru, appmedia.jp, surrounded-by-girls.online and qoo-app.com, so the only
external evidence is WebSearch result snippets (confidence LOW, must be re-verified by
opening the page) and statements made by the operator in the task prompt (USER_STATED).
No numeric combat effect is invented here.
"""
import json
from pathlib import Path

ACC = "2026-10-31"
OUT = Path(__file__).resolve().parents[1] / "data" / "kb" / "facts"

def src(url, title="", kind="search_snippet", note=""):
    return {"url": url, "title": title, "accessed": ACC, "kind": kind, "note": note}

PROMPT = src("operator-prompt:2026-10-31", "Task brief from operator", "user_prompt")

def F(key, value, region, source, conf, **kw):
    d = {"key": key, "value": value, "region": region, "source": source, "confidence": conf,
         "balance_version": kw.pop("balance_version", "UNKNOWN"), "version_date": kw.pop("version_date", "UNKNOWN")}
    d.update(kw)
    return d

facts = {"RU": [], "JP": [], "EN": [], "SEA": [], "KR": [], "RR": []}

# ---------------- RU: operator statements (structure of the game) ----------------
R = facts["RU"]
R += [
 F("region.ru.title", "Luna Fantasy", "RU", PROMPT, "user_stated", ru_status="unverified"),
 F("region.ru.kb_url", "https://lunafantasy.ru/", "RU", PROMPT, "user_stated",
   notes="Primary RU source. Not fetched: blocked by session network policy on 2026-10-31."),
 F("region.ru.store_listing", "Luna Fantasy (Android)", "RU",
   src("https://trashbox.ru/link/luna-fantasy-android", "trashbox.ru: Luna Fantasy"), "low",
   notes="Search snippet: RPG with visual-novel elements and character collection."),
 F("rules.team.size", 6, "RU", PROMPT, "user_stated", notes="PvP team of six heroines"),
 F("rules.build.sigil_count", 2, "RU", PROMPT, "user_stated"),
 F("rules.build.talents_per_sigil", 2, "RU", PROMPT, "user_stated"),
 F("rules.build.separate_talent_count", 2, "RU", PROMPT, "user_stated",
   notes="Two personal talents are a separate system from the sigil talents - never merge."),
 F("rules.build.limb_slots", 4, "RU", PROMPT, "user_stated", notes="Limb set bonuses at 2 and 4 pieces"),
 F("rules.build.limb_set_thresholds", [2, 4], "RU", PROMPT, "user_stated"),
 F("rules.build.decoration_slots", 8, "RU", PROMPT, "user_stated",
   notes="Operator: 'eight slots, if confirmed for RU' - treated as unverified."),
 F("rules.build.pet_slots_by_rarity", "UNKNOWN", "RU", PROMPT, "user_stated",
   notes="Depends on rarity; table not sourced."),
 F("rules.team.rune_count", 4, "RU", PROMPT, "user_stated", notes="Four runes in activation order; nested runes with probabilities"),
 F("rules.team.princess_weapon_positions", 4, "RU", PROMPT, "user_stated", notes="Four positions + resonance"),
 F("glossary.limb.other_regions", "demons", "RU", PROMPT, "user_stated",
   ru_name="Лимбы", notes="Called 'demons' in other versions."),
 F("glossary.stat.SPD", "СКР", "RU", PROMPT, "user_stated", ru_name="СКР", original_name="SPD"),
 F("effect.soul_eater.name", "Пожиратель душ", "RU", PROMPT, "user_stated", ru_name="Пожиратель душ",
   notes="Effect text and numbers UNKNOWN - hypothesis tests blocked until sourced."),
]
heroes_prompt = ["Hymelle", "Lucifer", "Klim", "Seneren", "Vignette", "Kira", "Illusia", "Verafiel", "Chloe", "Seraphia", "Nyxara"]
for h in heroes_prompt:
    R.append(F(f"hero.{h.lower()}.name.latin", h, "RU", PROMPT, "user_stated",
               notes="Name as written by operator; RU spelling not yet confirmed from lunafantasy.ru"))
R += [
 F("hero.verafiel.name.ru", "Верафиэль", "RU", PROMPT, "user_stated", ru_name="Верафиэль"),
 F("hero.verafiel.role", "support", "RU", PROMPT, "user_stated", ru_name="Поддержка"),
 F("hero.seraphia.alias.ru", "Монашка", "RU", PROMPT, "user_stated", ru_name="Монашка"),
 F("hero.kira.reference_url", "https://surrounded-by-girls.online/character/kira/", "RU", PROMPT, "user_stated",
   notes="Example community page given by operator; not fetched (blocked)."),
]

# ---------------- JP ----------------
APPM = "https://appmedia.jp/yabasyoujyo"
J = facts["JP"]
J += [
 F("region.jp.title", "やばい！少女に囲まれた！", "JP", src(APPM, "AppMedia ヤバ少女攻略"), "medium", original_name="やばい！少女に囲まれた！"),
 F("region.jp.ios_app_id", "id6740237645", "JP", src("https://apps.apple.com/jp/app/id6740237645", "App Store JP"), "medium"),
 F("region.jp.guide_hub", APPM, "JP", src(APPM, "AppMedia"), "medium"),
 F("hero.lucifer.name.jp", "ルシファー", "JP", src("https://dengekionline.com/article/202505/42108", "電撃オンライン"), "low", original_name="ルシファー"),
 F("hero.lucifer.element", "dark", "JP", src("https://dengekionline.com/article/202505/42108", "電撃オンライン"), "low", original_name="闇属性"),
 F("hero.lucifer.class", "mage", "JP", src("https://dengekionline.com/article/202505/42108", "電撃オンライン"), "low", original_name="魔法使い"),
 F("hero.lucifer.trait", "magic AoE burst", "JP", src("https://dengekionline.com/article/202505/42108", "電撃オンライン"), "low", original_name="魔法範囲爆裂"),
 F("hero.lucifer.rarity", "GR", "JP", src("https://dengekionline.com/article/202505/42108", "電撃オンライン"), "low"),
 F("hero.lucifer.summary", "magic attacker that amplifies abnormal-status damage", "JP", src(APPM, "AppMedia evaluation"), "low"),
 F("hero.lucifer.tier.appmedia", "SS", "JP", src(APPM, "AppMedia evaluation"), "low"),
 F("hero.seneren.name.jp", "セネリン", "JP", src(APPM, "AppMedia evaluation"), "low", original_name="セネリン",
   notes="HYPOTHESIS: operator's 'Seneren' = セネリン. Name match only."),
 F("hero.seneren.summary", "buffs whole team by class when fielded; high revive durability", "JP", src(APPM, "AppMedia evaluation"), "low"),
 F("hero.seneren.tier.appmedia", "SS", "JP", src(APPM, "AppMedia evaluation"), "low"),
 F("hero.vignette.name.jp", "ヴィネット", "JP", src("https://appmedia.jp/?p=78914927", "AppMedia ヴィネット (one of several result URLs)"), "low", original_name="ヴィネット"),
 F("hero.vignette.class", "support", "JP", src("https://appmedia.jp/?p=78914927"), "low", original_name="サポーター"),
 F("hero.vignette.summary", "revive specialist: active revives up to 3 allies; passive revives others (not self)", "JP", src("https://appmedia.jp/?p=78914927"), "low"),
 F("hero.vignette.tier.appmedia", "SSS", "JP", src("https://appmedia.jp/?p=78914927"), "low"),
 F("hero.vignette.panel.ATK", 112804, "JP", src("https://appmedia.jp/?p=78914927"), "low", notes="Level/stars/build of the sample unknown; rank 42/76 on site"),
 F("hero.vignette.panel.HP", 1166073, "JP", src("https://appmedia.jp/?p=78914927"), "low", notes="rank 6/76"),
 F("hero.vignette.panel.DEF", 5174, "JP", src("https://appmedia.jp/?p=78914927"), "low", notes="rank 14/76"),
 F("hero.vignette.panel.SPD", 4677, "JP", src("https://appmedia.jp/?p=78914927"), "low", notes="rank 5/76"),
 F("hero.elsia.name.jp", "エルシア", "JP", src(APPM, "AppMedia character list"), "low", original_name="エルシア",
   notes="HYPOTHESIS: may correspond to operator's 'Illusia'. Unconfirmed."),
 F("hero.elsia.class", "guardian", "JP", src(APPM), "low", original_name="ガーディアン"),
 F("hero.elsia.summary", "barrier for allies, counterattack, snake poison damage", "JP", src(APPM), "low"),
 F("hero.olivia.name.jp", "オリビア", "JP", src(APPM, "AppMedia latest news"), "low", original_name="オリビア"),
 F("hero.olivia.summary", "light mage attacker; multi-target each turn; unlimited follow-up attacks on ally actions", "JP", src(APPM), "low",
   notes="New JP release - NOT assumed available in RU."),
 F("region.jp.roster_size_on_appmedia", 76, "JP", src("https://appmedia.jp/?p=78914927"), "low", notes="'76体中' in ranking snippets"),
]
for k in ["リアドラ", "クトゥルフ", "ミリム"]:
    J.append(F(f"hero.jp_{k}.name.jp", k, "JP", src(APPM, "AppMedia character pages"), "low", original_name=k))

# ---------------- EN ----------------
QOO_EN = "https://m-apps.qoo-app.com/en-US/app/78580"
facts["EN"] += [
 F("region.en.title", "Tales of Angels", "EN", src(QOO_EN, "QooApp: Tales of Angels | English"), "low"),
 F("region.en.launch", "2024-12", "EN", src(QOO_EN, "QooApp news"), "low", notes="Official launch announced Dec 2024 (snippet)"),
 F("region.en.genre", "idle RPG, Live2D", "EN", src(QOO_EN), "low"),
]
# ---------------- SEA ----------------
QOO_SEA = "https://m-apps.qoo-app.com/en-US/app/78074"
facts["SEA"] += [
 F("region.sea.title", "Maidens Fantasy: LUST | SEA", "SEA", src(QOO_SEA, "QooApp"), "low", original_name="少女幻想:LUST|東南亞版"),
 F("region.sea.version", "v1.0.5", "SEA", src(QOO_SEA), "low", version_date="2025-12-23",
   notes="Contradiction: QooApp news mentions a 2.1.1 update in Jan 2025. Re-verify."),
 F("region.sea.version_news", "2.1.1", "SEA", src(QOO_SEA, "QooApp news"), "low", version_date="2025-01"),
]
# ---------------- KR / RR: searched, nothing found ----------------
facts["KR"].append(F("region.kr.title", "각성소녀: 욕망의 여정", "KR", PROMPT, "user_stated",
    notes="Search on 2026-10-31 returned no matching page."))
facts["RR"].append(F("region.rr.title", "Realm Rush: Bonded Maidens", "RR", PROMPT, "user_stated",
    notes="Search on 2026-10-31 returned no matching page."))

OUT.mkdir(parents=True, exist_ok=True)
for region, rows in facts.items():
    with open(OUT / f"{region}.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            r.setdefault("ru_status", "unverified")
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(region, len(rows))
