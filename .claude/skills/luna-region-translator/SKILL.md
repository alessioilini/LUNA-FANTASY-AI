---
name: luna-region-translator
description: >-
  Maps names and terms between the regional versions of the game (RU Luna Fantasy, JP
  やばい！少女に囲まれた！, EN Tales of Angels, SEA Maidens Fantasy: LUST | SEA, KR, RR) using the
  project glossary data/glossary.json and luna.localization, keeping the verification status of every
  mapping (user_stated / generic / missing; name_match / hypothesis / search_snippet). Use it when the
  user asks what a heroine, item, stat or system is called in another region, wants to translate a JP
  or EN guide, resolve a name to a hero_id, or add a glossary entry. Russian triggers: "как называется
  в японской версии", "переведи гайд", "глоссарий", "соответствие имён", "лимбы это демоны",
  "русское название", "регион", "локализация".
---

# Luna Region Translator

## Назначение
Сопоставлять имена героинь, систем, статов и эффектов между регионами без потери статуса проверки.
Источник истины — `data/glossary.json` (поля `key, category, ru, en, jp, kr, ru_status, jp_status,
aliases_ru, note`) и функции `luna.localization`: `lookup`, `term`, `resolve_hero`, `label`,
`unverified_terms`.

## Когда использовать
- «Как Верафиэль/Люцифер/Лимбы называются в JP/EN?», «что значит セネリン?».
- Перевод/разбор японского или английского гайда перед импортом фактов.
- Нужно превратить имя из таблицы боёв в `hero_id` (это же делает `luna validate import`).
- Добавление нового термина или алиаса (например «Монашка» → `seraphia`).

## Требуемые входные данные
- Термин или имя на любом языке (RU/EN/JP/KR) либо текст гайда.
- Для новой записи: источник соответствия (скриншот RU-клиента, страница lunafantasy.ru, слова
  оператора) и уровень уверенности.

## Алгоритм работы
1. Найти термин: `luna glossary Верафиэль`, `luna glossary Лимбы`, `luna glossary ルシファー`.
   Поиск — точное совпадение имени (без регистра) на любом языке или алиаса `aliases_ru`; EN-имя
   лимбов записано как «Limbs (Demons in other versions)». Полный список: `luna glossary`.
2. В Python:
   ```python
   from luna.localization import lookup, resolve_hero, term, label, unverified_terms
   resolve_hero("Монашка")      # -> "seraphia"
   term("system.limb", "en")    # -> "Limbs (Demons in other versions)"
   label("stat.ATK")            # "Атака* (ATK)" — звёздочка = generic, не подтверждено в RU
   ```
3. Проверить статус: `ru_status=user_stated` — термин RU-клиента со слов оператора;
   `generic` — обычный перевод, НЕ подтверждённая игровая надпись; `missing` — RU-имени нет.
   `jp_status`: `name_match` | `hypothesis` | `search_snippet`.
4. Регионы-названия игры (из `luna/provenance.py` `Region`): RU Luna Fantasy, JP やばい！少女に囲まれた！,
   EN Tales of Angels, SEA Maidens Fantasy: LUST | SEA, KR 각성소녀: 욕망의 여정 и RR Realm Rush:
   Bonded Maidens (KR/RR не подтверждены источниками).
5. Посмотреть, где у героини есть данные по регионам: `luna kb hero lucifer`, сводка — `luna meta diff`.
6. Добавление записи: дописать объект в `data/glossary.json` с честным `ru_status`/`jp_status` и `note`
   об источнике; соответствие только по созвучию → `jp_status: "hypothesis"`.
7. Запустить `python -m pytest -q tests/test_kb_and_validation.py -k localization`.

## Ограничения
- Перевод термина не переносит факты между регионами: JP-статы остаются `region: JP`.
- Героиня, найденная только в JP/EN/SEA, не доступна в RU без RU-подтверждения (см. luna-meta-tracker).
- Известные гипотезы, которые нельзя выдавать за факт: Illusia = エルシア, Seneren = セネリン.
- «Пожиратель душ» (`effect.soul_eater`) — перевод не подтверждён, механика UNKNOWN.
- Лимбы = «демоны» в других версиях (та же система, 4 позиции, сеты 2/4).
- Сигилы (2 × 2 таланта) и личные таланты (2 отдельных) — разные системы и в переводе тоже.
- Верафиэль (Верафиэль, `verafiel`) — поддержка (слова оператора, `user_stated`).
- Общие правила локализации пайплайна (ключи, ICU, LQA) — в навыке gamedev-localization-specialist.

## Формат результата
Таблица: `key | RU | EN | JP | KR | ru_status | jp_status | примечание/источник`, плюс явный список
терминов со статусом `generic`/`hypothesis`, которые нужно подтвердить в RU-клиенте.

## Проверки качества
- Каждое соответствие показано со статусом; `generic` помечено звёздочкой как в `label()`.
- Нет записи с `ru_status: user_stated` без указания, кто это заявил.
- `resolve_hero` возвращает один `hero_id` для каждого алиаса (нет дублей между записями).
- JSON глоссария валиден: `python -c "import json; json.load(open('data/glossary.json'))"`.

## Примеры запросов
- «Как Лимбы называются в английской версии и это то же самое, что демоны?»
- «Переведи этот японский тир-лист и сопоставь имена с нашими героинями.»
- «Кто такая Монашка в базе? Какой у неё hero_id?»
- «Добавь в глоссарий русское название для セネリン — я видел его в клиенте.»
