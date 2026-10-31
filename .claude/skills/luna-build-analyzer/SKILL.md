---
name: luna-build-analyzer
description: >-
  Checks and explains a heroine build or a whole team against the game constraints (luna.rules) and
  shows how final stats are assembled from the personal layer (sigils with their talents, personal
  talents, limbs and 2/4 set bonuses, decorations, pets, charm cards) and the team layer (global stats,
  faction bonus, runes, princess weapon and resonance, relics) applied exactly once. Use it when the
  user asks whether a build is legal, why a stat looks wrong, what an item contributes, how to read
  validate-team issues, or which talents duplicate. Russian triggers: "проверь билд", "разбор билда",
  "сигилы и таланты", "лимбы", "украшения", "питомцы", "двойной учёт", "глобальные статы",
  "почему такие статы", "вклад предмета".
---

# Luna Build Analyzer

## Назначение
Валидировать билды (`HeroBuild`) и команды (`Team`) по правилам из KB и объяснять, откуда берётся
каждая итоговая характеристика, не допуская двойного учёта. Код: `luna/rules.py`
(`validate_hero`, `validate_team`), `luna/engine/resolve.py` (`personal_sources`, `team_sources`,
`aggregate`, `build_units`), `luna/model.py`.

## Когда использовать
- «Это допустимый билд?», «почему validate-team ругается?»
- Подозрение на двойной учёт глобальных статов или статов с панели.
- Нужно понять вклад сигила/лимбов/питомца в итоговые статы или в модельный WR.
- Два одинаковых таланта на героине (сигил + личный) — как они складываются.

## Требуемые входные данные
- `team.json` (формат `Team.to_dict()`: `heroes[]`, `formation`, `global_stats`, `faction_bonus`,
  `runes` (4, порядок активации), `princess_weapon` (4 позиции), `relics`, `region`, `balance_version`, `status`).
- Каталог того же региона/версии (`--catalog`, по умолчанию `data/kb/catalog_RU.json`).
- Опционально инвентарь `{"section:id": count}` для проверки владения предметами.

## Алгоритм работы
1. Структура билда героини: `sigils: [{"id", "talents": [t1, t2]}] × 2` (таланты сигила),
   `talents: [t1, t2]` (2 отдельных личных таланта — другая система), `limbs: [4 по позициям]`,
   `decorations` (8 слотов, не подтверждено для RU), `pets` (слоты по редкости — таблица UNKNOWN),
   `charm_cards`, `extra_mods`, `stats_mode: base|panel`.
2. Проверка: `luna validate-team team.json --inventory inv.json`. Для демо на фикстуре:
   `luna validate-team team.json --catalog data/fixtures/synthetic_catalog.json --rules-dir data/fixtures`.
   Код выхода 1 = есть ERROR.
3. Разобрать коды: `SYSTEM_MIX` (талант не той системы), `SLOT_COUNT`, `WRONG_POSITION`/`POSITION_TAKEN`
   (лимб/часть оружия принцессы не на своей позиции), `DUPLICATE_EFFECT` (нужно допущение стакания),
   `GLOBAL_IN_PERSONAL`/`GLOBAL_DOUBLED` (двойной учёт), `PANEL_STATS`, `PET_SLOTS_UNKNOWN`,
   `RULE_UNKNOWN`/`RULE_UNVERIFIED` (правило не подтверждено → WARN, не ERROR), `MIXED_BALANCE`, `NOT_OWNED`.
4. Итоговые статы по слоям (формула `stat.aggregation`: `(base+Σflat)*(1+Σpct)`, доли — аддитивно):
   ```python
   from luna.model import Catalog, Team
   from luna.engine.assumptions import AssumptionSet
   from luna.engine.resolve import build_units
   cat = Catalog.load("data/fixtures/synthetic_catalog.json"); team = Team.load("team.json")
   for u in build_units(team, cat, "A", AssumptionSet.preset("exploratory_v1")):
       print(u.uid, u.hero_id, {k: round(v, 3) for k, v in u.stats.items()})
   ```
   Командные бонусы применяются один раз на героиню при старте боя; в `stats_mode: panel` статы
   предметов не прибавляются, а командные — по критичному допущению `stat.panel_includes_team`.
5. Дубли эффектов: политика `stack.duplicate_effect` (`stack|unique`) или точечно
   `AssumptionSet.preset("exploratory_v1", stacking={"power": "stack"})`.
6. Вклад компонентов в модельный WR: `luna matchup my.json enemy.json --ablation -n 300`
   (снимает лимбы/питомцев/сигилы/таланты/украшения/руны/оружие/реликты по одному, парный ΔWR).
7. Подбор билда из легальных альтернатив — luna-team-optimizer (`simulated_annealing_builds`).

## Ограничения
- Не выдумывать бонусы предметов: нет записи в каталоге с `provenance` — предмет не используется.
- Сеты лимбов: пороги 2 и 4 (`rules.build.limb_set_thresholds`), 4 позиции; лимбы = «демоны».
- Руны: 4 штуки в порядке активации, вложенные руны (`nested`) срабатывают с вероятностью `prob`.
- Оружие принцессы: 4 позиции + резонанс (`princess_resonance`).
- Глобальные статы только в `team.global_stats`, никогда в `extra_mods` героини.
- Почти все лимиты слотов RU сейчас `user_stated`/unverified — нарушение даёт ERROR только для
  превышения `user_stated`/подтверждённого лимита, иначе WARN.

## Формат результата
1) Вердикт `OK`/`INVALID`; 2) таблица проблем `уровень | код | путь | сообщение | что сделать`;
3) таблица статов по слоям `стат | база | личный слой | командный слой | итог`;
4) список использованных допущений (`stat.panel_includes_team`, `stack.duplicate_effect`, ...).

## Проверки качества
- Ни один источник бонуса не встречается и в личном, и в командном слое.
- Регион/версия команды совпадают с каталогом.
- Для каждого `DUPLICATE_EFFECT` указана выбранная политика стакания.
- Числа предметов взяты из каталога с источником, а не из памяти.

## Примеры запросов
- «Проверь билд Верафиэль: два сигила, личные таланты, лимбы и 8 украшений.»
- «Почему у героини атака выше, чем на панели? Не считаем ли глобальные статы дважды?»
- «Что даёт сет лимбов на 2 и на 4 предмета в моей команде?»
- «validate-team выдал SYSTEM_MIX — что это значит?»
