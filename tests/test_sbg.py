"""surrounded-by-girls.online parser: JP vs global skill versions, info table, stats, legacy layouts."""
from luna.collector import sbg

NEW = """<html><head><title>【ヤバ少女】キラ（綺羅）は引くべき？</title></head><body><h1>【ヤバ少女】キラ（綺羅）は引くべき？</h1>
<div class="article-body"><p>更新日：2026年10月24日 公開日：2026年7月18日</p>
<p>「花の芸者・綺羅 キラ Kira」（限定GR）の評価</p>
<table><tr><th>項目</th><th>内容</th></tr><tr><td>評価ランク</td><td>SSSランク</td></tr><tr><td>属性</td><td>光属性</td></tr>
<tr><td>職業</td><td>サポーター</td></tr><tr><td>日本版実装日</td><td>2026年8月18日</td></tr></table>
<h2>基本性能</h2><h3>🔹 ステータス（レベル350）</h3>
<table><tr><th>ステータス</th><th>数値</th></tr><tr><td>ATK</td><td>169538</td></tr><tr><td>体力</td><td>1347297</td></tr></table>
<h3>🔹 アクティブスキル</h3><h4>スキル　御鏡華盾</h4>
<h5>国内版</h5><p>追加で6%分の【瑠璃花の障】</p><h5>グローバル版</h5><p>追加で最大HPの5%分のラピスバリア</p>
</div></body></html>"""

OLD_TABLE = """<html><head><title>【ヤバ少女】ユラの評価</title></head><body><h1>【ヤバ少女】ユラの評価</h1><div class="article-body">
<h2>ユラの基本性能</h2><h3>🔹 アクティブスキル</h3>
<table><tr><th>スキル名</th><th>発動</th><th>効果</th></tr><tr><td>天使の祈り</td><td>1T</td><td>味方全体を回復</td></tr></table>
</div></body></html>"""

OLD_H3 = """<html><head><title>【ヤバ少女】ベルの評価！SSR・氷属性・ガーディアン</title></head><body><h1>【ヤバ少女】ベルの評価！SSR・氷属性・ガーディアン</h1>
<div class="article-body"><h2>スキル解説</h2><h3>アクティブスキル：金魚泉</h3><p>味方を回復する</p></div></body></html>"""


def test_new_layout_jp_and_global_kept_separate():
    c = sbg.parse_character(NEW, "https://surrounded-by-girls.online/character/kira/")
    assert c["name_jp"] == "キラ" and c["name_jp_alt"] == "綺羅" and c["name_latin"] == "Kira"
    assert c["rank"] == "SSS" and c["element_ru"] == "Свет" and c["class_ru"] == "Поддержка"
    assert c["jp_release_date"] == "2026-08-18" and c["stats"] == {"ATK": 169538.0, "HP": 1347297.0} and c["stats_level"] == 350
    sk = c["skills"][0]
    assert sk["name_jp"] == "御鏡華盾" and "6%" in sk["jp"][0] and "5%" in sk["global"][0]


def test_legacy_table_layout():
    c = sbg.parse_character(OLD_TABLE, "https://surrounded-by-girls.online/character/yura/")
    assert c["name_jp"] == "ユラ"
    assert c["skills"][0]["name_jp"] == "天使の祈り" and "効果: 味方全体を回復" in c["skills"][0]["other"]


def test_legacy_h3_layout_and_unmapped_element():
    c = sbg.parse_character(OLD_H3, "https://surrounded-by-girls.online/character/bell/")
    assert c["name_jp"] == "ベル" and c["skills"][0]["name_jp"] == "金魚泉"
    assert c["info"].get("element_jp") is None   # old layout has no info table; element only in the title
