"""Import of the operator's materials of 2026-11-01:
  1) 5 panel screenshots from the RU client (USER_OBSERVED, transcribed by Claude; labels partly truncated);
  2) 4 XLSX development plans generated earlier with ChatGPT (ASSISTANT_HISTORICAL);
  3) 'MASTER KNOWLEDGE BASE' text exported from ChatGPT (statuses as declared in it).

Status mapping to luna.provenance.Confidence:
  USER_OBSERVED -> user_stated   ASSISTANT_HISTORICAL -> hypothesis
  REGIONAL_PROVISIONAL -> low    UNVERIFIED_HYPOTHESIS -> hypothesis
Historical / hypothesis facts rank lowest in KnowledgeBase.best and never override verified data.
"""
import datetime as dt
import glob
import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
D = "2026-11-01"
CONF = {"USER_OBSERVED": "user_stated", "ASSISTANT_HISTORICAL": "hypothesis",
        "REGIONAL_PROVISIONAL": "low", "UNVERIFIED_HYPOTHESIS": "hypothesis"}
SRC_KB = {"url": "operator-chat:2026-11-01#chatgpt-master-kb", "title": "LUNA FANTASY AI — MASTER KNOWLEDGE BASE (ChatGPT export)",
          "accessed": D, "kind": "user_prompt"}

# ------------------------------------------------------------------ 1. screenshots (transcription)
# label on screen -> stat key; truncated labels are interpreted (see LABELS_NOTE) and listed for confirmation
LABELS = {"МТК": ("ACC", "Меткость (интерпретация сокращения «МТК»)"),
          "Крит. ша…": ("CRIT", "Крит. шанс"), "Шанс ко…": ("COMBO_CHANCE", "Шанс комбо (интерпретация)"),
          "ДОП Ф.У…": ("PHYS_DMG_BONUS", "Доп. физ. урон"), "ДОП М.У…": ("MAGIC_DMG_BONUS", "Доп. маг. урон"),
          "Крит. ур…": ("CRIT_DMG", "Крит. урон"), "Лечение": ("HEAL_BONUS", "Лечение"), "ДОП урон": ("DMG_BONUS", "Доп. урон"),
          "УКЛ": ("DODGE", "Уклонение"), "Крит. СО…": ("CRIT_RES", "Крит. сопротивление (интерпретация)"),
          "Шанс С…": ("CTRL_RES", "Шанс сопротивления (интерпретация: у героинь с «СОПР +20%» в пассивке он выше на ~20-40%)"),
          "СОПР Ф…": ("PHYS_DR", "Сопр. физ. урону"), "СОПР М…": ("MAGIC_DR", "Сопр. маг. урону"),
          "СОПР кр…": ("CRIT_DMG_RES", "Сопр. крит. урону (интерпретация)"), "Получен…": ("HEAL_RECV", "Получаемое лечение"),
          "СОПР ур…": ("DR", "Сопротивление урону")}
ORDER = ["МТК", "Крит. ша…", "Шанс ко…", "ДОП Ф.У…", "ДОП М.У…", "Крит. ур…", "Лечение", "ДОП урон",
         "УКЛ", "Крит. СО…", "Шанс С…", "СОПР Ф…", "СОПР М…", "СОПР кр…", "Получен…", "СОПР ур…"]
PANELS = [  # file, hero_id, title on screen, awakening, ATK, HP, DEF, SPD, 16 secondary % (ORDER), special bonus
    ("1.jpg", "vinette", "Человек · Виньетта", 14, 9019515, 116209904, 23513, 9519,
     [128.3, 23, 23, 11.8, 6.3, 156, 23, 40.7, 31.3, 65.6, 57.5, 4, 31.4, 12, 20.3, 34.7], "Навык Войны гильдий Поддержка 240"),
    ("2.jpg", "teselien", "Синий дракон · Тессарион", 24, 7831726, 102348968, 21357, 9506,
     [128.3, 10, 34, 15.8, 8.3, 153, 48, 40.7, 29.3, 54.1, 59.5, 4, 24.9, 0, 35.3, 34.7], "Навык Войны гильдий Поддержка 240"),
    ("3.jpg", "lucifer", "Смерть Ангела · Люцифер", 24, 9521849, 114462528, 22531, 9078,
     [128.3, 70, 23, 11.8, 29.3, 190, 0, 97.7, 25.3, 29.1, 17.5, 4, 4.9, 0, 5.3, 29.7], "Навык Войны гильдий Маг 240"),
    ("4.jpg", "seneren", "Вампирская летучая мышь · Сеньерен", 24, 9060047, 108750240, 23330, 9810,
     [132.3, 23, 23, 19.8, 6.3, 150, 41, 40.7, 50.8, 92.1, 61.5, 4, 28.9, 0, 41.8, 43.7], "Навык Войны гильдий Поддержка 240"),
    ("5.jpg", "illusia", "Змейка · Иллюсия", 24, 8206328, 118647512, 26101, 12992,
     [134.8, 15, 49.5, 11.8, 6.3, 150, 5, 45.7, 39.3, 70.6, 17.5, 24, 4.9, 9.5, 5.3, 63.7], "Навык Войны гильдий Страж 240"),
]


def panels():
    out, facts = [], []
    for f, hid, title, awk, atk, hp, df, spd, sec, special in PANELS:
        stats = {"ATK": atk, "HP": hp, "DEF": df, "SPD": spd}
        secondary = {}
        for lab, val in zip(ORDER, sec):
            key, ru = LABELS[lab]
            secondary[key] = {"value_pct": val, "label_on_screen": lab, "label_ru": ru}
        rec = {"hero_id": hid, "title_on_screen": title, "awakening": awk, "skill_levels": [3, 3, 3, 3],
               "stats": stats, "secondary": secondary, "special_bonus": special, "screenshot": f"data/user/screenshots/2026-11-01/{f}",
               "observed": D, "status": "USER_OBSERVED", "note": "панель зависит от уровня/звёзд/экипировки; снимок - пример (оператор)"}
        out.append(rec)
        src = {"url": f"screenshot:data/user/screenshots/2026-11-01/{f}", "title": f"RU-клиент: панель {title}", "accessed": D,
               "kind": "screenshot"}
        for k, v in stats.items():
            facts.append({"key": f"hero.{hid}.panel_ru.{k}", "value": v, "region": "RU", "source": src, "confidence": "user_stated",
                          "balance_version": "ru-client@2026-11-01", "version_date": D, "ru_status": "verified_in_ru_client",
                          "notes": f"A{awk}; снимок панели оператора; зависит от уровня/экипировки"})
        for k, v in secondary.items():
            facts.append({"key": f"hero.{hid}.panel_ru.{k}", "value": v["value_pct"] / 100, "region": "RU", "source": src,
                          "confidence": "user_stated", "balance_version": "ru-client@2026-11-01", "version_date": D,
                          "ru_status": "verified_in_ru_client",
                          "notes": f"A{awk}; подпись «{v['label_on_screen']}» -> {v['label_ru']}"})
    return out, facts


# ------------------------------------------------------------------ 2. XLSX plans
def xlsx_dump():
    books = []
    for p in sorted(glob.glob(str(ROOT / "data/kb/imports/chatgpt/xlsx/*.xlsx"))):
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        sheets = {}
        for ws in wb.worksheets:
            rows = [[("" if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]
            sheets[ws.title] = [r for r in rows if any(x.strip() for x in r)]
        head = " ".join(" ".join(r) for r in sheets.get("00_Дашборд", [])[:2])
        m = re.search(r"Актуализация:\s*(\d{2})\.(\d{2})\.(\d{4})", head)
        books.append({"file": Path(p).name, "plan_date": f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None,
                      "status": "ASSISTANT_HISTORICAL", "origin": "ChatGPT", "header": head, "sheets": sheets})
    return books


# ------------------------------------------------------------------ 3. master KB (structured extraction)
def kb_facts():
    F = []

    def add(key, value, status, region="RU", date=None, notes=""):
        F.append({"key": key, "value": value, "region": region, "source": SRC_KB, "confidence": CONF[status],
                  "balance_version": "chatgpt-history", "version_date": date or "UNKNOWN", "ru_status": "unverified",
                  "notes": f"import_status={status}; {notes}".strip("; ")})

    # rosters history (USER_OBSERVED, dated snapshots)
    add("user.roster@2025-10", {"Пандора": "11★", "Юла": "12★", "Селей": "11★", "Кристина": "12★", "Виньетта": "11★", "Клим": "11★"},
        "USER_OBSERVED", date="2025-10")
    add("user.team@2026-07", {"Виньетта": "13★", "Иллюсия": "11★", "Люцифер": "10★", "Клим": "11★", "Пандора": "13★", "Кристина": "13★"},
        "USER_OBSERVED", date="2026-07")
    add("user.bench@2026-07", {"Ундина": "11★", "Юла": "10★", "Харит": "10★", "Селей": "12★", "Эм": "10★", "Джин": "10★",
                               "Лотос": "10★", "Мей": "10★", "Брунина": "10★", "Лиядора": "10★"}, "USER_OBSERVED", date="2026-07")
    add("user.team@2026-08", {"Иллюсия": "11★ A9", "Виньетта": "13★", "Пандора": "13★", "Сеньерен": "10★ A0", "Люцифер": "11★ A19",
                              "Кристина": "13★"}, "USER_OBSERVED", date="2026-08")
    add("user.decoration_slots@2026-08", {"Кристина": 8, "Виньетта": 8, "Пандора": 8, "Люцифер": 6, "Иллюсия": 6, "Сеньерен": 5},
        "USER_OBSERVED", date="2026-08", notes="открытые слоты украшений на тот момент; не ограничение системы")
    add("user.spd@2026-08-17", {"Виньетта": 7616, "Кристина": 7435, "Пандора": 7392, "Иллюсия": 7234, "Люцифер": 7043},
        "USER_OBSERVED", date="2026-08-17")
    add("rules.awakening.lucifer_A19_needs_12star", True, "USER_OBSERVED", date="2026-08",
        notes="переход Люцифера за A19 требовал 12★")
    add("rules.talents.separate_format", "1+1", "USER_OBSERVED")
    add("rules.limbs.ru_alias", "Лимбы = система «Демон»", "USER_OBSERVED")
    add("hero.sbg:nurse-girl.role", "Поддержка (не маг)", "USER_OBSERVED", notes="исправлено оператором")
    # historical AI claims (never facts)
    for k, v in {"team.kira@2026-09": "Иллюсия — Кира — Верафиэль — Сеньерен — Люцифер — Хлоя",
                 "team.freeze@2026-09": "Иллюсия — Тессарион — Виньетта — Сеньерен — Люцифер — Юки Юки",
                 "team.target@2026-10-14": "Селестина — Серафия — Иллюсия — Сеньерен — Лирика — Кира",
                 "speed_order.kira_team": "Иллюсия → Кира → Верафиэль → Сеньерен → Люцифер → Хлоя",
                 "hero.sbg:chloe.dot_team_bonus": "+50% (A25: +60%)",
                 "hero.teselien.revive_A20_atk_pct": 2.16,
                 "hero.sbg:hymelle.execute_thr": "20% (A25: 22%)",
                 "talent.soul_eater.max_level": "36% шанс, запрет воскрешения 4 хода",
                 "hero.yuki.frost": "-5% СКР, -3% ЗАЩ за стак, до 5; 3 стака -> заморозка",
                 "hero.meylis.active": "134% ATK + 15% текущего HP",
                 "hero.sbg:mckenna.main_target_dmg": "до 494%, лечение до 50% от урона",
                 "hero.sbg:lilica.trap": "25% макс. HP Лирики истинным уроном; A20 добивание <30%",
                 "hero.sbg:yuuyou.preview": "тёмный воин, 8 эффектов, массовый урон до 400%, SS (предв.)",
                 "meta.presence@2026-08": "Иллюсия 8/8, Сеньерен 8/8, Мейлис 6/8, Люцифер 4/8, Клим 3/8 (выборка не сохранилась)",
                 "tier@2026-10": "Кира GOD, Лирика GOD, Селестина/Иллюсия/Сеньерен/Серафия META, Хлоя ~META, Юяо SS",
                 "hero.seraphia.first_revive_ignores_soul_eater": "первое воскрешение игнорирует запрет (не подтверждено)"}.items():
        add(k, v, "ASSISTANT_HISTORICAL")
    # regional name mappings from the export (provisional)
    for jp, ru in {"雲璟": "Селестин / Celestine", "雲韶": "Юнь Шао / предположительно Цинлуань", "幽瑶": "Юяо", "白鈴": "Бай Лин",
                   "凜火": "Маккенна / McKenna", "仙鶴娘": "Морозная Дымка (титул 霜嵐)", "結紗": "Юса", "陽菜": "Элнора",
                   "芹奈": "Сэрина / Serina", "由紀": "Юки", "エルザ": "Эльза / Ailsa", "リリカ": "Лилика / Лирика (Lyrica)",
                   "サエコ": "Саэко", "イヴ": "Ева / Ив", "アヌケト": "Аннукет", "ポリアンナ": "Поллианна", "オークリー": "Оукли / Окли",
                   "みもれもん": "Мимолемон (косплей-коллаборация, не отдельная героиня)", "妙音": "Химель / Hymelle",
                   "女部田郁子": "Икуко Онабута (Nukitashi)", "片桐奈々瀬": "Нанасэ Катагири (Nukitashi)",
                   "畔美岬": "Мисаки Хотори (Nukitashi)", "渡会ヒナミ": "Хинами Ватараи (Nukitashi)"}.items():
        add(f"name_map.{jp}", ru, "REGIONAL_PROVISIONAL")
    add("region.vn.title", "Yêu Quái, Chạy Đi Đâu…", "REGIONAL_PROVISIONAL", region="OTHER")
    add("region.en.rename", "Tales of Angels -> Idle Isekai Demons Tale (по EN-источникам)", "REGIONAL_PROVISIONAL", region="EN")
    add("fictional.game_design", "отдельный проект idle-RPG (24 героя, 40 карт) — FICTIONAL_GAME_DESIGN, не данные Luna Fantasy",
        "UNVERIFIED_HYPOTHESIS", notes="tag=FICTIONAL_GAME_DESIGN; не использовать для оценки клиента")
    return F


def main():
    pan, pfacts = panels()
    Path(ROOT / "data/user/panels").mkdir(parents=True, exist_ok=True)
    (ROOT / "data/user/panels/2026-11-01.json").write_text(json.dumps(pan, ensure_ascii=False, indent=1), encoding="utf-8")
    books = xlsx_dump()
    (ROOT / "data/kb/imports/chatgpt/xlsx_dump.json").write_text(json.dumps(books, ensure_ascii=False, indent=0), encoding="utf-8")
    kf = kb_facts()
    for name, rows in (("RU.observed.jsonl", pfacts), ("RU.chatgpt.jsonl", kf)):
        with open(ROOT / "data/kb/facts" / name, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"panels": len(pan), "panel_facts": len(pfacts), "xlsx_books": len(books),
                      "xlsx_rows": sum(len(r) for b in books for r in b["sheets"].values()), "kb_facts": len(kf)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
