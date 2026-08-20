# 04 — Експериментальний дизайн та відтворюваність

## Зміст
1. [Exact Reproducibility Protocol](#exact-reproducibility-protocol)
2. [Input Dataset](#input-dataset)
3. [Команди для запуску](#команди-для-запуску)
4. [Outputs та артефакти](#outputs-та-артефакти)
5. [Фіксація версій](#фіксація-версій)
6. [Як повторити на іншому CSV](#як-повторити-на-іншому-csv)
7. [Determinism checklist](#determinism-checklist)

---

## Exact Reproducibility Protocol

**Мета:** будь-хто може повторити експеримент та отримати **identical** результати

### Крок 1: Clone repository

```bash
git clone https://github.com/ZarAO/RoadSensorRecorder_Analysis.git
cd RoadSensorRecorder_Analysis
git checkout main  # commit: 2025-01-10
```

### Крок 2: Create virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# або: source .venv/bin/activate  # Linux/Mac

# Install dependencies (ставить пакет analyzer у editable-режимі)
pip install -r requirements.txt

# Еквівалент напряму (без pytest):
pip install -e ./analyzer
```

Пакет `road_quality_analyzer` лежить у `analyzer/src/` (src-layout), тому
editable-встановлення обов'язкове — без нього імпорт працює лише з кореня
репозиторію.

**Кореневий `requirements.txt` (workspace-форма):**
```
-e ./analyzer
pytest>=7.0.0
```

**Requirements (нижні межі з `analyzer/pyproject.toml`; мінімум Python 3.11 через numpy>=2.3):**
```
numpy>=2.3.0
pandas>=2.3.0
scipy>=1.16.0
matplotlib>=3.10.0
scienceplots>=2.1.0
folium>=0.20.0
pytest>=7.0.0   # extras: dev
```

### Крок 3: Verify input data

```bash
# Check CSV integrity
md5sum storage/data/sensor_data_20250729_163334.csv
# Expected: <hash> (якщо надано)

# Check structure
head -5 storage/data/sensor_data_20250729_163334.csv
```

**Expected output** (файл 2025-07-29 записаний до контракту v2, тому без `#`-преамбули):
```csv
Time,Type,X,Y,Z,Latitude,Longitude
1753796015011,Accelerometer,-3.7890346,7.984849,3.2075787,,
1753796015018,Gyroscope,-0.53068876,-2.369697,-0.35475972,,
1753796015422,Location,,,,50.38692857,30.45877463
```

### Крок 4: Run experiment

```bash
python -m road_quality_analyzer analyze \
  --input storage/data/sensor_data_20250729_163334.csv \
  --out out/new_run
```

> Legacy-пайплайн (`main.py` зі старим `modules/`) та скрипт порівняння
> `tools/compare_runs_v2.py` видалені з дерева (див. [09](09_migration_notes.md)).
> `main.py` тепер — тонка обгортка над тим самим `analyze()`.

---

## Input Dataset

**Файл:** `storage/data/sensor_data_20250729_163334.csv`

### Характеристики

| Parameter | Value |
|-----------|-------|
| **Filename** | sensor_data_20250729_163334.csv |
| **Size** | ~11 MB (11 891 449 байт) |
| **Date recorded** | 2025-07-29 (літо, суха погода) |
| **Distance** | 15.09 km (15092.4 м у вікні аналізу) |
| **Duration** | ~30 хвилин (1799 с) |
| **Total rows** | 188596 (без заголовка) |
| **Accelerometer rows** | 93399 (Type=='Accelerometer') |
| **Gyroscope rows** | 93398 (Type=='Gyroscope', пайплайном не використовуються) |
| **Location rows** | 1799 (Type=='Location') |
| **Accelerometer fs** | ~52.6 Hz (median dt = 19 мс) |
| **GPS fs** | ~1 Hz (median dt = 1000 мс) |
| **Route type** | Міські вулиці + заміська траса |
| **Vehicle** | Легковий автомобіль (sedan) |
| **Phone model** | [Unknown, можна додати] |
| **Mounting** | Dashboard holder |

### CSV Structure

```csv
# schema=2                                                  ← необов'язкова преамбула
# units: accel=m/s^2 (includes gravity), gyro=rad/s, latlon=deg WGS84, time=ms epoch anchored monotonic
Time,Type,X,Y,Z,Latitude,Longitude
1753796015011,Accelerometer,-3.7890346,7.984849,3.2075787,,    ← X,Y,Z у м/с² (з гравітацією)
1753796015018,Gyroscope,-0.53068876,-2.369697,-0.35475972,,    ← X,Y,Z у рад/с
1753796015422,Location,,,,50.38692857,30.45877463              ← Lat,Lon у градусах WGS84
```

**Колонки (рівно 7):**
- **Time:** epoch-ms на монотонному годиннику рекордера
  (`anchorWallMs + (event.timestamp - anchorNs)/1e6`)
- **Type:** `Accelerometer` | `Gyroscope` | `Location`
- **X, Y, Z:** акселерометр (м/с², з гравітацією) чи гіроскоп (рад/с); порожні для `Location`
- **Latitude, Longitude:** десяткові градуси WGS84; порожні для рядків сенсорів

Рядки з `#` перед заголовком пропускаються (`pd.read_csv(..., comment='#')`), тож
файли без преамбули (як цей датасет) читаються ідентично.

### Коментарний шар v2.1/v3

`# schema=2` незмінний — 7-колонковий контракт даних той самий. Новіші записи
додають коментовані рядки, які читач даних і так пропускає, але аналізатор
парсить окремо (`io/metadata.py`) у `report.md` і `recording_meta.json`:

- **v2.1 інциденти** — `# event: t=<anchored epoch ms>, type=<token>[, k=v...]`
  прямо в потоці даних (8 типів: `sensor_stall`, `sensor_recovered`,
  `sensor_dead`, `gps_lost`, `gps_rerequest`, `gps_recovered`,
  `accuracy_changed`, `low_storage`). Рядки не строго монотонні відносно даних
  (batching) — аналізатор сортує за `t`.
- **v2.1 футер** — `# end: duration_ms=, rows_accel=, rows_gyro=, rows_gps=,
  events=, battery_end_pct=, reason=<user|low_storage|destroy>`. Наявність
  футера = чиста зупинка; відсутність = обірваний запис (файл валідний, але
  неповний). `rows_*`/`events=` — queue-time верхні межі, не точні підсумки.
- **v3 блок профілю авто** — `# vehicle_<key>=<value>` × 11 ключів одразу після
  преамбули (`vehicle_tire_pressure_bar` — єдиний опційний). Значення — усе
  після першого `=`; `\r`/`\n` у вільному тексті замінені на пробіли ще при
  записі (тому можливі подвійні пробіли).

Канонічний опис контракту: `RoadSensorRecorder/README.md` (розділи «Інциденти і
футер» та «Профіль авто»). Файли без цього шару (як цей датасет) обробляються
без змін — секції звіту фіксують його відсутність.

### Pre-processing requirements

**Для нового пайплайну:**
- ✅ Перевіряє заголовок на точну відповідність контракту (інакше `ValueError`)
- ✅ Separates Accelerometer / Gyroscope / Location streams
- ✅ Drops NaN у значущих колонках кожного потоку
- ✅ Згортає дублікати timestamp у середнє (interp1d вимагає зростаючий x)
- ✅ NO ffill/bfill
- ✅ Time conversion: одиниця детектується (`ms` / `s` / ISO) → секунди від початку

**Для legacy:**
- ⚠ Uses ffill/bfill (non-causal)
- ⚠ Mixed streams до розділення

---

## Команди для запуску

### Legacy Pipeline (історично)

Legacy-прогін виконувався `python main.py` зі старим пакетом `modules/` і давав
`storage/results/results_YYYYMMDD_HHMMSS/` з 1799 time-based сегментами,
`road_quality_map.html` та діагностичними PNG. Цей код видалено
(див. [09](09_migration_notes.md)); зараз `main.py` — обгортка над новим `analyze()`
з автовизначенням останнього CSV у `storage/data/` та автогенерацією теки результатів:

```bash
python main.py --input storage/data/sensor_data_20250729_163334.csv --out storage/results/my_run
python main.py                # auto-detect останній CSV + storage/results/results_<timestamp>
```

### New Pipeline

**Main command:** `python -m road_quality_analyzer analyze`

```bash
python -m road_quality_analyzer analyze \
  --input storage/data/sensor_data_20250729_163334.csv \
  --out out/new_run
```

**Параметри CLI:** лише `--input` та `--out` (обидва обов'язкові).

Решта параметрів — константи в `cli.py`, і кожен запуск друкує їх фактичні
значення в `report.md` (секція Configuration):
- довжина сегмента 100 м
- threshold для anomalies 10.0 м/с²
- band-pass 0.5–6.0 Hz
- параметри авто Eq.4-6: `npeop=1.0`, `stif=1.0`, `dampf=1.0`, `tyres=1.0`

**Outputs:** `out/new_run/`

**Files created:**
- `road_segments.csv` — 152 distance-based 100m segments (2 з них `partial`)
- `roughness.geojson` — GeoJSON LineStrings з метриками (для QGIS/Kepler.gl)
- `events.geojson` — Point features для кожної аномалії
- `segments_map.html` — Folium map з color-coded segments
- `plots/speed_vs_distance.{png,pdf}`
- `plots/accel_vs_distance.{png,pdf}`
- `plots/metrics_vs_distance.{png,pdf}` — Grms + IRI_multi
- `plots/iri_psd_vs_distance.{png,pdf}`
- `report.md` — текстовий звіт (configuration, data window, sampling compliance,
  PSD scalar diagnostic, top-10 worst, assumptions)

**Runtime:** ~25 секунд

### Comparison Script

Скрипт `tools/compare_runs_v2.py` (STAGE 2) разом із каталогом `out/comparison/`
у репозиторії відсутній, тому порівняння з поточного дерева не відтворюється.
Стабільні копії його результатів (4 таблиці CSV + 4 графіки) збережені у
`docs/paper_assets/`, а самі числа наведені в [05](05_results_legacy_vs_new.md).

---

## Outputs та артефакти

### Legacy Run Directory Structure

```
storage/results/results_20260110_182841/
├── road_segments.csv           (1799 rows, 6 columns)
├── road_quality_map.html       (Folium map, ~500 KB)
├── grms_plot.png               (RMSA vs time)
├── rmsa_plot.png               (distribution histogram)
├── peaks_plot.png              (detected peaks)
├── time_series_plot.png        (raw accelerometer)
└── debug.log                   (processing log)
```

**road_segments.csv columns:**
```
segment, avg_latitude, avg_longitude, avg_rmsa, quality, color
```

### New Run Directory Structure

```
out/new_run/
├── road_segments.csv           (152 rows, 24 columns)
├── roughness.geojson           (152 features, LineString)
├── events.geojson              (Point на кожну аномалію)
├── segments_map.html           (Folium map)
├── plots/
│   ├── speed_vs_distance.png / .pdf     (PNG 150 DPI, PDF вектор)
│   ├── accel_vs_distance.png / .pdf
│   ├── metrics_vs_distance.png / .pdf
│   └── iri_psd_vs_distance.png / .pdf
└── report.md                   (configuration + diagnostics)
```

**road_segments.csv columns (24, у порядку запису):**
```
seg_id, s_start, s_end, length_m, partial, n_samples,
mean_speed_mps, mean_speed_kmh, speed_valid, low_speed_class,
needs_class12_survey, dx_le_03_share, grms,
iri_psd_raw, iri_psd, psd_band_power, psd_sqrt_scalar, psd_scalar_mode,
psd_n_samples_used, psd_df_hz, fs_used_hz, iri_multi, anomaly_count,
events_per_km
```

Три останні з них додала опція `--low-speed-policy`: `low_speed_class`,
`needs_class12_survey` та `events_per_km` (див.
[08](08_user_guide_and_cli_reference.md)). Кількість рядків залежить від
політики: за `ignore` низькошвидкісні сегменти в цей файл не потрапляють
(на записі 2025-07-29 це 19 зі 152 рядків), решта політик лишає всі 152.

---

## Фіксація версій

### Software Environment

```yaml
OS: Windows 11 (або Linux, macOS)
Python: >= 3.11 (поточний .venv: 3.14.4)
Virtual environment: .venv/

Dependencies (версії у поточному .venv, де 163/163 тестів проходять):
  numpy: 2.5.2
  pandas: 3.0.5
  scipy: 1.18.0
  matplotlib: 3.11.1
  scienceplots: 2.2.2
  folium: 0.20.0
  pytest: 9.1.1
```

Точні версії свого середовища зафіксуйте для публікації командою
`pip freeze > requirements.lock.txt`.

### Repository State

```
Repository: ZarAO/RoadSensorRecorder_Analysis
Branch: main
Commit: <commit hash from 2025-01-10>
Date: 2025-01-10

Key files:
- analyzer/pyproject.toml (road-quality-analyzer 1.1.0, src-layout)
- analyzer/src/road_quality_analyzer/ (io, preprocessing, orientation, filtering,
  anomaly, metrics, segmentation, artifacts, cli)
- main.py (тонка обгортка над cli.analyze)
- analyzer/tests/ (163 unit tests, 11 файлів)
- storage/data/sensor_data_20250729_163334.csv
```

**Як отримати commit hash:**
```bash
git rev-parse HEAD
```

### Configuration Snapshot

**New pipeline (константи в `analyzer/src/road_quality_analyzer/cli.py::analyze`):**
```python
# time grid
fs: auto-detect (1 / median dt); допустима смуга 5-1000 Hz, інакше ValueError

# orientation/gravity_alignment.py
GRAVITY_CUTOFF_HZ: 0.3     # Butterworth low-pass, order 4, filtfilt
GRAVITY_TOLERANCE: 0.10    # |g_hat| має бути в межах ±10% від 9.80665 m/s²

# orientation/heading.py
HEADING_MIN_SPEED_MPS: 1.0

# filtering.py
BAND_LOW_HZ: 0.5
BAND_HIGH_HZ: 6.0
order: 4                   # zero-phase filtfilt

# anomaly/threshold.py
ANOMALY_THRESHOLD_MS2: 10.0
DISTRESS_WINDOW_SEC: 0.5   # ±0.5 с навколо аномалії маскується для PSD

# metrics/iri.py
IRI_PSD_COEFFICIENTS, IRI_MULTI_COEFFICIENTS (книжкові значення, не змінені)
IRI_MULTI_DEFAULT_PARAMS: npeop/stif/dampf/tyres

# segmentation/segment_100m.py
SEGMENT_LENGTH_M: 100.0
MIN_FULL_SEGMENT_M: 90.0            # коротший сегмент → partial=True
SPEED_VALID_MIN/MAX_KMH: 20 / 100   # поза діапазоном IRI = NaN
DX_COMPLIANT_M: 0.3

# PSD (Welch)
DEFAULT_SCALAR_MODE: 'mean_psd_sqrt'  # також рахуються band_power_sqrt,
                                      # median_psd_sqrt, peak_psd_sqrt (діагностика)
guard: PSD рахується лише при n >= fs*2, інакше NaN
```

Фактичні значення кожного прогону друкуються у `report.md` (секція Configuration).

**Legacy (defaults):**
```python
# preprocessing.py
rolling_window_gravity: 50 samples
savgol_window: 11 samples
savgol_polyorder: 2
highpass_cutoff: 0.5 Hz

# analysis.py
rmsa_window_size: 10 samples
peak_threshold: mean + 2*std
peak_distance: 10 samples
segment_duration: 10 seconds (time-based)
```

---

## Як повторити на іншому CSV

### Вимоги до CSV

**Обов'язковий заголовок (перевіряється точно, 7 колонок):**
```
Time,Type,X,Y,Z,Latitude,Longitude
```

**Формат:**
- **Time:** epoch-ms (підтримуються також epoch-s та ISO-рядок — одиниця детектується)
- **Type:** `Accelerometer` | `Gyroscope` | `Location` (порівняння без урахування регістру)
- **X, Y, Z:** Float — акселерометр у м/с² (з гравітацією) або гіроскоп у рад/с;
  порожні для `Location`
- **Latitude, Longitude:** Float (градуси WGS84) для `Location`, порожні для сенсорів
- Перед заголовком дозволена преамбула з рядків, що починаються з `#`

**Приклад запису:**
```csv
# schema=2
Time,Type,X,Y,Z,Latitude,Longitude
1722261414023,Accelerometer,0.234,-0.123,9.876,,
1722261414000,Location,,,,50.450,30.523
```

### Крок 1: Підготовка CSV

```bash
# Перевірити структуру
head -10 your_data.csv

# Перевірити Type values
grep -v '^#' your_data.csv | cut -d',' -f2 | sort | uniq
# Має бути: Type, Accelerometer, Gyroscope, Location

# Перевірити, що в кожному рядку рівно 7 полів
grep -v '^#' your_data.csv | awk -F, '{print NF}' | sort | uniq -c
```

### Крок 2: Run new pipeline

```bash
python -m road_quality_analyzer analyze \
  --input your_data.csv \
  --out out/your_analysis
```

**Очікувана поведінка на проблемних даних (аналіз падає з `ValueError`, а не
підставляє вигадані значення):**
- заголовок не відповідає контракту → `Unexpected CSV header ...`
- немає рядків `Accelerometer` → `No usable Accelerometer rows ... Type values found = ...`
- немає рядків `Location` → `No Location rows ...: distance-based analysis requires GPS`
- виведена fs поза 5–1000 Hz → повідомлення про одиницю колонки `Time`
- |g_hat| відхиляється від 9.80665 м/с² більше ніж на 10% → одиниці або fs
  не відповідають контракту
- IRI_psd < 0 не є помилкою: `iri_psd_raw` зберігається, `iri_psd` кліпається до 0
- `report.md` позначає `fs` поза 80–120 Hz прапорцем ⚠ у секції Sampling Compliance

### Крок 3: Inspect outputs

```bash
# Перевірити road_segments.csv
head -5 out/your_analysis/road_segments.csv

# Відкрити карту
open out/your_analysis/segments_map.html  # Linux/Mac
# або: start out/your_analysis/segments_map.html  # Windows

# Читати звіт
cat out/your_analysis/report.md
```

---

## Determinism Checklist

### Фіксовані параметри

- [x] **Random seed:** `np.random.default_rng(20260101)` через фікстуру `rng`
  у `analyzer/tests/conftest.py` — єдине джерело випадковості в тестах (сам пайплайн
  стохастичних операцій не має)
- [x] **Filter parameters:** f_low=0.5, f_high=6.0, order=4 (фіксовані)
- [x] **Threshold:** 10.0 m/s² (константа)
- [x] **IRI coefficients:** Eq.3 (A=0.774, B=0.825), Eq.6 (фіксовані)
- [x] **Segmentation:** 100 м (конфігурований, але default фіксований)
- [x] **PSD parameters:** nperseg, window='hann' (детерміністичні)

### Reproducible operations

- [x] **Haversine distance:** pure math (no randomness)
- [x] **Quaternion rotation:** deterministic linear algebra
- [x] **Welch PSD:** deterministic FFT
- [x] **Speed smoothing:** 1-секундне ковзне середнє (`uniform_filter1d`) ДО
  `np.gradient` — детерміністичне
- [x] **Linear interpolation:** deterministic (`scipy.interpolate.interp1d`)
- [x] **Butterworth filter:** deterministic (scipy.signal.butter)
- [x] **filtfilt:** zero-phase, deterministic

### Non-deterministic sources (mitigated)

- [ ] **Pandas row ordering:** ❌ Може змінюватися → Sort by Time завжди
- [ ] **Float precision:** ❌ OS/CPU dependent → Use fixed dtypes (float64)
- [ ] **Parallel processing:** ❌ Немає (single-threaded)
- [ ] **File system order:** ❌ Не використовується (fixed input path)

### Validation

**Run twice, compare outputs:**
```bash
python -m road_quality_analyzer analyze --input data.csv --out run1
python -m road_quality_analyzer analyze --input data.csv --out run2

diff run1/road_segments.csv run2/road_segments.csv
# Expected: no differences (identical outputs)
```

---

## Висновки

**Reproducibility досягнута через:**
1. ✅ Фіксовані версії dependencies (requirements.txt)
2. ✅ Deterministic algorithms (no randomness)
3. ✅ Fixed configuration parameters
4. ✅ 163 unit test (validation)
5. ✅ Documented input format
6. ✅ Exact commands для запуску

**Для наукової публікації вказати:**
- Repository + commit hash
- Версію Python (мінімум 3.11; поточний .venv — 3.14.4)
- OS (Windows/Linux/macOS)
- Dependencies versions (вивід `pip freeze` вашого середовища)
- Input CSV checksum (MD5/SHA256)
- Configuration snapshot (якщо змінювали defaults)

**Наступні розділи:**
- [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md) — числові результати
- [06_threats_to_validity_and_limitations.md](06_threats_to_validity_and_limitations.md) — обмеження
