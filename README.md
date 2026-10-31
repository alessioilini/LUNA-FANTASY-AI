# Luna Fantasy AI: метаигра и боевая аналитика

Система для анализа PvP-команды из шести героинь Luna Fantasy и её региональных версий: база знаний
с источниками, проверка сборок, событийный боевой движок, симулятор Монте-Карло, оптимизатор,
анализ матчапов, мониторинг меты, валидация на реальных боях и локальный дашборд.

> **Главное правило проекта:** неизвестные числа и формулы не выдумываются. Значение без источника остаётся
> `UNKNOWN`, неизвестная формула — это именованное допущение (`docs/ASSUMPTIONS.md`). Модельный процент побед
> не считается реальным, пока симулятор не прошёл проверку на реальных боях (`luna validate status`).

Текущее состояние данных и ограничения описаны в [INSTALL_REPORT.md](INSTALL_REPORT.md).

## Установка

```bash
cd ~/AI-Lab/luna-fantasy        # символическая ссылка на этот репозиторий
pip install -e '.[dev,scrape]'
luna env-check
python -m pytest -q
```

## Структура

| Путь | Что внутри |
|---|---|
| `luna/provenance.py`, `luna/kb.py` | Факты: регион, версия баланса, источник, достоверность, статус в RU-клиенте; запрет смешивания версий |
| `luna/localization.py`, `data/glossary.json` | RU/EN/JP/KR глоссарий со статусом каждого перевода |
| `luna/model.py` | Героиня (Identity/Progression/Combat/Build) и команда (формация, руны, оружие принцессы, реликты, глобальные статы) |
| `luna/rules.py` | Проверка игровых ограничений сборки и команды |
| `luna/engine/` | Событийный движок 6×6, реестр допущений, сборка юнитов из каталога |
| `luna/sim/` | Одиночный бой с полным логом, серии Монте-Карло, доверительные интервалы, парные сравнения |
| `luna/optimize/` | CP-SAT, GA (NSGA-II ранжирование), SA, beam search, полный перебор порядка рун |
| `luna/matchup.py` | Анализ матчапа, контрпики с причинами, абляция экипировки, шесть режимов |
| `luna/validation.py` | Импорт CSV/XLSX/JSON/MD/скриншотов/видео, журнал расхождений, калибровка train/test |
| `luna/meta.py` | Региональные изменения, тир-листы, прогноз релизов в RU (всегда как гипотеза) |
| `luna/resources.py` | Планирование улучшений под бюджет (CP-SAT) и на долгий срок |
| `luna/collector/` | Загрузка lunafantasy.ru и региональных гайдов онлайн или из сохранённых страниц |
| `luna/export.py` | Экспорт отчётов в XLSX / CSV / HTML |
| `luna/dashboard/` | Локальный интерфейс (`luna dashboard`) |
| `luna/scenarios.py` | Этап 9: составы A/B, сценарий 3, гипотезы (what-if) |
| `.claude/skills/` | 12 собственных навыков `luna-*` и 10 внешних |
| `data/kb/facts/*.jsonl` | База фактов по регионам |
| `data/kb/catalog_RU.json` | Каталог RU: **пуст**, пока нет доступа к данным |
| `data/fixtures/` | Синтетические данные только для тестов (регион SYNTHETIC) |
| `data/scenarios/` | What-if каталог ролевых шаблонов, априоры, составы A/B |
| `reports/stage9/` | Результаты проверки гипотез (JSON/XLSX/HTML) и разбор |

## Частые команды

```bash
luna kb status                                   # что известно и чего не хватает по каждой героине
luna kb hero Верафиэль                           # карточка героини по регионам
luna glossary СКР
luna assumptions                                 # реестр неизвестных формул
luna validate-team my_team.json --inventory inv.json
luna battle A.json B.json --seed 7 --log battle.json --out report.html
luna sim A.json B.json -n 10000 --workers 4 --key vignette
luna compare A.json A_v2.json --opponents B.json C.json -n 1000
luna matchup my.json enemy.json --suggest --ablation --roster roster.json --out matchup.xlsx
luna optimize --roster roster.json --opponents meta1.json meta2.json --mode anti_meta --pareto win_rate robust_wr
luna collect --offline-dir saved_pages/ && luna kb accept RU
luna validate import history.xlsx && luna validate calibrate --grid grid.json
luna meta forecast
luna dashboard --port 8765
```

## Как пополнять данные (сайты недоступны из облачной сессии)

1. Сохранить страницы lunafantasy.ru из браузера и выполнить `luna collect --offline-dir <папка>`.
   Распознанные значения попадут в `data/kb/pending/`, затем после проверки — `luna kb accept RU`.
2. Или заполнить CSV-шаблон `hero_id,name_ru,stat,value,level,stars,source_url,date,confidence` и выполнить `luna kb import-csv`.
3. Скриншоты (`luna validate import shot.png`) сохраняются как доказательства вместе с шаблоном ручной расшифровки.
4. Либо разрешить домены в сетевых настройках окружения (см. INSTALL_REPORT.md) и запустить `luna collect --url ...`.
