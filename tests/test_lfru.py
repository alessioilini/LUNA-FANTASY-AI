"""lunafantasy.ru extractor: payload parsing, build order, provenance mapping, conservative stat parsing."""
import json

from luna.collector import lunafantasy as L

CHAR = {"id": "character:char_vinette", "kind": "character", "title": "Виньетта", "subtitle": "GR · Огонь · Поддержка",
        "aliases": ["ヴィネット", "Винетт"], "href": "/characters/vinette", "summary": "саппорт",
        "effects": [{"label": "Активный", "text": "Оружие любви: Атакует всех врагов, нанося 98% магического урона."}],
        "stats": [{"label": "ATK", "value": "112 804"}, {"label": "OЗ", "value": "1 166 073"}],
        "tags": ["GR", "Огонь", "SSS"], "status": "из галереи", "confidence": "проверено вручную",
        "sourceRefs": [{"label": "Источник", "url": "https://appmedia.jp/yabasyoujyo/78914927"}]}
LIMB = {"id": "limb:limb_set_kimuyusagi", "kind": "limb", "title": "Кольцо кролика", "subtitle": "debuff_control",
        "aliases": ["奇夢うさぎ"], "href": "/limbs", "effects": [{"label": "2 части", "text": "АТК +5%."},
                                                                 {"label": "4 части", "text": "При атаке с вероятностью 50% ..."}],
        "status": "ru_client_screenshot_verified", "sourceRefs": [{"label": "Эффект", "url": "https://appmedia.jp/x"}]}


def page(objs, build_html=""):
    payload = json.dumps("0:" + json.dumps(objs, ensure_ascii=False, separators=(",", ":")), ensure_ascii=False)[1:-1]
    return (f'<html><body><main>{build_html}</main><script>self.__next_f.push([1,"{payload}"])</script></body></html>')


def test_entities_and_merge():
    html = page([CHAR, LIMB])
    ents = L.merge_entities(L.entities(L.rsc_text(html)) + L.entities(L.rsc_text(page([dict(CHAR, extra="x" * 50)]))))
    assert set(ents) == {"character:char_vinette", "limb:limb_set_kimuyusagi"}
    assert "extra" in ents["character:char_vinette"]          # richest version kept


def test_provenance_mapping():
    p = L.site_provenance(CHAR)
    assert p["confidence"] == "medium" and p["ru_status"] == "unverified" and p["derived_from_jp_appmedia"]
    q = L.site_provenance(LIMB)
    assert q["confidence"] == "high" and q["ru_status"] == "verified_in_ru_client"
    r = L.site_provenance({"status": "из билда", "confidence": "версия гайда", "sourceRefs": [{"url": "https://appmedia.jp/1"}]})
    assert r["confidence"] == "low"


def test_stats_and_subtitle():
    assert L.parse_stats(CHAR) == {"ATK": 112804.0, "HP": 1166073.0}
    assert L.subtitle_parts(CHAR["subtitle"]) == ["GR", "Огонь", "Поддержка"]


def test_simple_mods_is_conservative():
    assert L.simple_mods("АТК +5%.") == [{"stat": "ATK", "value": 0.05, "mode": "pct"}]
    assert L.simple_mods("Увеличивает СКР на 15% +60.")[1] == {"stat": "SPD", "value": 60.0, "mode": "flat"}
    assert L.simple_mods("Урон +15% против целей с уровнем ОЗ выше 70%.") is None
    assert L.simple_mods("При атаке с вероятностью 50% ...") is None


def test_character_build_order():
    b = ('<div><h4>Сигил 1</h4><div data-inspectable-id="sigil-talent:t_a">1 A</div>'
         '<div data-inspectable-id="sigil:生存">2 B</div></div>'
         '<div><h4>Сигил 2</h4><div data-inspectable-id="sigil-talent:t_c">1 C</div>'
         '<div data-inspectable-id="sigil-talent:t_d">2 D</div></div>'
         '<div><h4>Таланты персонажа</h4><div data-inspectable-id="sigil-talent:t_e">1 E</div>'
         '<div data-inspectable-id="sigil:神護">11* F</div></div>'
         '<div data-inspectable-id="sigil-talent:t_a">A игровой термин</div>'
         '<div data-inspectable-id="limb:limb_set_kimuyusagi">Кольцо кролика БИС</div>'
         '<div data-inspectable-id="pet:p1">P1</div><div data-inspectable-id="pet:p1">P1 again</div>'
         '<div data-inspectable-id="accessory:a1">A1</div>')
    bd = L.character_build(page([], b))
    assert bd["sigil_pairs"] == [["sigil-talent:t_a", "sigil:生存"], ["sigil-talent:t_c", "sigil-talent:t_d"]]
    assert [t["id"] for t in bd["personal_talents"]] == ["sigil-talent:t_e", "sigil:神護"]
    assert bd["personal_talents"][1]["slot_note"] == "11*"
    assert [p["id"] for p in bd["pets"]] == ["pet:p1"] and bd["accessories"] == ["accessory:a1"]
