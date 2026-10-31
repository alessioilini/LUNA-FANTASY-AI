---
name: luna-data-collector
description: >-
  Collects Luna Fantasy game data (heroines, stats, items, rules) from lunafantasy.ru and regional
  sources into the project knowledge base with full provenance: online fetch via `luna collect --url`,
  offline ingestion of browser-saved HTML via `luna collect --offline-dir`, human review of pending
  facts, `luna kb accept`, and the manual CSV template `luna kb import-csv`. Use it whenever the user
  wants to add, update or import game data, parse saved pages, fill gaps in the KB, or reports that a
  site is blocked. Russian triggers: "собери данные", "спарси страницу", "загрузи героинь",
  "импорт CSV", "обнови базу", "сохранённые страницы", "lunafantasy.ru", "добавь статы героини",
  "сайт заблокирован".
---

# Luna Data Collector

## Назначение
Пополнять базу знаний (`data/kb/facts/<REGION>.jsonl` и `<REGION>.user.jsonl`) фактами с полным
происхождением: `region`, `balance_version`, `source`, `confidence`, `ru_status`. Сборщик
(`luna/collector/__init__.py`) никогда не пишет в базу напрямую: разобранные значения попадают в
`data/kb/pending/<REGION>.jsonl` и проходят ручную проверку перед `luna kb accept`.

## Когда использовать
- Пользователь просит загрузить/обновить героинь, статы, предметы с lunafantasy.ru или из JP/EN/SEA гайдов.
- Есть папка с сохранёнными из браузера HTML-страницами.
- Пользователь хочет вручную внести статы из таблицы (CSV-шаблон).
- В `luna kb status` у героинь много `ru_missing` и нужно закрыть пробелы.

## Требуемые входные данные
- Источник: URL (`collector.SOURCES`: RU `https://lunafantasy.ru/`, JP appmedia.jp, EN/SEA qoo-app,
  COMMUNITY surrounded-by-girls.online) **или** папка с `*.html`/`*.htm` **или** CSV.
- Регион (`RU` по умолчанию; `JP`, `EN`, `SEA`, `KR`, `RR`, `OTHER`).
- Версия баланса / дата патча, уровень и звёзды для статов (если известны) — иначе `UNKNOWN`.
- CSV-колонки: `hero_id,name_ru,stat,value,level,stars,source_url,date,confidence,region,balance_version`
  (опционально `ru_status`, `kind`).

## Алгоритм работы
1. Проверить окружение: `luna env-check` (нужны `requests`, `bs4`; иначе `pip install -e .[scrape]`).
2. **Онлайн-путь.** `luna collect --url https://lunafantasy.ru/` — соблюдает robots.txt, кэширует
   страницу в `data/cache/html/<sha16>.html` (+ `.json` с URL). Статусы: `ok`,
   `blocked_or_unreachable`, `disallowed_by_robots`, `error`.
3. Если статус `blocked_or_unreachable` (в облачной сессии 2026-10-31 были заблокированы
   lunafantasy.ru, appmedia.jp, qoo-app, surrounded-by-girls.online) — **не обходить блокировку**.
   Попросить пользователя сохранить страницы в браузере («Сохранить как… → HTML») в отдельную папку,
   называя файлы по `hero_id` (`verafiel.html`): имя файла становится `hero_id` факта.
4. **Офлайн-путь.** `luna collect --offline-dir ~/luna_pages --region RU` → разбор `parse_page`
   (заголовок, таблицы, строки статов по `STAT_PATTERNS`) → `data/kb/pending/RU.jsonl`.
   Для кэша онлайн-загрузок с настоящими URL:
   ```python
   import json, pathlib
   from luna.collector import CACHE, ingest_offline_dir
   url_map = {p.with_suffix(".html").name: json.loads(p.read_text())["url"] for p in CACHE.glob("*.json")}
   print(ingest_offline_dir(CACHE, "RU", url_map))
   ```
5. **Ревью pending** (обязательно, построчно): уровень/звёзды отображаемых статов, `balance_version`
   (заменить `UNKNOWN`, если известна), `confidence` (авторазбор = `medium`), `ru_status`
   (`verified_in_ru_client` только по RU-клиенту/скриншоту), заменить `offline:<файл>` на реальный URL,
   удалить ошибочные строки. Ничего не дописывать «по памяти».
6. Принять проверенное: `luna kb accept RU` → факты дописываются в `data/kb/facts/RU.user.jsonl`,
   pending-файл переименовывается в `RU.accepted.jsonl`.
7. **Ручной шаблон.** `luna kb import-csv heroes.csv` пишет факты сразу в `<REGION>.user.jsonl`
   (без стадии pending) — поэтому CSV проверяется до импорта.
8. Контроль: `luna kb conflicts` (одинаковый ключ+регион+версия с разными значениями),
   `luna kb status`, `luna kb hero verafiel`.

## Ограничения
- Никаких выдуманных чисел: нет источника — нет факта; неизвестное значение пишется как `"UNKNOWN"`.
- `Fact` без `source.url` отклоняется; `SYNTHETIC` регион/уверенность только для фикстур.
- Регионы и версии баланса не смешиваются; JP/EN/SEA-данные получают свой `region`, а не `RU`;
  героиня из JP/EN/SEA не считается доступной в RU без подтверждения.
- `parse_page` извлекает только статы по шаблонам; тексты навыков, сигилы, руны не разбираются
  автоматически — вносятся вручную с источником.
- OCR скриншотов нет: скриншот регистрируется через `luna validate import shot.png` как шаблон для
  ручной расшифровки (см. luna-battle-validator).
- Блокировки сети не обходить (прокси-обходы, зеркала без согласия пользователя запрещены).

## Формат результата
- JSON сборщика: `{"pages": N, "pending_facts": M, "file": ".../data/kb/pending/RU.jsonl"}` или
  `{"status": "blocked_or_unreachable", "url": ..., "error": ...}`.
- Таблица принятых фактов: `key | value | region | balance_version | confidence | ru_status | source`.
- Список того, что осталось `UNKNOWN`, и что нужно от пользователя (страницы, скриншоты).

## Проверки качества
- Каждый принятый факт имеет `region`, `balance_version`, `source.url`, `confidence`, `ru_status`.
- `luna kb conflicts` пуст или каждый конфликт объяснён (разные уровни/версии).
- Нет фактов RU, скопированных из JP/EN/SEA; нет `SYNTHETIC` в реальных файлах.
- Для статов в `notes` указаны `level=`/`stars=`; `stats_mode` (base/panel) понятен.
- Pending-файл после ревью принят или явно отклонён, а не забыт.

## Примеры запросов
- «Собери статы героинь с lunafantasy.ru и добавь в базу.»
- «Сайт не открывается из облака — я сохранил страницы в папку ~/luna_pages, загрузи их.»
- «Вот CSV со статами Верафиэль с моего аккаунта, импортируй.»
- «Добавь данные с японского appmedia по Люциферу, но не путай с RU.»
