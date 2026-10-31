---
name: luna-battle-validator
description: >-
  Validates the simulator against real battles with luna validate: imports battle history (CSV/XLSX
  tables, detailed JSON reports, old Markdown recommendations, screenshots and video frames as
  evidence), logs simulator-vs-game discrepancies, and calibrates UNKNOWN assumptions on a
  chronological train split while scoring a held-out test split (Brier, log-loss). The simulator is
  NOT VALIDATED until at least 20 test battles beat the 0.25 Brier baseline; calibration needs at
  least 10 battles with full teams. Use it when the user shares real battle results, asks how accurate
  the model is, or wants to calibrate formulas. Russian triggers: "реальные бои", "проверь точность",
  "валидация", "калибровка", "история боёв", "загрузи бои", "скриншот боя", "насколько точна модель".
---

# Luna Battle Validator

## Назначение
Отделять модельные числа от реальности: собирать реальные бои (`data/validation/battles.jsonl`),
доказательства (`data/validation/evidence/`), журнал расхождений (`data/validation/discrepancies.jsonl`),
старые рекомендации (`data/validation/old_recommendations.jsonl`) и калибровать допущения
(`luna/validation.py`) по правилу хронологического train/test.

## Когда использовать
- Пользователь прислал таблицу/скриншоты/видео реальных боёв.
- «Насколько точен симулятор?», «можно ли верить этому винрейту?»
- Подбор значений неизвестных формул (`dmg.k_def`, `order.tie_break`, ...) по реальным исходам.
- Проверка старых советов (Markdown) на фактах.

## Требуемые входные данные
- Таблица CSV/XLSX с колонками (RU/EN заголовки): `date/дата`, `mode/режим`, `result/результат`
  (победа/поражение/ничья), `rounds/раунды`, `my_team/моя команда`, `enemy_team/соперник`,
  `notes/заметки`, `my_power/бр`, `enemy_power/бр соперника`.
- Для калибровки — JSON-отчёты с полными `Team`-словарями `my_team`, `enemy_team` и `result`.
- Скриншоты (`.png/.jpg/.webp`), видео (`.mp4/.mov/.mkv/.webm`, нужен ffmpeg).

## Алгоритм работы
1. Импорт: `luna validate import battles.csv` (или `.xlsx`), `luna validate import battle_0412.json`,
   `luna validate import old_tips.md`, `luna validate import shot.png --kind hero`,
   `luna validate import fight.mp4`. Имена героинь резолвятся через глоссарий.
2. Скриншот → шаблон ручной расшифровки `evidence/<sha16>.json` (`status: needs_transcription`, OCR нет);
   видео → кадры для ручной разметки. Расшифрованные статы вносятся через luna-data-collector.
3. Статус: `luna validate status` → `records`, `records_with_full_teams`, `journal_entries`,
   `mean_brier`, `simulator_validated`.
4. Журнал расхождений по каждому бою:
   ```python
   from luna.validation import load_records, log_discrepancy
   from luna.sim.montecarlo import simulate
   # для записи r с полными командами: pred = simulate(my, enemy, cat, asm, n=300)
   log_discrepancy(r, pred, note="первый бой после патча")
   ```
5. Калибровка (только при ≥ 10 боях с полными составами):
   `luna validate calibrate --grid grid.json -n 100 --out reports/calibration.json`,
   `grid.json` = `{"dmg.k_def": [5000, 10000, 20000], "order.tie_break": [["attacker_first", "position"], ["position"]]}`.
   Сплит хронологический (`split_train_test`, 30% самых новых — тест); подбор по train Brier,
   отчёт по test.
6. Вердикт: `simulator_validated: true` только если тест ≥ 20 боёв и test Brier < 0.25. Лучшие
   параметры сохраняются как именованное переопределение (`--set ...`), а не как «подтверждённые».
7. QA-процесс и регрессии — gamedev-qa-verifier; схема событий/метрик точности — gamedev-analytics-engineer.

## Ограничения
- Не калибровать по 1–9 боям; `--force` только для отладки кода, никогда для выводов.
- Не тестировать на боях старше обучающих (никакого случайного сплита).
- Модельный WR не называется реальным, пока не выполнен критерий валидации.
- Бои разных регионов/версий баланса не смешиваются в одной калибровке.
- Значения со скриншотов вводятся вручную и проверяются; ничего не «дочитывать» за OCR.
- Подобранное значение допущения остаётся допущением (статус `ASSUMED`), а не `CONFIRMED`.

## Формат результата
Таблица `train_size | test_size | best_params | train_brier | test_brier | test_logloss | baseline 0.25 |
validated`, топ расхождений из журнала (`battle_id | predicted_wr | actual | brier`), явный вердикт
«ВАЛИДИРОВАН / НЕ ВАЛИДИРОВАН» и чего не хватает (сколько ещё боёв).

## Проверки качества
- Число боёв для калибровки ≥ 10, тестовых для вердикта ≥ 20.
- Сплит хронологический; даты у всех записей.
- У каждой записи есть `source` (файл/скриншот).
- Сравнение с базовой линией 0.25 приведено всегда.

## Примеры запросов
- «Вот таблица моих последних 40 боёв на арене — проверь, насколько точен симулятор.»
- «Откалибруй константу защиты по реальным боям.»
- «Загрузи скриншот статов Верафиэль, чтобы потом внести их в базу.»
- «Можно ли уже говорить, что модельный винрейт совпадает с реальным?»
