# 08 — User Guide and CLI Reference

## Зміст
1. [Quick Start](#quick-start)
2. [Installation](#installation)
3. [Main Analysis Pipeline](#main-analysis-pipeline)
4. [CLI Reference](#cli-reference)
5. [Outputs Description](#outputs-description)
6. [Troubleshooting](#troubleshooting)
7. [FAQ](#faq)

---

## Quick Start

### 2-Command Workflow

```powershell
# 1. Activate environment
.\.venv\Scripts\Activate.ps1

# 2. Run analysis
python main.py --input "storage\data\sensor_data_20250729_163334.csv" --out storage\results\my_run
```

`main.py` — тонка обгортка: без `--input` він бере найновіший
`storage/data/sensor_data_*.csv`, без `--out` створює `storage/results/results_<timestamp>/`.

**Output:**
```
storage/results/my_run/
├── road_segments.csv       (метрики на 100 м сегмент, 24 колонки)
├── recording_meta.json     (преамбула, профіль авто, події, футер запису)
├── roughness.geojson       (LineString на сегмент)
├── events.geojson          (Point на кожну аномалію)
├── segments_map.html       (Folium map, забарвлення за IRI_multi)
├── report.md               (configuration + diagnostics)
└── plots/                  (4 графіки, PNG + PDF)
```

**Typical runtime:** ~25 sec (для dataset ~188k rows)

---

## Installation

### Prerequisites

- **Python:** 3.11+ (вимога numpy>=2.3; поточний .venv — 3.14.4)
- **OS:** Windows 10/11, Linux, macOS
- **Disk space:** ~500 MB (venv + packages)

### Step 1: Clone/Download

```powershell
cd <your_workspace_directory>
git clone <repository_url> RoadSensorRecorder_Analysis
cd RoadSensorRecorder_Analysis
```

### Step 2: Create Virtual Environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows
# або: source .venv/bin/activate  # Linux/macOS
```

### Step 3: Install Dependencies

```powershell
pip install -r requirements.txt

# Еквівалент напряму (без pytest):
pip install -e ./analyzer
```

**Contents of `requirements.txt`** (workspace-форма — ставить analyzer editable):
```
-e ./analyzer
pytest>=7.0.0
```

Пакет `road_quality_analyzer` лежить у `analyzer/src/` (src-layout), тому
editable-встановлення обов'язкове: саме воно робить `import road_quality_analyzer`
і `python -m road_quality_analyzer` доступними з будь-якої робочої директорії.

**Runtime-залежності (нижні межі з `analyzer/pyproject.toml`):**
```
numpy>=2.3.0
pandas>=2.3.0
scipy>=1.16.0
matplotlib>=3.10.0
scienceplots>=2.1.0
folium>=0.20.0
```

**Verification:**
```powershell
python -c "import numpy, pandas, scipy, matplotlib, scienceplots, folium; print('OK')"
# Expected: OK

python -m pytest analyzer/tests -q
# Expected: 182 passed
```

---

## Main Analysis Pipeline

### Command Structure

```powershell
python -m road_quality_analyzer analyze --input <csv_path> --out <dir>
# або еквівалентно через обгортку:
python main.py --input <csv_path> --out <dir>
```

### Required Arguments

**`--input <path>`** — Path to sensor data CSV (контракт v2)
**`--out <dir>`** — Output directory (створюється за потреби)

Обидва обов'язкові для `python -m road_quality_analyzer analyze`; у `main.py`
обидва мають fallback (останній CSV у `storage/data/`, `storage/results/results_<timestamp>/`).

**Format requirements (рівно 7 колонок):**
```csv
# schema=2
# units: accel=m/s^2 (includes gravity), gyro=rad/s, latlon=deg WGS84, time=ms epoch anchored monotonic
Time,Type,X,Y,Z,Latitude,Longitude
1753796015011,Accelerometer,-3.7890346,7.984849,3.2075787,,
1753796015018,Gyroscope,-0.53068876,-2.369697,-0.35475972,,
1753796015422,Location,,,,50.38692857,30.45877463
```

**Columns (7 total):**

| Column | Unit | Description |
|--------|------|-------------|
| `Time` | ms | epoch-ms на монотонному годиннику рекордера |
| `Type` | — | `Accelerometer` \| `Gyroscope` \| `Location` |
| `X`, `Y`, `Z` | m/s² / rad/s | акселерометр (з гравітацією) або гіроскоп; порожні для `Location` |
| `Latitude`, `Longitude` | deg WGS84 | координати; порожні для рядків сенсорів |

Рядки, що починаються з `#`, — необов'язкова metadata-преамбула; вона
пропускається (`pd.read_csv(..., comment='#')`), тому файли без преамбули
читаються ідентично. Заголовок перевіряється точно — інакше `ValueError`.

Записи контрактів v2.1/v3/v3.1 містять додаткові коментовані рядки, які
аналізатор парсить у `report.md` (секції Recording Metadata / Vehicle Profile /
Recording Events) і `recording_meta.json`:

```csv
# device_id=abc123                       ← v3.1: ідентичність телефона (преамбула, не блок авто)
# vehicle_id=u-1                         ← v3.1: ідентичність авто (додатковий, 12-й ключ блоку — записується першим рядком блоку)
# vehicle_type=sedan                     ← v3: блок профілю авто (11 ключів)
# event: t=1753796581000, type=gps_lost, age_s=12   ← v2.1: інцидент запису
# end: duration_ms=40000, rows_accel=4000, rows_gyro=0, rows_gps=40, events=2, battery_end_pct=85, reason=user
```

Наявність футера `# end:` означає чисту зупинку; його відсутність — обірваний
запис (файл валідний до останнього рядка, але неповний). Канонічний опис
контракту — `RoadSensorRecorder/README.md`.

---

## CLI Reference

### `analyze` Command

**Full syntax:**
```powershell
python -m road_quality_analyzer analyze --input <csv_path> --out <dir> `
  [--low-speed-policy {very-poor|poor|invalid|ignore}] `
  [--iri-psd-A <float>] [--iri-psd-B <float>]
```

Три необов'язкові параметри: `--low-speed-policy`, `--iri-psd-A`, `--iri-psd-B`.

**`--low-speed-policy`** (за замовчуванням `invalid`) керує сегментами,
середня швидкість яких < 20 км/год: дорога настільки погана, що швидше
проїхати неможливо, а саме там акселерометрична оцінка IRI найменш валідна.

| Значення | Що відбувається з low-speed сегментом |
|----------|----------------------------------------|
| `very-poor` | `low_speed_class = very_poor`, рядок лишається в усіх артефактах |
| `poor` | `low_speed_class = poor`, рядок лишається |
| `invalid` | `low_speed_class = invalid`, рядок лишається (за замовчуванням) |
| `ignore` | рядок виключено з `road_segments.csv`, `roughness.geojson` і карти; `report.md` усе одно рахує та перелічує ці сегменти |

`iri_multi` для таких сегментів — `NaN` за **будь-якої** політики: Eq.4/5/6
мають speed-член і калібровані лише на 20–100 км/год, тому політика дає мітку,
а не число.

**`--iri-psd-A` / `--iri-psd-B`** (за замовчуванням — книжкові константи
`A_sqrt_psd`/`B_const` з `metrics/iri.py`) підставляють калібровані коефіцієнти
Eq.3 (`IRI = A·√PSD + B`) замість книжкових. Кожен прапорець незалежний (не
переданий — береться книжкове значення), але призначені вони для спільного
використання як одного каліброваного набору. Впливають лише на
`iri_psd_raw`/`iri_psd` — `iri_multi` (Eq.6) їх не використовує. `report.md`
друкує застосовані A/B у секції `Configuration`, коли задано хоч один із
прапорців. Дослідження `studies/profilometer_validation`
([розділ 10](10_profilometer_validation.md)) поки не дало готового до
публікації набору для цих прапорців — гейти калібрування (R² > 0.85,
MAE < 0.5) на наявних даних не пройдено, книжкові константи в коді лишаються
незмінними.

Інших параметрів немає: `--config`, `--dx`, `--gravity_cutoff`, `--npeop`,
`--rf_threshold` тощо **не існують**. Решта параметрів пайплайну — константи у
`analyzer/src/road_quality_analyzer/cli.py`, і кожен прогін друкує їхні фактичні значення
у секцію `Configuration` файлу `report.md`:

| Константа | Значення | Призначення |
|-----------|----------|-------------|
| `SEGMENT_LENGTH_M` | `100.0` | довжина сегмента (м) |
| `GRAVITY_CUTOFF_HZ` | `0.3` | low-pass для оцінки гравітації (Hz) |
| `BAND_LOW_HZ` / `BAND_HIGH_HZ` | `0.5` / `6.0` | band-pass перед метриками (Hz) |
| `ANOMALY_THRESHOLD_MS2` | `10.0` | поріг аномалії по \|a_vertical\| (м/с²) |
| `DISTRESS_WINDOW_SEC` | `0.5` | маскування ±0.5 с навколо аномалії для PSD |
| `HEADING_MIN_SPEED_MPS` | `1.0` | мінімальна швидкість для валідного heading |
| `DEFAULT_SCALAR_MODE` | `mean_psd_sqrt` | скаляризація PSD для Eq.3 |
| `FS_MIN_HZ` / `FS_MAX_HZ` | `5` / `1000` | допустима смуга виведеної fs |
| `GRAVITY_TOLERANCE` | `0.10` | допуск \|g_hat\| відносно 9.80665 м/с² |

Пороги сегментації живуть у `segmentation/segment_100m.py`:
`MIN_FULL_SEGMENT_M = 90.0` (`partial`), `SPEED_VALID_MIN/MAX_KMH = 20/100`
(`speed_valid`), `DX_COMPLIANT_M = 0.3` (`dx_le_03_share`),
`LOW_SPEED_MAX_KMH = 20.0` (`low_speed_class`, `needs_class12_survey`).

### Examples

**Example 1: явні вхід і вихід**
```powershell
python -m road_quality_analyzer analyze `
  --input storage\data\sensor_data_20250729_163334.csv `
  --out out\run1
```

**Example 2: обгортка з автовизначенням останнього CSV**
```powershell
python main.py
```

**Example 3: обгортка з іменованою текою результатів**
```powershell
python main.py --input storage\data\sensor_data_20250729_163334.csv --out storage\results\official_run
```

**Example 4: позначити низькошвидкісні ділянки як «дуже погані»**
```powershell
python -m road_quality_analyzer analyze `
  --input storage\data\sensor_data_20250729_163334.csv `
  --out out\run_very_poor `
  --low-speed-policy very-poor
```
Рядки лишаються в усіх артефактах, у колонці `low_speed_class` стоїть
`very_poor`, `iri_multi` — порожній (NaN).

**Example 5: прибрати низькошвидкісні ділянки з карти й таблиць**
```powershell
python -m road_quality_analyzer analyze `
  --input storage\data\sensor_data_20250729_163334.csv `
  --out out\run_ignore `
  --low-speed-policy ignore
```
У консолі з'явиться рядок на кшталт
`Low-speed (< 20 km/h): 19 [policy: ignore, 19 excluded from artifacts]`:
19 сегментів не потраплять у `road_segments.csv`, `roughness.geojson` і карту,
але `report.md` перелічить їх повністю. Використовувати лише тоді, коли артефакт
готується для порівняння виміряних IRI — інакше з карти зникають саме найгірші
ділянки.

---

## Outputs Description

### Structure

```
<out>/
├── road_segments.csv
├── recording_meta.json
├── roughness.geojson
├── events.geojson
├── segments_map.html
├── report.md
└── plots/
    ├── speed_vs_distance.png / .pdf
    ├── accel_vs_distance.png / .pdf
    ├── metrics_vs_distance.png / .pdf
    └── iri_psd_vs_distance.png / .pdf
```

### File 1: `road_segments.csv`

**Purpose:** метрики на кожен 100 м сегмент (`seg_id = floor(s / 100)`)

**Format** (24 колонки; приклад — сегмент 1 датасету 2025-07-29):
```csv
seg_id,s_start,s_end,length_m,partial,n_samples,mean_speed_mps,mean_speed_kmh,speed_valid,low_speed_class,needs_class12_survey,dx_le_03_share,grms,iri_psd_raw,iri_psd,psd_band_power,psd_sqrt_scalar,psd_scalar_mode,psd_n_samples_used,psd_df_hz,fs_used_hz,iri_multi,anomaly_count,events_per_km
1,100.08,199.97,99.90,False,502,10.49,37.76,True,normal,False,1.0,0.0664,-0.81,0.0,...,mean_psd_sqrt,502,...,52.63,4.38,0,0.0
```

**Columns:**

| Column | Unit | Description |
|--------|------|-------------|
| `seg_id` | — | `floor(s / 100)` |
| `s_start`, `s_end` | m | межі сегмента за cumulative distance |
| `length_m` | m | фактична довжина сегмента |
| `partial` | bool | `True`, якщо `length_m < 90` — виключений із середніх звіту |
| `n_samples` | — | кількість семплів у сегменті |
| `mean_speed_mps`, `mean_speed_kmh` | m/s, km/h | середня швидкість (медіани немає) |
| `speed_valid` | bool | `20 ≤ mean_speed_kmh ≤ 100` (діапазон калібрування Eq.4/5/6) |
| `low_speed_class` | — | мітка сегмента `mean_speed_kmh < 20` за `--low-speed-policy`: `very_poor` / `poor` / `invalid`; `normal` для решти (значення `ignore` у цьому файлі не трапляється — за такої політики рядок узагалі не експортується, мітку видно лише в `report.md`) |
| `needs_class12_survey` | bool | `True` для `mean_speed_kmh < 20` — потрібен профілометр класу 1/2 |
| `dx_le_03_share` | 0-1 | частка семплів із `dx = v/fs ≤ 0.3 м` |
| `grms` | g | RMS вертикального прискорення після band-pass |
| `iri_psd_raw` | m/km | Eq.3 як є (може бути < 0) |
| `iri_psd` | m/km | те саме, кліпнуте до 0; `NaN` лише якщо PSD не обчислити (Eq.3 не має speed-члена) |
| `psd_band_power` | g² | потужність у смузі 0.5-6 Hz |
| `psd_sqrt_scalar` | g/√Hz | скаляр PSD, що йде в Eq.3 (`sqrt(mean(PSD))` у режимі за замовчуванням) |
| `psd_scalar_mode` | — | режим скаляризації (`mean_psd_sqrt` за замовчуванням) |
| `psd_n_samples_used` | — | скільки семплів пішло у Welch (після distress removal) |
| `psd_df_hz` | Hz | роздільність частоти Welch |
| `fs_used_hz` | Hz | fs, з якою рахувався сегмент |
| `iri_multi` | m/km | Eq.6 (GENERIC vehicle); `NaN`, якщо `speed_valid = False` |
| `anomaly_count` | — | кількість семплів із \|a_vertical\| > 10 м/с² |
| `events_per_km` | 1/km | `anomaly_count` / довжину сегмента в км; `NaN` при нульовій довжині |

Для сегментів із `needs_class12_survey = True` індикатором стану служить
`events_per_km` — пороговий детектор працює й нижче 20 км/год, тоді як обидві
IRI-формули там не визначені.

**Usage:**
```python
import pandas as pd

df = pd.read_csv('out/run1/road_segments.csv')

# лише повні сегменти
full = df[~df['partial']]

# Top 10 roughest segments
print(full.nlargest(10, 'iri_multi')[['seg_id', 's_start', 'iri_multi']])

# Average IRI (NaN-сегменти поза діапазоном швидкості не враховуються)
print(f"Mean IRI: {full['iri_multi'].mean():.2f} m/km")
```

---

### File 2: `roughness.geojson`

**Purpose:** геометрія сегментів з метриками для QGIS / Kepler.gl / Folium

- `LineString` на сегмент (координати у порядку `[lon, lat]`); якщо в сегменті
  менше 2 точок — `Point`
- Properties: `seg_id`, `s_start`, `s_end`, `length_m`, `partial`, `iri_multi`,
  `iri_psd_raw`, `iri_psd`, `grms`, `mean_speed_kmh`, `speed_valid`,
  `low_speed_class`, `needs_class12_survey`, `dx_le_03_share`, `anomaly_count`,
  `events_per_km` (+ PSD-діагностика)
- `low_speed_class` / `needs_class12_survey` / `events_per_km` дозволяють
  відфільтрувати кандидатів на обстеження профілометром прямо в QGIS:
  `needs_class12_survey = true`
- Не-скінченні значення серіалізуються як `null` (`allow_nan=False`) — файл
  завжди валідний JSON

### File 3: `events.geojson`

`Point` на кожен семпл із `|a_vertical| > 10 м/с²`; properties:
`event_type = "threshold_10ms2"`, `distance_m`, `time_s`.

### File 4: `segments_map.html`

**Purpose:** інтерактивна карта сегментів (Folium / Leaflet)

- сірий полілайн — весь GPS-трек
- сегменти забарвлені за `iri_multi`, нормованим на [min, max] цього запису:
  зелений `#1A9641` < 0.33, синій `#2C7BB6` < 0.66, помаранчевий `#FF7F00` < 0.85,
  червоний `#D7191C` вище; чорний — сегмент із `NaN` IRI
- сегменти з `needs_class12_survey = True` (< 20 км/год) — пурпурові `#FF00FF`
  і на 2 px товщі: вони поза шкалою IRI, бо числа для них немає. Легенда
  «Потребує обстеження профілометром (клас 1/2)» додається лише тоді, коли такі
  сегменти є на карті (за політики `ignore` їх немає взагалі)
- кожна лінія має чорну обводку (видно на будь-якому фоні)
- tooltip: seg_id, межі, IRI_multi, IRI_psd, Grms, швидкість, anomalies,
  events/km, а для low-speed сегментів ще й `low_speed_class`

> Колір **відносний у межах запису**, а не абсолютна шкала IRI — два різні
> записи порівнювати за кольором не можна.

### File 5: `report.md`

Секції: Generated Artifacts, Summary, Data Window, Configuration (усі фактичні
константи та коефіцієнти, зокрема застосована `--low-speed-policy`), Sampling
Compliance, IRI Statistics, PSD Scalar Mode Diagnostic (4 режими), Top 10 Worst
Segments, «Сегменти з низькою швидкістю (< 20 км/год)», Assumptions & Limitations.

Секція про низьку швидкість містить застосовану політику, кількість таких
сегментів із загальної (і скільки виключено за політики `ignore`), таблицю
`seg_id | length_m | mean_speed_kmh | events_per_km | low_speed_class` та
пояснення, чому числовий IRI для них не наводиться. Вона друкується завжди:
якщо низькошвидкісних сегментів немає, це прямо зазначено.

### File 6: `plots/`

PNG (150 DPI) + PDF (вектор, стиль SciencePlots) для кожного графіка:
`speed_vs_distance`, `accel_vs_distance`, `metrics_vs_distance` (Grms + IRI_multi),
`iri_psd_vs_distance`.

---

## Troubleshooting

### Error 1: `FileNotFoundError: [Errno 2] No such file`

**Symptom:**
```
FileNotFoundError: [Errno 2] No such file or directory: 'storage/data/sensor_data.csv'
```

**Cause:** відносний шлях, але поточна директорія — не корінь проєкту

**Solution:**
```powershell
# Option A: Use absolute path
python main.py --input "<full_path_to_data>\sensor_data_20250729_163334.csv" --out out\run1

# Option B: Change directory first (recommended)
cd <workspace_root>
python main.py --input "storage\data\sensor_data_20250729_163334.csv" --out out\run1
```

---

### Error 2: `ValueError: Unexpected CSV header`

**Symptom:**
```
ValueError: Unexpected CSV header in <file>: expected ['Time', 'Type', 'X', 'Y',
'Z', 'Latitude', 'Longitude'], found [...]
```

**Cause:** заголовок не відповідає контракту v2 (перейменовані/зайві/переставлені колонки)

**Solution:** привести файл до контракту — рівно ці 7 колонок у цьому порядку.
Metadata-рядки перед заголовком дозволені лише якщо починаються з `#`.

Споріднені помилки того ж походження:
- `No usable Accelerometer rows in <file>: Type values found = [...]` —
  значення `Type` не збігаються з `Accelerometer` / `Gyroscope` / `Location`
  (наприклад, старі `ACCEL` / `GPS`)
- `Error tokenizing data` — у рядку більше 7 полів (читання свідомо падає,
  а не зсуває колонки: `index_col=False`)

---

### Error 3: `ImportError: No module named 'folium'`

**Symptom:**
```
ImportError: No module named 'folium'
```

**Cause:** virtual environment не активовано або залежності не встановлені

**Solution:**
```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -c "import folium; print(folium.__version__)"
```

---

### Error 4: `ValueError: No Location rows ... requires GPS`

**Symptom:**
```
ValueError: No Location rows in <file>: distance-based analysis requires GPS.
Re-record with location permission granted.
```

**Cause:** запис зроблено без дозволу на локацію (у файлі немає рядків `Location`)

**Solution:** перезаписати маршрут із наданим дозволом. Підставляти лінійний
лічильник замість реальної дистанції не можна — 100 м бін без GPS не гарантує
однакової щільності семплів, тому пайплайн падає, а не «здогадується».

---

### Error 5: `ValueError` про fs або гравітацію

**Symptom:**
```
Derived sampling rate 0.1 Hz is outside the plausible band 5-1000 Hz
(detected Time unit: s). Check the Time column of <file>.

Estimated gravity magnitude 0.98 m/s^2 deviates more than 10% from 9.80665 m/s^2 ...
```

**Cause:** одиниця колонки `Time` або одиниці акселерометра не відповідають
контракту (наприклад, значення в `g` замість `m/s²`)

**Solution:** перевірити преамбулу `# units:` рекордера та формат `Time`.
Обидві перевірки навмисно падають до обчислення метрик — інакше Grms і IRI
були б зміщені на порядок.

---

### Error 6: негативний `IRI_psd`

**Symptom:**
```
iri_psd_raw = -0.81, iri_psd = 0.0
```

**Cause:** Eq.3 з книжковими коефіцієнтами (`0.774*sqrt(PSD) - 0.825`) не
калібрована під цей телефон/автомобіль

**Expected:** див. [06_threats](06_threats_to_validity_and_limitations.md) —
на датасеті 2025-07-29 `iri_psd_raw` від'ємний у 100% повних сегментів.
Сире значення зберігається, `iri_psd` кліпається до 0.

**Solution:**
- **Short-term:** використовувати `iri_multi` як основну метрику
- **Long-term:** перекалібрувати A, B за ground truth
  (див. [07_roadmap](07_future_work_roadmap.md))

---

## FAQ

### Q1: Чому IRI_psd = 0.0 у багатьох сегментах?

**A:** `iri_psd` — це `max(iri_psd_raw, 0)`:

```
IRI_psd_raw = 0.774 * sqrtPSD - 0.825   (A_sqrt_psd, B_const з metrics/iri.py)
→ від'ємний, поки sqrtPSD < 0.825 / 0.774 = 1.066 g/sqrt(Hz)
→ у road_segments.csv iri_psd = 0.0, а iri_psd_raw зберігає сире значення
```

На датасеті 2025-07-29 `iri_psd_raw` від'ємний у **100%** повних сегментів —
це ознака того, що книжкові коефіцієнти не калібровані під цей телефон, а не
ідеальна дорога.

`iri_psd` дорівнює `NaN` (а не 0), якщо:
- `speed_valid = False` (середня швидкість поза 20-100 км/год), або
- у сегменті менше ніж `fs * 2` семплів після distress removal (±0.5 с навколо
  кожної аномалії) — PSD не обчислюється, вигаданого числа не пишемо

**Solution:** використовувати `iri_multi` (Eq.6) як основну метрику.

---

### Q2: Чому anomaly_count = 0 у всіх сегментах?

**A:** Детектор — абсолютний поріг, а не ML-класифікатор:
`|a_vertical| > 10 м/с²` (`anomaly/threshold.py`), причому по **gravity-removed**
вертикалі у world frame. Книжковий поріг задавався для сирого показу
акселерометра, тому на цьому сигналі він фактично не калібрований і кількість
подій занижена. На датасеті 2025-07-29 детектується 0 подій.

Параметра для зміни порогу в CLI немає — це константа `ANOMALY_THRESHOLD_MS2`
у `cli.py`. Див. [07_roadmap](07_future_work_roadmap.md) щодо калібрування.

---

### Q3: Як інтерпретувати IRI values?

**A:** (based on WorldBank classification)

| IRI Range | Classification | Road Condition |
|-----------|----------------|----------------|
| 0-2 m/km | Excellent | Newly paved |
| 2-4 m/km | Good | Minor wear |
| 4-6 m/km | Fair | Moderate roughness |
| 6-8 m/km | Poor | Significant distress |
| > 8 m/km | Very Poor | Major potholes/cracks |

**Our dataset** (поточний прогін, 150 повних сегментів):
- Mean IRI_multi = 2.99 m/km → **GOOD**
- Max IRI_multi = 6.72 m/km → **POOR**
- 19 сегментів мають `speed_valid = False` → IRI = NaN і в середнє не входять

---

### Q4: Чому Grms і IRI_multi не ідеально корелюють?

**A:** IRI_multi (Eq.6, GENERIC) включає additional factors:

```
IRI_multi = 50.32*Grms - 0.06*Speed_kmh + 0.17*Npeop
            - 1.86*Stif - 0.90*DampF - 0.78*TyreS + 6.68
```

**Speed effect:**
- High speed → vehicle "floats" → lower perceived roughness
- Coefficient: -0.06 (negative → damping)

**Vehicle params:**
- Значення `npeop = stif = dampf = tyres = 1.0` — припущення
  (`IRI_MULTI_DEFAULT_PARAMS`), вони не вимірювались
- Soft suspension (low stif) → lower IRI (absorbs bumps)

**Conclusion:** Grms ~ IRI сильно корелюють, але не 1:1.

---

### Q5: Як зберегти results для конкретної дати?

**A:** Через `--out`:

```powershell
python main.py `
  --input storage\data\sensor_data_20250729_163334.csv `
  --out storage\results\official_run_2025_07_29
```

**Structure:**
```
storage/results/
├── official_run_2025_07_29/    ← named output
│   ├── road_segments.csv
│   ├── roughness.geojson
│   ├── events.geojson
│   ├── segments_map.html
│   ├── report.md
│   └── plots/
├── results_20260110_013358/    ← auto-generated timestamp (main.py без --out)
│   └── ...
```

---

### Q6: Чи можна запустити на real-time data (Android app)?

**A:** **Currently: NO** (post-processing only)

**Future work:** See [07_roadmap](07_future_work_roadmap.md)

**Workaround:** Collect data → transfer CSV → analyze offline (~25 sec)

---

### Q7: Як налаштувати для іншого phone/vehicle?

**A:** Two options:

**Option 1: Use defaults** (current approach)
- Assumes generic phone/vehicle
- Good for **relative comparisons** (segment A vs B)
- Absolute IRI може бути biased

**Option 2: Calibrate** (future work)
- Collect ground truth IRI (profilometer)
- Підібрати `IRI_MULTI_DEFAULT_PARAMS` / коефіцієнти Eq.3 у коді
  (CLI-прапорців для цього немає)
- See [07_roadmap](07_future_work_roadmap.md)

---

### Q8: Де знайти sample datasets для testing?

**A:** Included in repo:

```
storage/data/
└── sensor_data_20250729_163334.csv
```

**Characteristics** (перевірено на файлі):
- Route: Urban mixed-traffic
- Rows: 188596 — 93399 `Accelerometer`, 93398 `Gyroscope`, 1799 `Location`
- Duration: ~30 хв (1799 с)
- Sampling: 52.6 Hz (accel, median dt = 19 мс), 1 Hz (GPS)
- Distance у вікні аналізу: 15123.7 м, 152 сегменти (2 `partial`)
- Файл записаний до контракту v2 → без `#`-преамбули (читається так само)

Синтетичні CSV для тестів генерує `analyzer/tests/conftest.py::write_drive_csv`.

---

### Q9: Як експортувати у GeoJSON для QGIS?

**A:** Це вже робиться автоматично: `roughness.geojson` (сегменти,
`LineString`) та `events.geojson` (аномалії, `Point`) створюються кожним
прогоном, координати у порядку `[lon, lat]`, відсутні метрики — `null`.

**Usage у QGIS:**
```
Layer → Add Layer → Add Vector Layer → roughness.geojson
```

---

## Додаткові ресурси

### Documentation Links

- **Theory:** [01_background_and_problem_statement.md](01_background_and_problem_statement.md)
- **Methods (new):** [02_methods_new_pipeline.md](02_methods_new_pipeline.md)
- **Methods (legacy):** [03_methods_legacy_pipeline.md](03_methods_legacy_pipeline.md)
- **Validation:** [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md)
- **Limitations:** [06_threats_to_validity_and_limitations.md](06_threats_to_validity_and_limitations.md)
- **Roadmap:** [07_future_work_roadmap.md](07_future_work_roadmap.md)

### External References

1. **IRI Standard:** ASTM E1926-08, "Computing International Roughness Index"
2. **Smartphone Class III:** ASTM E950-09, "Classification of Devices"
3. **Formulas:** зовнішній довідник `02_FORMULAS_TEST_MAP_UNIFIED.md`
   (у репозиторії його немає). Коефіцієнти, що виконуються, — у
   `analyzer/src/road_quality_analyzer/metrics/iri.py`

### Support

**Issues/Questions:** Create GitHub issue або contact project maintainer

---

**Наступні кроки:**
- Run analysis: `python main.py --input <path> --out <dir>`
- Explore results у `storage/results/` directory
- Review [00_index.md](00_index.md) для navigation

---

## How to Cite

```bibtex
@software{roadsensor_analysis_2025,
  title = {RoadSensorRecorder Analysis Pipeline},
  author = {Your Name},
  year = {2025},
  url = {https://github.com/yourusername/RoadSensorRecorder_Analysis},
  note = {Smartphone-based IRI estimation with orientation correction}
}
```

**Paper citation** (якщо published):
```
Author, A., Author, B. (2025). Improving Smartphone-Based Road Roughness Estimation via Gravity Alignment. 
Journal of Transportation Engineering, XX(Y), pages. DOI: XX.XXXX/XXXXX
```

---

## Веб-адмінка

Локальна адмінка для повного циклу: завантаження CSV → запуск аналізу → перегляд
результатів (звіт, графіки, Leaflet-мапа) → глобальна мапа всіх зон → дашборд →
калібрування коефіцієнтів проти профілометра (Phase 3).
Дизайн: `docs/superpowers/specs/2026-08-19-web-admin-design.md`,
`docs/superpowers/specs/2026-08-20-admin-calibration-design.md`,
`docs/superpowers/specs/2026-08-20-admin-phase2-aggregation-design.md`.

**Передумова (Phase 3):** порівняння з еталоном профілометра виконує ту саму
математику, що й дисертаційне дослідження, через пакет `studies/profilometer_validation`,
встановлений editable і використаний backend'ом як бібліотека:

```bash
pip install -e studies/profilometer_validation
```

Без цього кроку backend впаде на імпорті `src/services/comparison.py`. Пакет не
входить у workspace `requirements.txt` — встановлюється окремо (як і сам `analyzer`).

**Запуск (два термінали):**

```powershell
# Backend (FastAPI, http://127.0.0.1:8000)
cd web_admin/backend
..\..\.venv\Scripts\python.exe -m uvicorn src.main:app --reload

# Frontend (Angular dev server, http://localhost:4200)
cd web_admin/frontend
npx ng serve --proxy-config proxy.conf.json
```

- Прев'ю файлу при завантаженні показує профіль авто і бейдж запису
  (чиста зупинка / обірваний / pre-v2.1) з `recording_meta`.
- Сторінка рану рендерить `report.md`, графіки, таблицю сегментів (без числового
  IRI для low-speed — інваріант аналізатора) і Leaflet-мапу, а також (Phase 3)
  чіп застосованих коефіцієнтів, список артефактів рану і блок порівнянь.
- Кнопка «Порівняти з іншим раном» на сторінці рану (активна лише коли
  поточний ран `done` і є хоча б один інший `done`-ран того самого файла) веде
  на run-vs-run порівняння — [докладніше нижче](#порівняння-двох-ранів-одного-файла-run-vs-run).
- Дашборд (`/dashboard`) має розбивку за типом авто —
  [докладніше нижче](#дашборд).
- Тести backend: `cd web_admin/backend && python -m pytest` (стаб аналізатора;
  повний цикл — `-m slow`). Тести frontend: `npx ng test --watch=false`.

### Порівняння двох ранів одного файла (run-vs-run)

`GET /api/files/{file_id}/compare?run_a=<id>&run_b=<id>` (фронтенд-роут
`/runs/:id/compare/:other`) порівнює два завершені рани **того самого файла**
сегмент-у-сегмент за `seg_id`. Гарди (`409`, український текст): `run_a ==
run_b` → «оберіть два різні рани»; ран не з цього файла → «ран не належить
цьому файлу»; хоч один ран не `done` → «обидва рани мають бути завершені».

Обидва боки читають `road_segments.csv` і застосовують ту саму `eq6_bias`-корекцію
IRI_multi, що й сторінка рану (`bias_of(run.params['coefficients'])`) —
інакше два рани, що різняться лише підтвердженим набором `eq6_bias`, показали
б нульову дельту, хоча самі сторінки ранів відрізняються на цей зсув.
З'єднання рядків — `inner join` за `seg_id`: для одного файлу сітки збігаються,
якщо тільки різна `--low-speed-policy` не прибрала сегмент з одного боку
(`ignore`) — тоді зіставлених рядків менше, ніж об'єднання `seg_id`, без помилки.

Сервер рахує **лише** `delta_iri_multi = iri_multi_b - iri_multi_a`
(`CompareSegmentRow`, `web_admin/backend/src/api/schemas.py`); `iri_psd`,
`grms` і `mean_speed` повертаються парами `_a`/`_b` без готової дельти.
Рядки з `|delta_iri_multi| > 0.5` підсвічуються в таблиці фронтенду.

### Дашборд

`GET /api/dashboard` (сторінка `/dashboard`) агрегує дані по двох свідомо
різних популяціях, і на верхньому рівні, і в розрізі `vehicle_type` (частки за
типом авто в сумі дають підсумок «Всі»):

- `files_total` / `runs_done` — **усі** рядки `SourceFile` і **всі**
  `AnalysisRun` зі статусом `done`, без дедуплікації: кожен файл (видалений
  чи ні, з раном чи без) і кожен завершений ран (перезапуски рахуються окремо).
- `km_total` / `low_speed_total` / `mean_iri_multi` / `iri_histogram` /
  `worst_segments` — рахуються лише з **останнього** `done`-рану кожного
  файла (`_latest_done_run`); гістограма і список найгірших сегментів
  додатково читають CSV сегментів кожного такого рану.

`vehicle_type` береться з `SourceFile.recording_meta` через
`coefficients.vehicle_type_from_meta` (той самий геттер, що й сторінка
файлів) — **не** з `recording_meta.json` конкретного рану. Відсутній тип
авто мапиться у `невідомо`; чипи розбивки на UI не показуються, коли типів
узагалі немає (порожні дані) або коли єдиний наявний тип — `невідомо`
(тривіальна розбивка — нема з чим порівнювати).

`by_vehicle_type[type]` має ту саму форму, що й верхній рівень (`files_total`,
`runs_done`, `km_total`, `low_speed_total`, `mean_iri_multi`, `iri_histogram`),
без `worst_segments` (той список лишається спільним, не розрізаним за типом).
Чипи «Всі» / конкретний тип на сторінці перемикають, яку з цих секцій бачать
KPI-картки та гістограма — запит до сервера один, розбивка вже готова у відповіді.

### Калібрування (Phase 3)

Вкладка «Калібрування» додає еталонні дані профілометра, порівняння з ранами
аналізатора та керовані базою коефіцієнти IRI.

**Еталони профілометра (`ReferenceDataset`)**

Завантаження офіційної xlsx-форми вимірювання IRI (20 колонок, метадані-рядки
над заголовком `км|м|км|м|канал 1…`). Парсер `src/services/reference_forms.py`
шукає заголовок серед перших 40 рядків, читає 10 каналів IRI разом із
координатами початку/кінця кожного інтервалу, визначає крок пікетажу
(`step_m`, зазвичай 10 м) і перевіряє неперервність (розриви/перекриття
пікетажу, канали 9-10, що дублюють канал 8) — усе це потрапляє у `warnings`.
Структурні збої (нечитний файл, відсутній заголовок, менше 5 рядків даних)
кидають `ValueError`, і завантаження відхиляється (422).

Результат зберігається як `storage/reference/<id>/original.xlsx` +
`intervals_10m.csv` — похідний CSV у форматі, який точно збігається з тим,
що читає `profilometer_validation.match.load_form_10m`, тому порівняння
споживає його без додаткових перетворень.

`measured_at` — це ручне поле форми завантаження, а не значення з xlsx: дата
в самій формі часто застаріла (шаблон копіюють з попереднього виміру), тому
дату виміру вводить оператор під час завантаження.

**Сторінка еталона** (`/calibration/references/:id`) показує метадані
(дорога/напрям/смуга/категорія, крок пікетажу, кількість інтервалів,
`parse_warnings`), Leaflet-мапу інтервалів (`GET /api/references/{id}/geojson`,
через спільний `shared/segment-map.ts`) і графік профілю IRI еталона поверх
таблиці інтервалів (пагінація по 200 рядків; стовпець «канал 1–8» — діапазон
min–max по восьми каналах, а не одне значення). Графік і таблиця читають
`GET /api/references/{id}/intervals` (`iri_ref = mean(ch1..ch8)`) і рендеряться
спільним `MultiLineChart` — тим самим компонентом, що й профіль на сторінці
агрегату. Пікетаж інтервалу для графіка/таблиці — середина
`[km_start:m_start, km_end:m_end]`, та сама конвенція, що й `chainage_m` у
`build_reference_geojson`, тому таблиця, графік і мапа узгоджені.

**Порівняння (`Comparison`)**

Порівняння запускається для пари (run × reference) і виконує геозіставлення
100-метрових сегментів рану з 10-метровими інтервалами еталона
(`profilometer_validation.match.windowed_reference`), рахує валідаційну
статистику (`profilometer_validation.calibrate`) і зберігає артефакти під
`storage/results/comparisons/cmp<id>_<stamp>/`:

```
cmp<id>_<stamp>/
├── matched_pairs.csv     # зіставлені пари сегмент↔інтервал
├── stats.json            # validation / eq3_fit / eq6_bias / gates / effective_n / influence
├── chart_data.json       # компактні серії для SVG-графіків фронтенду
└── figures/              # графіки PDF (вектор) + PNG (scatter, Bland–Altman, chainage overlay)
```

Гарди перед постановкою в чергу (`409`, український текст): ран ще не
`status == 'done'` → «ран ще не завершено»; еталон видалено
(`source_deleted`) → «еталон видалено — файл еталонних інтервалів більше не
доступний»; еталон не 10-метрова форма (`step_m != 10`) → «еталон має бути
10 м формою…». Під час виконання завдання (статус `failed`, текст у
`Comparison.error`): bbox рану й еталона не перетинаються географічно,
артефакти рану відсутні на диску, замало зіставлених пар (< 5). «Гейти»
(`eq3_r2_pass`, `eq6_bias_mae_pass` за порогами R² ≥ 0.85, MAE ≤ 0.5) — це
індикатори для людини, а не автоматичне рішення: підтвердження набору
коефіцієнтів завжди ручне.

`chart_data.json` — компактний зріз під SVG-графіки без сторонніх бібліотек:

| Ключ | Вміст |
|------|-------|
| `scatter` | `[{seg_id, psd_sqrt_scalar, iri_ref, iri_multi, chainage_m}, …]` |
| `profile` | `[{chainage_m, iri_ref, iri_multi, iri_multi_bias_corrected, seg_id}, …]` |
| `bland_altman` | `[{seg_id, mean, diff}, …]` |
| `eq3_fit` | `{A, B, r2, mae, n}` |
| `bias` | середній зсув Eq.6 (число, м/км) |
| `gates` | ті самі порогові індикатори, що й у `stats.json` |

**Мультипроїзні порівняння (`AggregateComparison`)**

Порівняння одного еталона з **кількома** ранами тієї самої дороги (мінімум 2,
`MIN_RUNS`) — репрезентативніша оцінка, ніж один проїзд, і єдиний спосіб
оцінити повторюваність і ефект швидкості. Математика — виключно з
дисертаційного пакета `profilometer_validation.aggregate`; backend-оркестратор
(`src/services/aggregate.py`) сам документує це у своєму docstring як
«unchanged — the admin runs exactly what the dissertation reports» — він лише
оркеструє: гарди, зіставлення по кожному рану, артефакти, графіки.

Методика:

1. Кожен ран зіставляється з еталоном тим самим `windowed_reference`, що й
   одиночне порівняння (спільні параметри з `services.comparison`) — агрегат
   з одного рану відтворює те саме порівняння.
2. Усі пари з усіх ранів об'єднуються і розбиваються на фіксовані 100-метрові
   біни **по пікетажу еталона** (`bin_pairs`, `BIN_WIDTH_M = 100.0`) — свідоме
   рішення: сегменти різних ранів між собою не вирівняні (у кожного свій
   `s=0`), а пікетаж еталона — спільна система координат.
3. `per_bin_stats` пулить усі проїзди в біні в `mean_iri`/`std_iri`/`min_iri`/
   `max_iri`/`n_passes`.
4. **Bias з довірчим інтервалом** (`bias_with_ci`): середня різниця
   `mean_iri - iri_ref` по бінах, t-CI з ефективним n Бартлетта
   (`profilometer_validation.calibrate.effective_n`, корекція на
   автокореляцію послідовних 100-метрових бінів; `n_eff` обмежено зверху
   номінальним `n_bins`).
5. **Повторюваність** (`repeatability_sd`): пулований within-bin std лише по
   бінах, проїханих ≥ 2 рази (`sigma_r`); `None`, якщо жоден бін не має повтору.
6. **Ефект швидкості** (`speed_effect`): demeaned (within-bin fixed-effects)
   нахил відхилення від еталона на швидкість, лише по бінах з ≥ 2 проїздами;
   `None`, якщо розкид середніх швидкостей проїздів < 3 км/год (недостатньо
   інформації для оцінки нахилу) або жоден бін не має повтору.
7. Агрегований профіль (пулований `mean_iri` на бін проти `iri_ref`)
   валідується тими самими `profilometer_validation.calibrate.validation_stats`,
   що й одиночне порівняння (ρ, MAE).

Дублікат `run_id` у списку рахується як **один** прохід, а не два
(`unique_run_ids` — order-preserving де-дуп): інакше один ран, вписаний двічі,
роздував би `n_runs` і підробляв оцінку повторюваності.

REST: `POST /api/aggregate-comparisons` `{reference_id, run_ids[], params}` →
`201 AggregateOut`; гарди — менше двох унікальних ранів (`422`, «потрібно
щонайменше два рани»), будь-який ран не `done` (`409`, «ран #N ще не
завершено»), еталон видалено/не 10-метровий (`409`, ті самі повідомлення, що
й у порівняння). `GET /api/aggregate-comparisons` / `GET .../{id}` — список і
деталі; `DELETE .../{id}` знімає прив'язку
`CoefficientSet.aggregate_comparison_id` (знімок статистики лишається) і
видаляє каталог артефактів; `GET .../{id}/artifacts/{name}` — той самий
контракт serving'у, що й у порівняння (`resolve()` + `is_relative_to`, `403`
при виході за межі каталогу).

Під час виконання завдання (статус `failed`, текст у
`AggregateComparison.error`, з позначкою, який саме прохід зламався):
артефакти рану відсутні на диску, bbox рану й еталона не перетинаються
географічно, замало зіставлених пар для конкретного рану (той самий поріг
`MIN_PAIRS`, що й одиночне порівняння), або після відсіву нескінченних
значень не лишилось жодного 100-метрового біна.

Артефакти лежать під `storage/results/aggregates/agg<id>_<stamp>/`:

```
agg<id>_<stamp>/
├── per_pass_pairs.csv     # усі зіставлені пари, з колонкою run_id
├── per_bin.csv            # один рядок на 100-метровий бін
├── aggregate_stats.json   # bias/repeatability/speed_effect/validation, повний
├── chart_data.json        # profile[] (lo/hi = min/max проїздів у біні) + bias/repeatability/speed_effect/validation
└── figures/               # fig_agg_profile (профіль + розкид проїздів), fig_agg_speed (лише якщо speed_effect не null)
```

Сторінка `/calibration/aggregates/:id` рендерить `chart_data.json` через
спільний `MultiLineChart` (еталон + середнє смартфона, смуга `lo..hi` —
розкид проїздів у біні), таблицю бінів і, для завершеного агрегату, той самий
`CreateSetDialog`, що й сторінка одиночного порівняння (провенанс `{kind:
'aggregate', id}`; попередній вибір телефону/авто бере ключі ідентичності з
**першого** пулованого рану — набір мислиться як один телефон в одному авто).
Видалення одного з пулованих ранів не видаляє й не перераховує агрегат:
`mark_stale_for_run` лише позначає `summary.stale = true` — історичний
результат лишається читабельним, але явно поміченим як більше не відтворюваним.

**Набори коефіцієнтів (`CoefficientSet`)**

Набір — це `{model: 'eq3'|'eq6_bias', params: {A,B}|{bias}, vehicle_type,
phone_model, device_id, vehicle_id, status: draft|confirmed|archived}`.
`device_id`/`vehicle_id` — це ключ ідентичності контракту v3.1 (телефон сам
пише `# device_id=` і `# vehicle_id=` у файл); діалог створення набору
заповнює їх автоматично з рану, ручного введення немає. Життєвий цикл:

1. **draft** — створюється зі `stats.json` завершеного порівняння
   (`POST /api/coefficient-sets`); вироджений фіт (нечислові/нескінченні
   A/B/bias) відхиляється (409).
2. **confirm** — `POST /coefficient-sets/{id}/confirm`; попередній
   підтверджений набір з тим самим **ключем резолюції** автоматично
   архівується — не більше одного підтвердженого набору на комбінацію. Ключ
   архівування збігається з тим, що порівнює відповідний рівень резолюції
   (див. нижче): для набору з ідентичністю це `(model, device_id, vehicle_id)`
   **без** `vehicle_type`/`phone_model` (рівень 1 їх не порівнює, тому й тут
   вони ігноруються — інакше два підтверджені набори володіли б тим самим
   «телефон+авто»); для решти — повний NULL-безпечний ключ `(model,
   vehicle_type, phone_model, device_id, vehicle_id)`, тому набір з
   ідентичністю і legacy-набір того ж авто співіснують. Відповідь містить
   `reanalyze_candidates` — кількість файлів того ж `vehicle_type`, готових до
   переаналізу.
3. **reanalyze** — `POST /coefficient-sets/{id}/reanalyze` створює **нові**
   рани для файлів того ж `vehicle_type`; уже виконані рани заднім числом
   не змінюються.
4. **archive** — ручне архівування без підтвердженого замінника.

Резолюція коефіцієнтів під час постановки рану в чергу відбувається
**виключно** через `src/services/coefficients.resolve_for_meta`, окремо для
моделей `eq3` і `eq6_bias`, чотири рівні від найточнішого до книжкового:

1. `(model, device_id, vehicle_id)` — точний збіг ідентичності «цей телефон у
   цьому авто»; діє лише тоді, коли **і** запис, **і** набір мають обидва
   ключі (контракт v3.1). Тип авто тут не порівнюється: профіль авто вже
   названий своїм UUID;
2. `(model, vehicle_type, phone_model)` — legacy-ключ: точний збіг телефону
   (з `# device:` преамбули запису) і типу авто;
3. `(model, vehicle_type, phone_model IS NULL)` — набір без прив'язки до
   конкретного телефону;
4. жодного підтвердженого набору не знайдено → аналізатор використовує
   книжкові константи з коду (`analyzer/src/road_quality_analyzer/metrics/iri.py`) —
   вони **ніколи** не потрапляють у базу даних.

Рівні 2 і 3 вимагають, щоб у набору `device_id` і `vehicle_id` були NULL:
набір, калібрований для одного авто, ніколи не «протікає» на інше авто того
самого типу, а «пів-ідентичності» (один ключ без другого) не резолвиться
взагалі — `preview-resolution` показує для такого ключа 0 файлів.
Записи, зроблені до контракту v3.1, не мають `device_id` і резолвляться
рівнями 2–4 точно так, як раніше.

`POST /api/coefficient-sets/preview-resolution` приймає **повний** ключ і
відповідає справжньою інверсією резолюції: файл, який уже виграє більш
специфічний підтверджений набір, у прев'ю не рахується — інакше «Впливатиме
на N файлів» обіцяло б файли, яких новий набір ніколи не торкнеться. Саме тому
0 у прев'ю не завжди означає «неправильний ключ»: файли можуть бути просто
перекриті специфічнішим підтвердженим набором.

Прев'ю рахує по рівню свого ключа, а `reanalyze_candidates` — свідомо по
всьому `vehicle_type` (це не список файлів набору, а лише пропозиція
перезапуску; кожен новий ран усе одно резолвить свої коефіцієнти сам, тому
надлишкові рани нічого не псують). Наслідок-асиметрія: набір з ідентичністю і
`vehicle_type = NULL` показує N файлів у прев'ю (рівень 1 не порівнює тип
авто), але 0 кандидатів на переаналіз.

Без визначеного `vehicle_type` (запис до v3, без блоку профілю авто)
резолюція одразу повертає книжкові константи: коефіцієнти каліброване по
типу авто, тому невідомий тип не успадковує чужий набір.

Результат резолюції знімком записується у `AnalysisRun.params['coefficients']`
і в артефакт `calibration.json` рану (лише коли резолюція щось знайшла) —
пізніше редагування набору ніколи не переписує історію вже виконаного рану.
Eq.3-набір передається аналізатору як реальні `iri_psd_A`/`iri_psd_B`
(артефакти `road_segments.csv`/`roughness.geojson` рахуються з ними одразу);
Eq.6-зсув застосовується лише на боці відповіді API: `mean_iri_multi_corrected`
у зведенні рану (`AnalysisRun.summary`) і `iri_multi_corrected` у рядках
сегментів (`GET /api/runs/{id}/segments`) — артефакти аналізатора зсув ніколи
не змінює. Ключ `iri_multi_bias_corrected` — це окрема річ: колонка
порівняльних графіків (`chart_data.json`, `matched_pairs.csv`). Коефіцієнти,
надіслані клієнтом у `params`, завжди видаляються перед резолюцією
(anti-spoofing) — керувати калібруванням можна лише через підтверджені набори.

**Залежність Eq.3 ⇄ Eq.6**

Набір `eq6_bias` завжди фітується проти ранів, порахованих з конкретними
коефіцієнтами Eq.3: провенанс — `comparison → run →
params['coefficients']['eq3']['set_id']`. Тому підтвердження **нового** набору `eq3` робить
раніше підтверджений `eq6_bias` застарілим: зсув міряли для іншої шкали
IRI_psd. Порядок дій після зміни Eq.3: підтвердити новий `eq3` → переаналіз
(`reanalyze`) → нове порівняння на свіжому рані → вивести з нього новий
`eq6_bias` і підтвердити його; старий набір архівувати. Автоматично цей
зв'язок не перевіряється — це рішення оператора, тому перед підтвердженням
Eq.3 варто пройти ланцюжок провенансу вручну.

**Нова палітра мапи**

Усі мапи (глобальна, сторінка рану) рендеряться через один спільний
компонент `shared/segment-map.ts` — Leaflet-версія замінила попередній
folium iframe на сторінці рану. Шкала важкості IRI_multi — контракт даних,
а не тема UI, тому кольори задані сирими hex-значеннями:

| Колір | hex | Поріг |
|-------|-----|-------|
| зелений | `#00a63e` | IRI < 2.5 |
| жовтий | `#f5c400` | 2.5 ≤ IRI < 4 |
| помаранчевий | `#ff7300` | 4 ≤ IRI < 6 |
| червоний | `#d81e2c` | IRI ≥ 6 |
| магента | `#FF00FF` | `needs_class12_survey = true` — контракт «числа немає», переважає будь-яке IRI |
| сірий | `#8b93a3` | IRI недоступний з іншої причини |

Обводка сегментів (casing) інверсна темі мапи, а не темі UI: на темній темі —
світла обводка `rgba(245,245,244,0.9)`, на світлій — темна
`rgba(15,18,25,0.85)`, товщина 10px під лінією даних (6px, 9px при hover) —
так лінія лишається читабельною на будь-якому фоні базового шару CARTO.

**`RQA_REFERENCE_DIR`**

Новий env var (за замовчуванням `storage/reference`) — корінь зберігання
завантажених еталонів (`<id>/original.xlsx`, `<id>/intervals_10m.csv`), за
тим самим шаблоном, що й `RQA_DATA_DIR`/`RQA_RESULTS_DIR` (`src/core/config.py`).
