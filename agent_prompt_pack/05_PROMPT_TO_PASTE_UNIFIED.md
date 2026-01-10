# 05 — PROMPT TO PASTE (UNIFIED)

Скопіюй весь текст нижче і встав у GitHub Copilot Chat у VS Code.

---

Ти GitHub Copilot Agent, працюєш у VS Code **всередині цього репозиторію**.

## Жорсткі правила
1) **НЕ використовуй інтернет/браузинг** і не підтягуй зовнішні джерела.
2) Формули/коефіцієнти/пороги з книги бери **ТІЛЬКИ** з `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md` (розділ “BOOK CANON”).
3) Те, чого немає як формули в книзі, але потрібно для реалізації (orientation-корекція тощо) — бери з того ж файлу з розділу “ENGINEERING ADDITIONS”.
4) Після кожного логічного етапу роби короткий self-check по `agent_prompt_pack/04_ACCEPTANCE_CHECKLIST_UNIFIED.md`.

## Ціль
Перетворити поточний проєкт у відтворюваний пайплайн аналізу дорожнього полотна зі смартфонних сенсорів, який:
- коректно робить **orientation-корекцію**,
- рахує **IRI (m/km)** по **100 м сегментах** мінімум двома способами (PSD Eq.3 і multi-linear Eq.6),
- підтримує vehicle classification (LEV/DSD/GENERIC → Eq.4/5/6),
- генерує артефакти (CSV/GeoJSON/HTML/plots/report),
- не ламає legacy `python main.py`.

## План робіт (виконувати послідовно)
### 1) Baseline
- Запусти поточний код і зафіксуй baseline outputs у `out/baseline_<date>/`.
- Опиши поточні проблеми (змішані сенсорні ряди, сегментація, відсутність IRI, тощо) у новому `out/.../report.md`.

### 2) Додай новий пакет `road_quality_analyzer/`
Створи структуру:
- `road_quality_analyzer/io/*`
- `road_quality_analyzer/preprocessing/*`
- `road_quality_analyzer/orientation/*`
- `road_quality_analyzer/metrics/*`
- `road_quality_analyzer/segmentation/*`
- `road_quality_analyzer/anomaly/*`
- `road_quality_analyzer/reporting/*`
- `road_quality_analyzer/cli.py`
та забезпеч запуск:
```bash
python -m road_quality_analyzer analyze --input <csv> --out <dir> --config <yaml>
```

### 3) Ingestion (строго)
- Розділи CSV на окремі потоки (accelerometer/gyroscope/location).
- Заборони ffill/bfill акселя через GPS рядки.
- Переведи час у секунди, відсортуй.

### 4) Uniform time grid + GPS distance
- Побудуй `t_grid` для акселя (median dt).
- Інтерполюй аксель на `t_grid`.
- Побудуй cumulative distance `s(t)` з GPS і інтерполюй на `t_grid`.
- Швидкість `v(t)=ds/dt` + згладжування.

### 5) Orientation-корекція (обовʼязково)
Реалізуй строго за `02_FORMULAS...` (Engineering Additions B3):
- low-pass gravity `g_hat(t)`
- quaternion/матриця `R(t)` що вирівнює gravity
- `a_lin_world(t)` і `a_vertical(t)`
- `heading` з GPS у горизонтальній площині
- `a_perp(t)` перпендикуляр до руху
- маскуй `a_perp` коли speed нижче `heading_min_speed_mps`.

Додай unit test на синтетичний roll/pitch.

### 6) Фільтрація та метрики
- Band-pass 0.5–6 Hz підтримати (конфіг).
- Grms (RMS вертикалі в g).
- Welch PSD + band power → sqrtPSD (як визначено в 02).
- IRI_psd: Eq.3.
- Distress removal перед PSD: вирізай ±w навколо distress (threshold_10ms2) (див. 02).

### 7) Vehicle classification + IRI_multi
- Додай enum: LEV/DSD/GENERIC.
- Реалізуй Eq.4/5/6 (Book Canon) з параметрами з конфігу:
  - Speed у км/год (segment mean),
  - Npeop/Stif/DampF/TyreS з конфігу.
- wheel size приймай як метадані, але не використовуй у формулах.

### 8) 100 м сегментація (як у книзі)
- Ресемплінг у домені відстані (`s_grid`) з кроком 0.25 м.
- Сегменти по 100 м.
- На сегмент: mean speed, valid_ratio, Grms, sqrtPSD, IRI_psd, IRI_multi, anomaly_count.

### 9) Anomaly detection
- Реалізуй `threshold_10ms2`: a_vertical > 10 m/s² (Book Canon).
- Додай `rf` режим (опціонально): features {a_vertical, a_perp, speed} + moving average; реалізація повинна існувати, але може бути вимкнена за замовчуванням якщо немає даних/міток.

### 10) Артефакти
Записуй у `--out`:
- segments.csv
- roughness.geojson
- events.geojson
- segments_map.html
- plots/*.png
- report.md (включно з sampling compliance: dx≤0.3m, fs, рекомендації 80–120Hz)

### 11) Legacy compatibility
- `python main.py` має працювати як раніше.
- Дозволено додати прапорець для виклику нового пайплайна з legacy.

### 12) Фінальна перевірка
Звірся з `agent_prompt_pack/04_ACCEPTANCE_CHECKLIST_UNIFIED.md`.
Якщо щось не виконано — допрацюй, доки всі чекбокси не закриються.

---
