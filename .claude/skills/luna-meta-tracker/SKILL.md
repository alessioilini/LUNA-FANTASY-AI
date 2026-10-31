---
name: luna-meta-tracker
description: >-
  Tracks the game meta across regions with luna.meta and data/meta/entries.jsonl: new heroines, skill
  and item changes, combos, tier lists, popular teams, version diffs and RU release forecasts, each
  labelled confirmed / community / hypothesis with a source. A heroine first seen in JP, EN or SEA is
  never marked available in RU without an RU source. Use it when the user asks what is new or strong,
  which teams are popular, what may come to RU, or wants to log a patch note, tier list or observed
  team. Russian triggers: "мета", "что нового", "тир-лист", "популярные команды", "кто выйдет в RU",
  "прогноз релиза", "патч", "изменения баланса", "сильнейшие героини".
---

# Luna Meta Tracker

## Назначение
Вести журнал меты (`data/meta/entries.jsonl`) с явным статусом и источником каждой записи и
отвечать на вопросы о мете без смешивания регионов. Код: `luna/meta.py` (`validate_entry`, `add`,
`query`, `forecast_ru`, `region_diff`).

## Когда использовать
- «Что сейчас в мете?», «какие команды популярны?», «что нового в JP?»
- «Какие героини могут выйти в RU?» (прогноз — только гипотеза).
- Добавить тир-лист, патч-ноут, наблюдённую команду соперника.
- Подобрать пул соперников для luna-team-optimizer.

## Требуемые входные данные
- Запись: `region`, `kind` (`new_hero`, `skill_change`, `item_change`, `combo`, `tier_list`,
  `popular_team`, `version_diff`, `ru_release_forecast`, `event`), `status` (`confirmed` | `community`
  | `hypothesis`), `subject`, `source` (обязателен кроме `hypothesis`), `date`, `summary`, `confidence`.
- Для не-RU записи с `ru_available: true` — обязательный `ru_source`.

## Алгоритм работы
1. Просмотр: `luna meta list --region JP --kind tier_list`, `luna meta list --status confirmed`,
   экспорт `luna meta list --region RU --out reports/meta_ru.xlsx`.
2. Прогноз RU-релизов: `luna meta forecast` — героини `new_hero` вне RU без RU-записи; всегда
   `status: hypothesis`, `ru_available: false`.
3. Где RU-данных не хватает относительно других регионов: `luna meta diff`.
4. Добавление: сохранить запись в файл и `luna meta add --file entry.json`; валидатор отклонит
   неверный `kind`/`status`, запись без источника и `ru_available: true` без `ru_source`.
   ```json
   {"region": "RU", "kind": "popular_team", "status": "community", "subject": "verafiel-support-core",
    "source": "https://lunafantasy.ru/...", "summary": "состав и наблюдения", "confidence": "low"}
   ```
5. Популярные команды для оптимизации: превратить подтверждённые составы в `Team`-JSON со
   `status: observed_opponent` (статы `UNKNOWN`, если не известны) → `--opponents` в luna-team-optimizer.
6. Перевести имена из JP/EN источников — luna-region-translator; числа из гайдов — luna-data-collector.

## Ограничения
- JP/EN/SEA новинки и тир-листы не переносятся на RU: другая версия баланса, другая доступность.
- Тир-лист сообщества — мнение (`community`), не результат модели и не факт.
- Не выдумывать даты выхода в RU; прогноз — только список кандидатов с пометкой «гипотеза».
- Составы «Команда A/B» из брифа — тестовые, не мета и не ростер пользователя.
- Верафиэль — поддержка (со слов оператора); иные роли без источника не приписывать.

## Формат результата
Таблица `дата | регион | тип | субъект | статус | уверенность | краткое содержание | источник`,
отдельный блок «Прогноз для RU (гипотезы)» и блок «Чего не хватает в RU» из `meta diff`.

## Проверки качества
- У каждой записи есть `status`, а у не-гипотез — `source`.
- Ни одна не-RU героиня не помечена `ru_available: true` без `ru_source`.
- Регионы не смешаны в одной строке/выводе «по мете».
- Дата записи указана; устаревшие записи (старая версия баланса) отмечены.

## Примеры запросов
- «Что сейчас в мете в японской версии и что из этого может прийти к нам?»
- «Добавь тир-лист из этого гайда с lunafantasy.ru.»
- «Какие героини уже есть в JP, но не вышли в RU?»
- «Запиши команду соперника, с которой я встретился на арене, в популярные команды.»
