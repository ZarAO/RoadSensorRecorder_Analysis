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
python main.py --input "data\sensor_data_20250729_163334.csv" --out results\my_run
```

`main.py` — тонка обгортка: без `--input` він бере найновіший
`data/sensor_data_*.csv`, без `--out` створює `results/results_<timestamp>/`.

**Output:**
```
results/my_run/
├── road_segments.csv       (метрики на 100 м сегмент, 24 колонки)
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
```

**Contents of `requirements.txt`:**
```
numpy>=2.3.0
pandas>=2.3.0
scipy>=1.16.0
matplotlib>=3.10.0
scienceplots>=2.1.0
folium>=0.20.0
pytest>=7.0.0
```

**Verification:**
```powershell
python -c "import numpy, pandas, scipy, matplotlib, scienceplots, folium; print('OK')"
# Expected: OK

python -m pytest tests -q
# Expected: 163 passed
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
обидва мають fallback (останній CSV у `data/`, `results/results_<timestamp>/`).

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

---

## CLI Reference

### `analyze` Command

**Full syntax:**
```powershell
python -m road_quality_analyzer analyze --input <csv_path> --out <dir> `
  [--low-speed-policy {very-poor|poor|invalid|ignore}]
```

**`--low-speed-policy`** (за замовчуванням `invalid`) — єдиний необов'язковий
параметр. Він керує сегментами, середня швидкість яких < 20 км/год: дорога
настільки погана, що швидше проїхати неможливо, а саме там акселерометрична
оцінка IRI найменш валідна.

| Значення | Що відбувається з low-speed сегментом |
|----------|----------------------------------------|
| `very-poor` | `low_speed_class = very_poor`, рядок лишається в усіх артефактах |
| `poor` | `low_speed_class = poor`, рядок лишається |
| `invalid` | `low_speed_class = invalid`, рядок лишається (за замовчуванням) |
| `ignore` | рядок виключено з `road_segments.csv`, `roughness.geojson` і карти; `report.md` усе одно рахує та перелічує ці сегменти |

`iri_multi` для таких сегментів — `NaN` за **будь-якої** політики: Eq.4/5/6
мають speed-член і калібровані лише на 20–100 км/год, тому політика дає мітку,
а не число.

Інших параметрів немає: `--config`, `--dx`, `--gravity_cutoff`, `--npeop`,
`--rf_threshold` тощо **не існують**. Решта параметрів пайплайну — константи у
`road_quality_analyzer/cli.py`, і кожен прогін друкує їхні фактичні значення
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
  --input data\sensor_data_20250729_163334.csv `
  --out out\run1
```

**Example 2: обгортка з автовизначенням останнього CSV**
```powershell
python main.py
```

**Example 3: обгортка з іменованою текою результатів**
```powershell
python main.py --input data\sensor_data_20250729_163334.csv --out results\official_run
```

**Example 4: позначити низькошвидкісні ділянки як «дуже погані»**
```powershell
python -m road_quality_analyzer analyze `
  --input data\sensor_data_20250729_163334.csv `
  --out out\run_very_poor `
  --low-speed-policy very-poor
```
Рядки лишаються в усіх артефактах, у колонці `low_speed_class` стоїть
`very_poor`, `iri_multi` — порожній (NaN).

**Example 5: прибрати низькошвидкісні ділянки з карти й таблиць**
```powershell
python -m road_quality_analyzer analyze `
  --input data\sensor_data_20250729_163334.csv `
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
FileNotFoundError: [Errno 2] No such file or directory: 'data/sensor_data.csv'
```

**Cause:** відносний шлях, але поточна директорія — не корінь проєкту

**Solution:**
```powershell
# Option A: Use absolute path
python main.py --input "<full_path_to_data>\sensor_data_20250729_163334.csv" --out out\run1

# Option B: Change directory first (recommended)
cd <workspace_root>
python main.py --input "data\sensor_data_20250729_163334.csv" --out out\run1
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
  --input data\sensor_data_20250729_163334.csv `
  --out results\official_run_2025_07_29
```

**Structure:**
```
results/
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
data/
└── sensor_data_20250729_163334.csv
```

**Characteristics** (перевірено на файлі):
- Route: Urban mixed-traffic
- Rows: 188596 — 93399 `Accelerometer`, 93398 `Gyroscope`, 1799 `Location`
- Duration: ~30 хв (1799 с)
- Sampling: 52.6 Hz (accel, median dt = 19 мс), 1 Hz (GPS)
- Distance у вікні аналізу: 15123.7 м, 152 сегменти (2 `partial`)
- Файл записаний до контракту v2 → без `#`-преамбули (читається так само)

Синтетичні CSV для тестів генерує `tests/conftest.py::write_drive_csv`.

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
   `road_quality_analyzer/metrics/iri.py`

### Support

**Issues/Questions:** Create GitHub issue або contact project maintainer

---

**Наступні кроки:**
- Run analysis: `python main.py --input <path> --out <dir>`
- Explore results у `results/` directory
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
