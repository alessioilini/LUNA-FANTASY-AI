---
name: luna-hero-database
description: >-
  Answers questions about heroines and items from the provenance knowledge base (data/kb/facts/*.jsonl)
  and the per-region catalog (data/kb/catalog_RU.json): hero cards grouped by region, coverage of the
  P0 hero model, conflicts, and adding catalog entries with provenance. It never merges regions or
  balance versions and keeps unknown values as UNKNOWN. Use it when the user asks what is known about a
  heroine, her stats, role, element, class or skills, which data is missing, or wants to add a heroine
  to the catalog for simulation. Russian triggers: "что известно о героине", "статы героини",
  "карточка героини", "роль", "стихия", "база героинь", "каких данных не хватает", "добавь героиню в
  каталог", "Верафиэль".
---

# Luna Hero Database

## Назначение
Давать сводку по героиням и предметам строго из базы знаний (`luna.kb.KnowledgeBase`) и каталога
(`luna.model.Catalog`), показывая для каждого значения регион, версию баланса, источник, уверенность и
`ru_status`. Готовить записи каталога, пригодные для движка, без выдуманных чисел.

## Когда использовать
- «Что мы знаем о Верафиэль / Люцифер / Виньетте?»
- «Каких статов не хватает для симуляции RU-героинь?»
- Перед симуляцией: проверить, что героиня есть в каталоге нужного региона/версии.
- Добавить героиню или предмет в каталог по проверенным фактам.

## Требуемые входные данные
- Имя героини на любом языке (резолвится через глоссарий) или `hero_id`.
- Регион (по умолчанию RU) и, при необходимости, `balance_version`.
- Для новой записи каталога: факты из KB или источник + уверенность.

## Алгоритм работы
1. Карточка героини (регионы не сливаются): `luna kb hero Верафиэль` или `luna kb hero lucifer`.
2. Покрытие P0-модели (`name.ru, element, class, role, stat.ATK, stat.HP, stat.DEF, stat.SPD, skills`):
   `luna kb status --out reports/kb_status.xlsx`.
3. Конфликты значений: `luna kb conflicts`. Где RU-данных нет, а в других регионах есть: `luna meta diff`.
4. Точечный запрос в Python (никогда не берёт значение из другого региона):
   ```python
   from luna.kb import KnowledgeBase
   kb = KnowledgeBase.load()
   value, fact = kb.best("hero.verafiel.role", region="RU")   # (UNKNOWN, None) если нет
   kb.query("hero.lucifer.", region="JP")                      # все JP-факты
   ```
5. Каталог для движка: `data/kb/catalog_RU.json` (сейчас пуст — RU-числа не получены) и
   демонстрационный `data/fixtures/synthetic_catalog.json` (регион `SYNTHETIC`, числа выдуманы).
   Запись героини: `id, names{ru,en,jp}, role, rarity, faction, element, base_stats{...|"UNKNOWN"},
   stats_mode (base|panel), abilities[...], tags, provenance{source, confidence, note}`.
6. После правки каталога: `python -c "from luna.model import Catalog; print(Catalog.load('data/kb/catalog_RU.json').unsourced_entries())"`
   — список должен быть пуст.
7. Если данных нет — направить в luna-data-collector, а не заполнять «типичными» значениями.

## Ограничения
- Неизвестное остаётся `UNKNOWN` (`luna.provenance.UNKNOWN`); оно падает при использовании как число —
  для what-if нужны явные априоры (`--priors`, см. luna-battle-simulator).
- Нельзя смешивать регионы и версии: `ensure_single_balance`, `Catalog.merge` бросают `MixedBalanceError`.
- JP/EN/SEA-героини не доступны в RU без RU-подтверждения.
- Верафиэль — поддержка (`user_stated`). Составы «Команда A/B» из брифа (`luna/scenarios.py`) — тестовые,
  НЕ подтверждённый ростер пользователя.
- Шаблоны ролей в `luna/scenarios.py` (`WHATIF_VERSION`) — гипотезы, а не реальные навыки.
- Синтетический каталог нельзя выдавать за данные игры.

## Формат результата
Карточка: для каждого региона таблица `атрибут | значение | confidence | ru_status | balance_version |
источник`, затем блок «Не известно (UNKNOWN)» и «Что нужно, чтобы закрыть пробел».

## Проверки качества
- Ни одно значение не показано без региона и источника.
- RU и JP/EN/SEA разнесены по разным таблицам.
- `unsourced_entries()` пуст для изменённого каталога; `luna kb conflicts` не вырос.
- Числа `confidence: low/hypothesis` явно помечены как неподтверждённые.

## Примеры запросов
- «Что известно про Верафиэль в RU и есть ли её статы?»
- «Покажи, каких данных не хватает по всем героиням для симуляции.»
- «Сравни, что известно о Люцифере в JP и в RU.»
- «Добавь Виньетту в каталог RU по фактам из базы.»
