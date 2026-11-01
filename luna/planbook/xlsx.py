"""Write the plan workbook. Scores are live Excel formulas driven by the sheet «Веса»; only the
CP-SAT assignments (cards, pets) and the simulator numbers are values - regenerate with `luna planbook`.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import terms as T
from .votes import SOURCES, TEAM

FONT = "Arial"
F_BASE = Font(name=FONT, size=10)
F_BOLD = Font(name=FONT, size=10, bold=True)
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=FONT, size=14, bold=True)
F_NOTE = Font(name=FONT, size=9, italic=True, color="555555")
F_INPUT = Font(name=FONT, size=10, color="0000FF")
F_LINK = Font(name=FONT, size=10, color="008000")
FILL_HEAD = PatternFill("solid", fgColor="2F4858")
FILL_INPUT = PatternFill("solid", fgColor="FFFF00")
FILL_SEC = PatternFill("solid", fgColor="DDE6ED")
FILL_WARN = PatternFill("solid", fgColor="FCE4D6")
THIN = Border(bottom=Side(style="thin", color="BBBBBB"))
WRAP = Alignment(wrap_text=True, vertical="top")
CAT_RU = {"sigil": "Сигил (刻印)", "personal": "Личный талант", "limb": "Лимбы (демоны) 4/4", "substat_13": "Допстат лимба, слоты 1·3",
          "substat_24": "Допстат лимба, слоты 2·4", "pet": "Питомец", "accessory": "Украшение", "card": "Карта прелестей",
          "rune": "Руна", "pw": "Оружие принцессы", "tier": "Тир героини"}
MAP_RU = {"lfru_alias": "подтверждено (lunafantasy.ru)", "meaning": "перевод по смыслу", "hypothesis": "гипотеза — на согласование",
          "unmapped": "нет соответствия"}
GROUP_RU = {"main": "основная рекомендация", "list": "в списке (по порядку)", "candidate": "кандидат / второй приоритет",
            "avoid": "не рекомендуется (☓)"}


def _hdr(ws, row, cols, widths=None):
    for j, name in enumerate(cols, 1):
        c = ws.cell(row=row, column=j, value=name)
        c.font, c.fill, c.alignment = F_HEAD, FILL_HEAD, Alignment(wrap_text=True, vertical="center")
    if widths:
        for j, wdt in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = wdt


def _title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = F_TITLE
    if sub:
        ws["A2"] = sub
        ws["A2"].font = F_NOTE


def _arial(ws):
    """Cells written without an explicit font get Arial 10 (keeps bold/colour fonts already set)."""
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None and c.font.name != FONT:
                c.font = F_BASE


def entity_desc(kind: str, suf: str) -> str:
    for x in T.entities():
        if x["id"] == f"{kind}:{suf}":
            eff = "; ".join(f"{e['label']}: {e['text']}" for e in x.get("effects", [])[:2] if e.get("text"))
            return (eff or x.get("summary") or "")[:300]
    return ""


KIND = {"limb": "limb", "pet": "pet", "accessory": "accessory", "card": "charm-card", "rune": "rune", "pw": "princess-weapon"}


def write(res: dict, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    names, team, order = res["names"], res["team"], res["order"]
    w = res["weights"]
    today = res["today"]

    # ------------------------------------------------------------------ README
    ws = wb.active
    ws.title = "README"
    _title(ws, "LUNA FANTASY — план развития пачки с весами источников и модели",
           f"Сгенерировано {today.isoformat()} командой `luna planbook`. Команда: {res['team_name']}.")
    lines = [
        ("Что это", "Книга повторяет структуру ваших планов (дашборд, сигилы/таланты, лимбы, украшения, карты, питомцы, руны, оружие "
                    "принцессы), но каждая рекомендация получена из «голосов» источников с явными весами и формулами."),
        ("Как считается вес", "Вес голоса = Вес источника × Вес группы (основная/кандидат/☓) × Вес сопоставления имени × Позиция × "
                              "Рейтинг (★, x/5) × Свежесть. Свежесть = max(пол; 0.5^(возраст/период полураспада))."),
        ("Итог кандидата", "Консенсус = сумма весов голосов → нормировка к лучшему кандидату героини в категории. Если у кандидата "
                           "есть статистически значимый модельный эффект симулятора, Итог = (α·Консенсус + β·Модель)/(α+β)."),
        ("Что можно менять", "Только ЖЁЛТЫЕ ячейки с СИНИМ шрифтом на листе «Веса». Все баллы, ранги и выбор лучших пересчитаются "
                             "автоматически. Назначения с ограничениями (карты без повторов, питомцы с лимитом связей) — результат "
                             "оптимизатора CP-SAT на момент генерации: после изменения весов перезапустите генератор."),
        ("Приоритет источников", "По просьбе оператора японские источники (AppMedia, surrounded-by-girls) имеют наибольший вес 1.0; "
                                 "lunafantasy.ru 0.7; планы ChatGPT 0.3 (исторические); слабые априорные голоса 0.25–0.3."),
        ("Важно про AppMedia", "Большинство страниц AppMedia последний раз обновлялись в мае–июне 2025 года, поэтому множитель "
                               "свежести у них низкий. Если считаете их актуальными — увеличьте «Период полураспада» на листе «Веса»."),
        ("Модель", "Модельные значения — результат симулятора проекта (НЕ реальный винрейт, симулятор не откалиброван). Учитываются "
                   "только статистически значимые эффекты (95% ДИ не пересекает 0). Подробности — лист «Модель»."),
        ("Имена", "Японские названия сопоставлены с русскими. Спорные соответствия отмечены как «гипотеза» (вес ×0.75) и вынесены "
                  "на лист «Сопоставление_JP_RU» для вашего решения."),
        ("Правила", "Сигилы (2×2) и личные таланты (2) считаются отдельно и не объединяются; лимбы = «демоны»; дубли таланта в "
                    "сигиле и личном таланте помечаются ⚠. Неизвестное не выдумывается: нет данных — «—»."),
        ("Обновление", "python -m luna planbook  (или python -m luna.planbook.build) — пересобирает голоса, модель и книгу."),
    ]
    for i, (k, v) in enumerate(lines, 4):
        ws.cell(row=i, column=1, value=k).font = F_BOLD
        c = ws.cell(row=i, column=2, value=v)
        c.font, c.alignment = F_BASE, WRAP
        ws.row_dimensions[i].height = 42
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 120
    ws.cell(row=16, column=1, value="Легенда").font = F_BOLD
    c = ws.cell(row=17, column=1, value="Пример ввода")
    c.font, c.fill = F_INPUT, FILL_INPUT
    ws.cell(row=17, column=2, value="жёлтая ячейка с синим шрифтом — вводимое значение (лист «Веса»)").font = F_BASE
    ws.cell(row=18, column=1, value="=Веса!B5").font = F_LINK
    ws.cell(row=18, column=2, value="зелёный шрифт — ссылка на другой лист; чёрный — формула; значения симулятора и CP-SAT — "
                                    "обычные числа с примечанием").font = F_BASE

    # ------------------------------------------------------------------ Веса
    wv = wb.create_sheet("Веса")
    _title(wv, "ВЕСА И ПАРАМЕТРЫ (редактируемые)", "Меняйте только жёлтые ячейки. Значения по умолчанию — предложение, не факт.")
    ref = {}
    r = 4
    _hdr(wv, r, ["Источник (id)", "Название", "Регион", "Вес", "Примечание"], [16, 46, 9, 9, 90])
    src_rows = (r + 1, r + len(SOURCES))
    for i, (sid, (nm, reg, url, wt, note)) in enumerate(SOURCES.items(), r + 1):
        wv.cell(row=i, column=1, value=sid)
        wv.cell(row=i, column=2, value=nm)
        wv.cell(row=i, column=3, value=reg)
        c = wv.cell(row=i, column=4, value=w["source"][sid])
        c.font, c.fill = F_INPUT, FILL_INPUT
        wv.cell(row=i, column=5, value=f"{note}. {url}")
    ref["src_id"] = f"Веса!$A${src_rows[0]}:$A${src_rows[1]}"
    ref["src_w"] = f"Веса!$D${src_rows[0]}:$D${src_rows[1]}"
    ref["src_reg"] = f"Веса!$C${src_rows[0]}:$C${src_rows[1]}"

    def table(start, title, rows, key):
        _hdr_cells = [title, "Вес", "Пояснение"]
        for j, name in enumerate(_hdr_cells, 1):
            c = wv.cell(row=start, column=j, value=name)
            c.font, c.fill = F_HEAD, FILL_HEAD
        for i, (k, v, note) in enumerate(rows, start + 1):
            wv.cell(row=i, column=1, value=k)
            c = wv.cell(row=i, column=2, value=v)
            c.font, c.fill = F_INPUT, FILL_INPUT
            wv.cell(row=i, column=3, value=note)
        ref[key + "_k"] = f"Веса!$A${start + 1}:$A${start + len(rows)}"
        ref[key + "_v"] = f"Веса!$B${start + 1}:$B${start + len(rows)}"
        return start + len(rows) + 2

    r = src_rows[1] + 2
    r = table(r, "Группа голоса", [(g, w["group"][g], GROUP_RU[g]) for g in w["group"]], "grp")
    r = table(r, "Сопоставление имени", [(m, w["map"][m], MAP_RU[m]) for m in w["map"]], "map")
    r = table(r, "Тир", [(t, w["tier"][t], "балл тира героини") for t in w["tier"]], "tier")
    params = [("gamma", w["gamma"], "затухание по позиции: позиция k даёт 1/(1+γ·(k−1))"),
              ("half_life", w["half_life"], "период полураспада свежести, дней"),
              ("recency_floor", w["recency_floor"], "минимальный множитель свежести"),
              ("alpha", w["alpha"], "вес консенсуса источников в итоге"),
              ("beta", w["beta"], "вес модели симулятора в итоге (только значимые эффекты)"),
              ("model_sig_only", 1, "1 = учитывать только статистически значимые модельные эффекты; 0 = все"),
              ("hero_w_tier", w["hero_w_tier"], "оценка героини: вес тира (AppMedia/SBG)"),
              ("hero_w_model", w["hero_w_model"], "оценка героини: вес вклада кита в модели"),
              ("hero_w_ready", w["hero_w_ready"], "оценка героини: вес прокачки в ростере"),
              ("max_stars", 15, "звёзды для нормировки прокачки (допущение)"),
              ("max_awakening", 30, "пробуждение для нормировки прокачки (допущение)"),
              ("today", today, "дата расчёта свежести")]
    for j, name in enumerate(["Параметр", "Значение", "Пояснение"], 1):
        c = wv.cell(row=r, column=j, value=name)
        c.font, c.fill = F_HEAD, FILL_HEAD
    for i, (k, v, note) in enumerate(params, r + 1):
        wv.cell(row=i, column=1, value=k)
        c = wv.cell(row=i, column=2, value=v)
        c.font, c.fill = F_INPUT, FILL_INPUT
        if k == "today":
            c.number_format = "yyyy-mm-dd"
        wv.cell(row=i, column=3, value=note)
        ref[k] = f"Веса!$B${i}"
    r = r + len(params) + 2
    wv.cell(row=r, column=1, value="Питомцы: лимит связей одного 5★ питомца по редкости (правило из планов ChatGPT, НЕ подтверждено)").font = F_BOLD
    for i, (k, v) in enumerate(w["pet_cap"].items(), r + 1):
        wv.cell(row=i, column=1, value=k)
        c = wv.cell(row=i, column=2, value=v)
        c.font, c.fill = F_INPUT, FILL_INPUT
        wv.cell(row=i, column=3, value="используется оптимизатором CP-SAT при генерации")
    _arial(wv)
    wv.freeze_panes = "A5"

    # ------------------------------------------------------------------ Голоса
    wg = wb.create_sheet("Голоса")
    cols = ["Героиня (id)", "Героиня", "Категория", "Кандидат (ключ)", "Название RU", "Оригинал", "Источник", "Регион",
            "Дата", "Группа", "Позиция", "Рейтинг", "Сопоставление", "W источник", "W группа", "W сопост.", "W позиция",
            "Свежесть", "W рейтинг", "Вес без рейтинга", "Вес голоса", "Примечание", "Ссылка"]
    _hdr(wg, 1, cols, [14, 14, 12, 26, 26, 18, 10, 8, 11, 10, 8, 8, 12, 9, 9, 9, 9, 9, 9, 10, 10, 40, 40])
    votes = res["votes"]
    for i, v in enumerate(votes, 2):
        vals = [v["hero"], names.get(v["hero"], v["hero"]), v["cat"], v["cand"], v["name_ru"], v["name_orig"], v["source"],
                f"=IFERROR(INDEX({ref['src_reg']},MATCH(G{i},{ref['src_id']},0)),\"\")",
                dt.date.fromisoformat(v["date"]), v["group"], v["pos"],
                v["rating"] if v["rating"] is not None else None, v["map_status"],
                f"=INDEX({ref['src_w']},MATCH(G{i},{ref['src_id']},0))",
                f"=INDEX({ref['grp_v']},MATCH(J{i},{ref['grp_k']},0))",
                f"=INDEX({ref['map_v']},MATCH(M{i},{ref['map_k']},0))",
                f"=1/(1+{ref['gamma']}*(K{i}-1))",
                f"=MAX({ref['recency_floor']},POWER(0.5,({ref['today']}-I{i})/{ref['half_life']}))",
                f"=IF(C{i}=\"tier\",IFERROR(INDEX({ref['tier_v']},MATCH(L{i},{ref['tier_k']},0)),0),IF(L{i}=\"\",1,L{i}))",
                f"=N{i}*O{i}*P{i}*Q{i}*R{i}", f"=T{i}*S{i}", v["note"], v["url"]]
        for j, val in enumerate(vals, 1):
            c = wg.cell(row=i, column=j, value=val)
            c.font = F_BASE
        wg.cell(row=i, column=9).number_format = "yyyy-mm-dd"
        for j in range(14, 22):
            wg.cell(row=i, column=j).number_format = "0.000"
    nv = len(votes) + 1
    wg.freeze_panes = "E2"
    wg.auto_filter.ref = f"A1:W{nv}"
    G = {k: f"Голоса!${col}$2:${col}${nv}" for k, col in
         (("hero", "A"), ("cat", "C"), ("cand", "D"), ("src", "G"), ("base", "T"), ("vw", "U"))}

    # ------------------------------------------------------------------ Кандидаты
    wk = wb.create_sheet("Кандидаты")
    cols = ["Героиня (id)", "Героиня", "Категория", "Кандидат (ключ)", "Название RU", "Сопоставление", "Источники", "Голосов",
            "Консенсус", "Консенсус (норм.)", "Модель Δ", "Значимо", "Модель учитывается", "Модель (норм.)", "Итог",
            "Ранг", "№", "Ключ ранга", "Ключ кандидата", "Описание"]
    _hdr(wk, 1, cols, [14, 14, 12, 26, 28, 14, 22, 8, 10, 10, 10, 8, 10, 10, 9, 6, 6, 30, 40, 60])
    cands = res["cands"]
    nk = len(cands) + 1
    K = {k: f"Кандидаты!${col}$2:${col}${nk}" for k, col in
         (("hero", "A"), ("cat", "C"), ("cand", "D"), ("name", "E"), ("final", "O"), ("rank", "P"), ("key", "R"),
          ("key2", "S"), ("src", "G"), ("cons", "I"))}
    L = {k: f"${col}$2:${col}${nk}" for k, col in (("A", "A"), ("C", "C"), ("I", "I"), ("K", "K"), ("M", "M"), ("O", "O"), ("Q", "Q"))}
    for i, c in enumerate(cands, 2):
        desc = entity_desc(KIND.get(c["cat"], ""), c["cand"]) if c["cat"] in KIND else ""
        vals = [c["hero"], names.get(c["hero"], c["hero"]), c["cat"], c["cand"], c["name_ru"], c["map_status"], c["sources"],
                f"=COUNTIFS({G['hero']},A{i},{G['cat']},C{i},{G['cand']},D{i})",
                f"=SUMIFS({G['vw']},{G['hero']},A{i},{G['cat']},C{i},{G['cand']},D{i})",
                f"=IF(_xlfn.MAXIFS({L['I']},{L['A']},A{i},{L['C']},C{i})>0,I{i}/_xlfn.MAXIFS({L['I']},{L['A']},A{i},{L['C']},C{i}),0)",
                c["model_raw"], c["model_sig"],
                f"=IF(K{i}=\"\",0,IF(OR({ref['model_sig_only']}=0,L{i}=1),1,0))",
                f"=IF(M{i}=0,\"\",IF(_xlfn.MAXIFS({L['K']},{L['A']},A{i},{L['C']},C{i},{L['M']},1)>_xlfn.MINIFS({L['K']},{L['A']},A{i},{L['C']},C{i},{L['M']},1),"
                f"(K{i}-_xlfn.MINIFS({L['K']},{L['A']},A{i},{L['C']},C{i},{L['M']},1))/(_xlfn.MAXIFS({L['K']},{L['A']},A{i},{L['C']},C{i},{L['M']},1)"
                f"-_xlfn.MINIFS({L['K']},{L['A']},A{i},{L['C']},C{i},{L['M']},1)),0.5))",
                f"=ROUND(IF(N{i}=\"\",J{i},({ref['alpha']}*J{i}+{ref['beta']}*N{i})/({ref['alpha']}+{ref['beta']})),6)",
                f"=1+COUNTIFS({L['A']},A{i},{L['C']},C{i},{L['O']},\">\"&O{i})+COUNTIFS({L['A']},A{i},{L['C']},C{i},{L['O']},O{i},{L['Q']},\"<\"&Q{i})",
                c["row"], f"=A{i}&\"|\"&C{i}&\"|\"&P{i}", f"=A{i}&\"|\"&C{i}&\"|\"&D{i}", desc]
        for j, val in enumerate(vals, 1):
            cell = wk.cell(row=i, column=j, value=val)
            cell.font = F_BASE
        for j in (9, 10, 11, 14, 15):
            wk.cell(row=i, column=j).number_format = "0.000"
        if c["model_raw"] is not None:
            wk.cell(row=i, column=11).comment = Comment("Симулятор проекта, парный Монте-Карло (лист «Модель»). Не реальный винрейт.", "luna")
    wk.freeze_panes = "F2"
    wk.auto_filter.ref = f"A1:T{nk}"

    def pick(hero_cell, cat, k, what="name"):
        col = K["name"] if what == "name" else K["final"]
        dflt = '"—"' if what == "name" else '""'
        return f"=IFERROR(INDEX({col},MATCH({hero_cell}&\"|{cat}|{k}\",{K['key']},0)),{dflt})"

    def score_of(hero_cell, cat, cand_key):
        return f"=IFERROR(INDEX({K['final']},MATCH({hero_cell}&\"|{cat}|{cand_key}\",{K['key2']},0)),\"\")"

    # ------------------------------------------------------------------ Героини
    wh = wb.create_sheet("Героини")
    _title(wh, "ГЕРОИНИ: тир источников, вклад кита в модели, прокачка", "Оценка = взвешенное среднее доступных компонент (веса — лист «Веса»).")
    cols = ["Героиня (id)", "Героиня", "В команде", "Звёзды", "Пробуждение", "Тир AppMedia", "Тир SBG", "Тир-балл",
            "Модель: Δ без навыков", "95% ДИ", "Значимо", "Вклад кита (норм.)", "Прокачка (норм.)", "Оценка"]
    _hdr(wh, 4, cols, [14, 16, 9, 8, 11, 11, 9, 9, 13, 20, 8, 12, 12, 9])
    tier_src = {}
    for v in votes:
        if v["cat"] == "tier":
            tier_src.setdefault(v["hero"], {})[v["source"]] = v["rating"]
    heroes = list(dict.fromkeys(team + sorted(h for h in tier_src if h not in team)))
    kit = res["model"].get("kit", {})
    nh = 4 + len(heroes)
    for i, h in enumerate(heroes, 5):
        ro = res["roster"].get(h, {})
        stars = ro.get("stars") if isinstance(ro.get("stars"), int) else None
        awk = ro.get("awakening") if isinstance(ro.get("awakening"), int) else None
        kd = kit.get(h)
        sig = None if not kd else (1 if (kd["ci95"][0] > 0 or kd["ci95"][1] < 0) else 0)
        vals = [h, names.get(h, h), "да" if h in team else "", stars, awk, tier_src.get(h, {}).get("appmedia"),
                tier_src.get(h, {}).get("sbg"),
                f"=IFERROR(SUMIFS({G['vw']},{G['hero']},A{i},{G['cat']},\"tier\")/SUMIFS({G['base']},{G['hero']},A{i},{G['cat']},\"tier\"),\"\")",
                kd["delta"] if kd else None, f"{kd['ci95'][0]:+.3f} … {kd['ci95'][1]:+.3f}" if kd else None, sig,
                f"=IF(OR(I{i}=\"\",AND({ref['model_sig_only']}=1,K{i}<>1)),\"\",IF(MAX($I$5:$I${nh})>MIN($I$5:$I${nh}),"
                f"(MAX($I$5:$I${nh})-I{i})/(MAX($I$5:$I${nh})-MIN($I$5:$I${nh})),0.5))",
                f"=IF(OR(D{i}=\"\",E{i}=\"\"),\"\",(MIN(1,D{i}/{ref['max_stars']})+MIN(1,E{i}/{ref['max_awakening']}))/2)",
                f"=IFERROR((IF(H{i}=\"\",0,{ref['hero_w_tier']}*H{i})+IF(L{i}=\"\",0,{ref['hero_w_model']}*L{i})+IF(M{i}=\"\",0,{ref['hero_w_ready']}*M{i}))"
                f"/(IF(H{i}=\"\",0,{ref['hero_w_tier']})+IF(L{i}=\"\",0,{ref['hero_w_model']})+IF(M{i}=\"\",0,{ref['hero_w_ready']})),\"\")"]
        for j, val in enumerate(vals, 1):
            wh.cell(row=i, column=j, value=val).font = F_BASE
        for j in (8, 9, 12, 13, 14):
            wh.cell(row=i, column=j).number_format = "0.000"
    wh.freeze_panes = "C5"
    HS = {"hero": f"Героини!$A$5:$A${nh}", "score": f"Героини!$N$5:$N${nh}", "tier": f"Героини!$H$5:$H${nh}"}

    # ------------------------------------------------------------------ 00_Дашборд
    wd = wb.create_sheet("00_Дашборд", 1)
    _title(wd, f"LUNA FANTASY — ПЛАН РАЗВИТИЯ: {res['team_name']}",
           f"Актуализация: {today.isoformat()} • веса: JP 1.0 / RU 0.7 / ChatGPT 0.3 • порядок — по СКР панели оператора (без панели — в конце)")
    cols = ["Ход", "Героиня (id)", "Дева", "СКР (панель)", "Оценка героини", "Лимбы 4/4", "Карта прелести", "Сигил 1",
            "Сигил 2", "Таланты 1+1", "Питомцы (4)", "Внимание"]
    _hdr(wd, 4, cols, [5, 12, 14, 11, 10, 22, 20, 30, 30, 30, 50, 30])
    pets_text = {h: " · ".join(p["name_ru"] for p in res["pets"].get(h, [])) or "—" for h in team}
    for i, h in enumerate(order, 5):
        vals = [i - 4, h, names.get(h, h), res["spd"].get(h),
                f"=IFERROR(INDEX({HS['score']},MATCH(B{i},{HS['hero']},0)),\"\")",
                pick(f"B{i}", "limb", 1),
                f"=IFERROR(INDEX('05_Карты_прелести'!$C$5:$C${4 + len(team)},MATCH(B{i},'05_Карты_прелести'!$A$5:$A${4 + len(team)},0)),\"—\")",
                f"={pick(f'B{i}', 'sigil', 1)[1:]}&\" + \"&{pick(f'B{i}', 'sigil', 2)[1:]}",
                f"={pick(f'B{i}', 'sigil', 3)[1:]}&\" + \"&{pick(f'B{i}', 'sigil', 4)[1:]}",
                f"={pick(f'B{i}', 'personal', 1)[1:]}&\" + \"&{pick(f'B{i}', 'personal', 2)[1:]}",
                pets_text[h],
                f"=IFERROR(INDEX('01_Сигилы_таланты'!$P$5:$P${4 + len(team)},MATCH(B{i},'01_Сигилы_таланты'!$A$5:$A${4 + len(team)},0)),\"\")"]
        for j, val in enumerate(vals, 1):
            c = wd.cell(row=i, column=j, value=val)
            c.font, c.alignment = F_BASE, WRAP
        wd.cell(row=i, column=5).number_format = "0.000"
        wd.cell(row=i, column=4).number_format = "#,##0"
    r = 6 + len(team)
    notes = ["Как читать: в каждой ячейке — кандидат с наибольшим итоговым весом (лист «Кандидаты»). Ранги пересчитываются при изменении «Весов».",
             "Сигил 1 = 1-й и 2-й по весу таланты сигилов, Сигил 2 = 3-й и 4-й. Личные таланты считаются отдельно (не объединяются с сигилами).",
             "«—» означает, что ни один источник не дал рекомендации для этой героини в этой категории.",
             "Модельные числа — оценка симулятора (не откалиброван, не реальный винрейт)."]
    for k, t in enumerate(notes):
        c = wd.cell(row=r + k, column=1, value=t)
        c.font = F_NOTE
    wd.freeze_panes = "D5"

    # ------------------------------------------------------------------ 01_Сигилы_таланты
    ws1 = wb.create_sheet("01_Сигилы_таланты", 2)
    _title(ws1, "СИГИЛЫ (2×2) И ЛИЧНЫЕ ТАЛАНТЫ (2) — ПО ВЕСУ",
           "Сигилы и личные таланты — разные системы; одинаковый эффект в обеих помечается ⚠ (дубли не суммируются).")
    cols = ["Героиня (id)", "Дева", "Сигил 1 — 1", "вес", "Сигил 1 — 2", "вес", "Сигил 2 — 1", "вес", "Сигил 2 — 2", "вес",
            "Талант 1", "вес", "Талант 2", "вес", "5-й кандидат сигила", "Проверка"]
    _hdr(ws1, 4, cols, [12, 14, 18, 7, 18, 7, 18, 7, 18, 7, 18, 7, 18, 7, 18, 34])
    for i, h in enumerate(order, 5):
        vals = [h, names.get(h, h)]
        for k in range(1, 5):
            vals += [pick(f"A{i}", "sigil", k), pick(f"A{i}", "sigil", k, "score")]
        for k in range(1, 3):
            vals += [pick(f"A{i}", "personal", k), pick(f"A{i}", "personal", k, "score")]
        vals += [pick(f"A{i}", "sigil", 5),
                 f"=IF(OR(AND(K{i}<>\"—\",COUNTIF(C{i}:J{i},K{i})>0),AND(M{i}<>\"—\",COUNTIF(C{i}:J{i},M{i})>0)),\"⚠ дубль сигил/талант\","
                 f"IF(C{i}=\"—\",\"нет рекомендаций сигилов\",\"ок\"))"]
        for j, val in enumerate(vals, 1):
            ws1.cell(row=i, column=j, value=val).font = F_BASE
        for j in range(4, 15, 2):
            ws1.cell(row=i, column=j).number_format = "0.00"
    ws1.freeze_panes = "C5"

    # ------------------------------------------------------------------ 02_Лимбы
    ws2 = wb.create_sheet("02_Лимбы", 3)
    _title(ws2, "ЛИМБЫ («ДЕМОНЫ»): НАБОР 4/4 И ДОПСТАТЫ", "Модель оценивает только бонус 2 частей (простой стат); эффект 4 частей не закодирован.")
    cols = ["Героиня (id)", "Дева", "Набор №1", "вес", "Набор №2", "вес", "Набор №3", "вес", "Эффект набора №1",
            "Слоты 1·3: допстат 1", "2", "3", "Слоты 2·4: допстат 1", "2", "3"]
    _hdr(ws2, 4, cols, [12, 14, 20, 7, 20, 7, 20, 7, 60, 16, 16, 16, 20, 20, 20])
    for i, h in enumerate(order, 5):
        vals = [h, names.get(h, h)]
        for k in range(1, 4):
            vals += [pick(f"A{i}", "limb", k), pick(f"A{i}", "limb", k, "score")]
        vals.append(f"=IFERROR(T(INDEX(Кандидаты!$T$2:$T${nk},MATCH(A{i}&\"|limb|1\",{K['key']},0))),\"\")")
        vals += [pick(f"A{i}", "substat_13", k) for k in range(1, 4)] + [pick(f"A{i}", "substat_24", k) for k in range(1, 4)]
        for j, val in enumerate(vals, 1):
            c = ws2.cell(row=i, column=j, value=val)
            c.font, c.alignment = F_BASE, WRAP
        for j in (4, 6, 8):
            ws2.cell(row=i, column=j).number_format = "0.00"
    ws2.freeze_panes = "C5"

    # ------------------------------------------------------------------ 03_Аксессуары
    ws3 = wb.create_sheet("03_Аксессуары", 4)
    _title(ws3, "УКРАШЕНИЯ: 8 СЛОТОВ НА КАЖДУЮ ДЕВУ — ПО ВЕСУ", "Источники: SBG (2 героини), планы ChatGPT; список lunafantasy.ru одинаков для всех и не считается рекомендацией.")
    _hdr(ws3, 4, ["Героиня (id)", "Дева", "Приоритет", "Украшение", "Вес", "Очки (9−приоритет)"], [12, 14, 9, 44, 8, 10])
    r = 5
    for h in order:
        for k in range(1, 9):
            vals = [h, names.get(h, h), k, pick(f"A{r}", "accessory", k), pick(f"A{r}", "accessory", k, "score"),
                    f"=IF(D{r}=\"—\",0,9-C{r})"]
            for j, val in enumerate(vals, 1):
                ws3.cell(row=r, column=j, value=val).font = F_BASE
            ws3.cell(row=r, column=5).number_format = "0.00"
            r += 1
    acc_last = r - 1
    ws3.freeze_panes = "D5"

    # ------------------------------------------------------------------ 04_Качать_украшения
    ws4 = wb.create_sheet("04_Качать_украшения", 5)
    _title(ws4, "ПРИОРИТЕТ ПРОКАЧКИ УКРАШЕНИЙ ДО 5★", "Командный балл = сумма очков позиций (№1 = 8 … №8 = 1) по листу «03_Аксессуары».")
    _hdr(ws4, 4, ["Украшение", "Нужно копий (дев)", "Командный балл", "Сумма весов", "Ранг"], [44, 14, 14, 12, 8])
    accs = sorted({c["name_ru"] for c in res["cands"] if c["cat"] == "accessory" and c["hero"] in team})
    n4 = 4 + len(accs)
    for i, a in enumerate(accs, 5):
        vals = [a, f"=COUNTIF('03_Аксессуары'!$D$5:$D${acc_last},A{i})",
                f"=SUMIFS('03_Аксессуары'!$F$5:$F${acc_last},'03_Аксессуары'!$D$5:$D${acc_last},A{i})",
                f"=SUMIFS('03_Аксессуары'!$E$5:$E${acc_last},'03_Аксессуары'!$D$5:$D${acc_last},A{i})",
                f"=IF(C{i}=0,\"\",1+COUNTIF($C$5:$C${n4},\">\"&C{i}))"]
        for j, val in enumerate(vals, 1):
            ws4.cell(row=i, column=j, value=val).font = F_BASE
        ws4.cell(row=i, column=4).number_format = "0.00"

    # ------------------------------------------------------------------ 05_Карты_прелести
    ws5 = wb.create_sheet("05_Карты_прелести", 6)
    _title(ws5, "КАРТЫ ПРЕЛЕСТИ: ОДНА НА ДЕВУ, БЕЗ ПОВТОРОВ В СОСТАВЕ (CP-SAT)",
           "Выбор — результат оптимизатора на момент генерации; «Вес сейчас» и «Лучшая по весу» пересчитываются формулами.")
    _hdr(ws5, 4, ["Героиня (id)", "Дева", "Карта (CP-SAT)", "Ключ", "Вес сейчас", "Лучшая по весу без ограничения", "вес",
                  "Повтор в составе", "Описание"], [12, 14, 22, 22, 9, 26, 7, 14, 60])
    for i, h in enumerate(team, 5):
        cc = res["cards"].get(h)
        vals = [h, names.get(h, h), cc["name_ru"] if cc else "—", cc["cand"] if cc else "",
                score_of(f"A{i}", "card", cc["cand"]) if cc else "", pick(f"A{i}", "card", 1), pick(f"A{i}", "card", 1, "score"),
                f"=IF(C{i}=\"—\",\"\",IF(COUNTIF($C$5:$C${4 + len(team)},C{i})>1,\"⚠ повтор\",\"ок\"))",
                entity_desc("charm-card", cc["cand"]) if cc else ""]
        for j, val in enumerate(vals, 1):
            c = ws5.cell(row=i, column=j, value=val)
            c.font, c.alignment = F_BASE, WRAP
        ws5.cell(row=i, column=5).number_format = "0.00"
        ws5.cell(row=i, column=7).number_format = "0.00"
        ws5.cell(row=i, column=3).comment = Comment("Назначение CP-SAT: максимум суммы весов при условии «одна карта — одна дева».", "luna")

    # ------------------------------------------------------------------ 06_Синергия (исторические заметки)
    ws6 = wb.create_sheet("06_Синергия", 7)
    _title(ws6, "СИНЕРГИЯ (ИСТОРИЧЕСКИЕ ЗАМЕТКИ ChatGPT, НИЗКАЯ ДОСТОВЕРНОСТЬ)",
           "Текст скопирован из последнего плана ChatGPT, где встречаются героини команды; в веса не входит.")
    ws6.cell(row=4, column=1, value="Пары и тексты — см. лист 06 в исходных XLSX (data/kb/imports/chatgpt/xlsx). "
                                    "Модельная оценка синергии пар не выполнялась: для этого нужны закодированные киты всех героинь.").font = F_NOTE

    # ------------------------------------------------------------------ 08_Питомцы
    ws8 = wb.create_sheet("08_Питомцы", 8)
    _title(ws8, "ПИТОМЦЫ: 4 НА ДЕВУ (CP-SAT, лимит связей по редкости — допущение)",
           "Выбор — оптимизатор на момент генерации; лимиты связей из планов ChatGPT НЕ подтверждены (лист «Веса»).")
    _hdr(ws8, 4, ["Героиня (id)", "Дева", "Питомец №1", "вес", "Питомец №2", "вес", "Питомец №3", "вес", "Питомец №4", "вес",
                  "Источники питомца №1"], [12, 14, 22, 7, 22, 7, 22, 7, 22, 7, 30])
    for i, h in enumerate(team, 5):
        vals = [h, names.get(h, h)]
        ps = res["pets"].get(h, [])
        for k in range(4):
            if k < len(ps):
                vals += [ps[k]["name_ru"], score_of(f"A{i}", "pet", ps[k]["cand"])]
            else:
                vals += ["—", ""]
        vals.append(f"=IFERROR(T(INDEX({K['src']},MATCH(A{i}&\"|pet|{ps[0]['cand']}\",{K['key2']},0))),\"\")" if ps else "")
        for j, val in enumerate(vals, 1):
            ws8.cell(row=i, column=j, value=val).font = F_BASE
        for j in (4, 6, 8, 10):
            ws8.cell(row=i, column=j).number_format = "0.00"
    r = 6 + len(team)
    _hdr_row = ["Питомец", "Редкость", "Связей в плане", "Лимит", "Проверка"]
    for j, name in enumerate(_hdr_row, 1):
        c = ws8.cell(row=r, column=j, value=name)
        c.font, c.fill = F_HEAD, FILL_HEAD
    used = sorted({p["name_ru"]: p["cand"] for h in team for p in res["pets"].get(h, [])}.items())
    cap_cells = {k: i for i, k in enumerate(w["pet_cap"], 0)}
    for i, (nm, key) in enumerate(used, r + 1):
        rar = res["rarity"].get(key, "")
        vals = [nm, rar, f"=COUNTIF($C$5:$C${4 + len(team)},A{i})+COUNTIF($E$5:$E${4 + len(team)},A{i})+"
                         f"COUNTIF($G$5:$G${4 + len(team)},A{i})+COUNTIF($I$5:$I${4 + len(team)},A{i})",
                w["pet_cap"].get(rar, ""), f"=IF(D{i}=\"\",\"\",IF(C{i}<=D{i},\"ок\",\"⚠ превышен лимит\"))"]
        for j, val in enumerate(vals, 1):
            ws8.cell(row=i, column=j, value=val).font = F_BASE

    # ------------------------------------------------------------------ 11_Руны / 12_Оружие
    for sname, cat, title, sub in (("11_Руны", "rune", "4 СЛОТА РУН — ПОРЯДОК ПО ВЕСУ",
                                    "Источники: планы ChatGPT (порядок слотов) + класс руны на lunafantasy.ru. Порядок = убывание итогового веса."),
                                   ("12_Оружие_принцессы", "pw", "ОРУЖИЕ ПРИНЦЕССЫ — ПРИОРИТЕТ ПО ВЕСУ",
                                    "Источники: планы ChatGPT + класс оружия на lunafantasy.ru.")):
        wsx = wb.create_sheet(sname)
        _title(wsx, title, sub)
        _hdr(wsx, 4, ["Место", "Название", "Вес", "Источники", "Описание"], [8, 28, 9, 26, 70])
        wsx["G4"] = TEAM
        wsx["G4"].font = F_NOTE
        for i, k in enumerate(range(1, 7), 5):
            vals = [k, pick("$G$4", cat, k), pick("$G$4", cat, k, "score"),
                    f"=IFERROR(T(INDEX({K['src']},MATCH($G$4&\"|{cat}|{k}\",{K['key']},0))),\"\")",
                    f"=IFERROR(T(INDEX(Кандидаты!$T$2:$T${nk},MATCH($G$4&\"|{cat}|{k}\",{K['key']},0))),\"\")"]
            for j, val in enumerate(vals, 1):
                c = wsx.cell(row=i, column=j, value=val)
                c.font, c.alignment = F_BASE, WRAP
            wsx.cell(row=i, column=3).number_format = "0.00"

    # ------------------------------------------------------------------ Модель
    wm = wb.create_sheet("Модель")
    m = res["model"]
    _title(wm, "МОДЕЛЬ СИМУЛЯТОРА (НЕ РЕАЛЬНЫЙ ВИНРЕЙТ)", "Парный Монте-Карло с общими случайными числами: моя команда с изменением против неизменённой.")
    info = [("Статус", m.get("status")), ("Боёв на вариант", m.get("n")), ("Seed", m.get("seed")), ("Пресет допущений", m.get("preset")),
            ("Метрика", m.get("metric")), ("Базовый балл (зеркало)", m.get("baseline")),
            ("Статы без панели", "; ".join(f"{k}: {v}" for k, v in (m.get("stat_notes") or {}).items()) or "—"),
            ("Причина пропуска", m.get("reason", "—")),
            ("Находка", "В зеркальном бою баф команды +5% СКР от Иллюсии снижал модельный балл (0.65 → 0.82 без него, 60 боёв): "
                        "это артефакт зеркального матча/темпа и шума, а не механика игры. Поэтому в веса идут только значимые эффекты."),
            ("Вывод по лимбам", (f"значимых эффектов бонуса 2 частей: {sum(1 for x in m.get('limb', {}).values() if x['ci95'][0] > 0 or x['ci95'][1] < 0)} "
                                 f"из {len(m.get('limb', {}))}. Если 0 — +5% стата слишком мал для симулятора, и выбор набора решают "
                                 "источники и эффект 4 частей (он не закодирован).")),
            ("Осторожно", "Вклад кита Мяоинь завышен неопределённостью её статов (нет панели — оценка по медианному коэффициенту). "
                          "Малый вклад кита Люцифера может означать недооценку ДоТ/статусов в ките — проверить по реальным боям.")]
    for i, (k, v) in enumerate(info, 4):
        wm.cell(row=i, column=1, value=k).font = F_BOLD
        c = wm.cell(row=i, column=2, value=v)
        c.font, c.alignment = F_BASE, WRAP
    r = 5 + len(info)
    _hdr_cells = ["Героиня", "Набор лимбов", "Бонус 2 частей", "Δ балла", "95% ДИ", "Значимо"]
    for j, name in enumerate(_hdr_cells, 1):
        c = wm.cell(row=r, column=j, value=name)
        c.font, c.fill = F_HEAD, FILL_HEAD
    r += 1
    for k, v in sorted(m.get("limb", {}).items()):
        h, limb = k.split("|", 1)
        lname = next((x["title"] for x in T.entities() if x["id"] == f"limb:{limb}"), limb)
        sig = "да" if (v["ci95"][0] > 0 or v["ci95"][1] < 0) else "нет"
        for j, val in enumerate([names.get(h, h), lname, f"{v['stat']} +{v['value']:.0%}", v["delta"],
                                 f"{v['ci95'][0]:+.3f} … {v['ci95'][1]:+.3f}", sig], 1):
            wm.cell(row=r, column=j, value=val).font = F_BASE
        wm.cell(row=r, column=4).number_format = "+0.000;-0.000;0"
        r += 1
    r += 1
    for j, name in enumerate(["Героиня", "Вариант", "", "Δ балла", "95% ДИ", "Значимо"], 1):
        c = wm.cell(row=r, column=j, value=name)
        c.font, c.fill = F_HEAD, FILL_HEAD
    r += 1
    for h, v in m.get("kit", {}).items():
        sig = "да" if (v["ci95"][0] > 0 or v["ci95"][1] < 0) else "нет"
        for j, val in enumerate([names.get(h, h), "навыки заменены обычной атакой", "", v["delta"],
                                 f"{v['ci95'][0]:+.3f} … {v['ci95'][1]:+.3f}", sig], 1):
            wm.cell(row=r, column=j, value=val).font = F_BASE
        wm.cell(row=r, column=4).number_format = "+0.000;-0.000;0"
        r += 1
    for col, wd_ in zip("ABCDEF", (22, 30, 18, 10, 22, 9)):
        wm.column_dimensions[col].width = wd_
    wm.column_dimensions["B"].width = 60

    # ------------------------------------------------------------------ Сопоставление_JP_RU
    wj = wb.create_sheet("Сопоставление_JP_RU")
    _title(wj, "СОПОСТАВЛЕНИЕ ИМЁН: НА СОГЛАСОВАНИЕ", "Впишите решение в жёлтую колонку («да», «нет» или правильное RU-название) — учту при следующей генерации.")
    _hdr(wj, 4, ["Оригинал", "Категория", "RU (как принято)", "Статус", "Пояснение", "Голосов", "Решение оператора"],
         [22, 16, 26, 26, 70, 9, 24])
    seen = {}
    for v in votes:
        if v["map_status"] == "lfru_alias" or v["source"] in ("lfru_grade", "class_fit"):
            continue
        k = (v["name_orig"], v["cat"], v["name_ru"], v["map_status"])
        seen.setdefault(k, [v["note"], 0])
        seen[k][1] += 1
    order_st = {"hypothesis": 0, "unmapped": 1, "meaning": 2}
    for i, ((orig, cat, ru, st), (note, cnt)) in enumerate(sorted(seen.items(), key=lambda x: (order_st.get(x[0][3], 9), x[0][1], x[0][0])), 5):
        vals = [orig, CAT_RU.get(cat, cat), ru, MAP_RU.get(st, st), note, cnt, None]
        for j, val in enumerate(vals, 1):
            c = wj.cell(row=i, column=j, value=val)
            c.font, c.alignment = F_BASE, WRAP
        wj.cell(row=i, column=7).fill = FILL_INPUT
        wj.cell(row=i, column=7).font = F_INPUT
        if st == "hypothesis":
            for j in range(1, 7):
                wj.cell(row=i, column=j).fill = FILL_WARN
    wj.freeze_panes = "A5"

    # ------------------------------------------------------------------ Источники
    wsr = wb.create_sheet("Источники")
    _title(wsr, "ИСТОЧНИКИ", "Количество голосов и диапазон дат по каждому источнику.")
    _hdr(wsr, 4, ["Источник", "Название", "Регион", "Голосов", "Самая ранняя дата", "Самая поздняя дата", "Ссылка", "Примечание"],
         [12, 44, 8, 9, 14, 14, 44, 80])
    for i, (sid, (nm, reg, url, wt, note)) in enumerate(SOURCES.items(), 5):
        ds = sorted(v["date"] for v in votes if v["source"] == sid)
        vals = [sid, nm, reg, f"=COUNTIF({G['src']},A{i})", dt.date.fromisoformat(ds[0]) if ds else None,
                dt.date.fromisoformat(ds[-1]) if ds else None, url, note]
        for j, val in enumerate(vals, 1):
            c = wsr.cell(row=i, column=j, value=val)
            c.font, c.alignment = F_BASE, WRAP
        wsr.cell(row=i, column=5).number_format = "yyyy-mm-dd"
        wsr.cell(row=i, column=6).number_format = "yyyy-mm-dd"

    for sheet in wb.worksheets:
        _arial(sheet)
    wb.save(out)
    return out
