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
python main.py analyze --input "data\sensor_data_20250729_163334.csv"
```

**Output:**
```
results/results_<timestamp>/
├── road_segments.csv       (IRI metrics per 100m)
├── gps_track.html         (GPS route map)
└── segments_map.html      (IRI heatmap)
```

**Typical runtime:** 15-30 sec (для dataset ~95k rows)

---

## Installation

### Prerequisites

- **Python:** 3.11+ (tested on 3.13.5)
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
folium>=0.20.0
```

**Verification:**
```powershell
python -c "import numpy, pandas, scipy, folium; print('OK')"
# Expected: OK
```

---

## Main Analysis Pipeline

### Command Structure

```powershell
python main.py analyze [OPTIONS]
```

### Required Arguments

**`--input <path>`** — Path to sensor data CSV

**Format requirements:**
```csv
timestamp,accel_x,accel_y,accel_z,latitude,longitude,speed,accuracy
1722271999500,0.123,-0.456,9.789,50.4501,30.5234,12.5,5.0
...
```

**Columns (9 total):**
- `timestamp` (ms): Unix epoch milliseconds
- `accel_x/y/z` (m/s²): 3-axis accelerometer (body frame)
- `latitude/longitude` (degrees): GPS coordinates (WGS84)
- `speed` (m/s): GPS speed
- `accuracy` (m): GPS horizontal accuracy

---

## CLI Reference

### `analyze` Command

**Full syntax:**
```powershell
python main.py analyze `
  --input <csv_path> `
  [--output <dir>] `
  [--dx 100.0] `
  [--gravity_cutoff 0.25] `
  [--anomaly_abs 10.0] `
  [--min_speed 1.0] `
  [--npeop 1] `
  [--stif 1.0] `
  [--damp_f 1.0] `
  [--tyre_s 1.0] `
  [--rf_threshold 0.63]
```

### Optional Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--output` | `results/results_<timestamp>` | Вихідна директорія |
| `--dx` | `100.0` | Segment length (m) |
| `--gravity_cutoff` | `0.25` | Low-pass cutoff for gravity (Hz) |
| `--anomaly_abs` | `10.0` | Absolute anomaly threshold (m/s²) |
| `--min_speed` | `1.0` | Min speed for valid heading (m/s) |
| `--npeop` | `1` | Number of people (vehicle load) |
| `--stif` | `1.0` | Suspension stiffness factor (0.8-1.2) |
| `--damp_f` | `1.0` | Front damping factor (0.8-1.2) |
| `--tyre_s` | `1.0` | Tire stiffness factor (0.8-1.2) |
| `--rf_threshold` | `0.63` | RF probability threshold (anomaly detection) |

### Examples

**Example 1: Default analysis**
```powershell
python main.py analyze --input data\sensor_data_20250729_163334.csv
```

**Example 2: Custom segment length (200m)**
```powershell
python main.py analyze `
  --input data\sensor_data_20250729_163334.csv `
  --dx 200.0
```

**Example 3: Vehicle with passenger (npeop=2)**
```powershell
python main.py analyze `
  --input data\sensor_data_20250729_163334.csv `
  --npeop 2
```

**Example 4: Softer suspension (stif=0.8)**
```powershell
python main.py analyze `
  --input data\sensor_data_20250729_163334.csv `
  --stif 0.8 `
  --damp_f 1.1
```

---

## Outputs Description

### Structure

```
results/results_<timestamp>/
├── road_segments.csv
├── gps_track.html
└── segments_map.html
```

### File 1: `road_segments.csv`

**Purpose:** IRI metrics per distance segment

**Format:**
```csv
segment_id,distance_start_m,distance_end_m,lat_mean,lon_mean,speed_median_mps,grms,iri_psd,iri_multi,num_anomalies,valid_gps_ratio
0,0.0,100.0,50.4501,30.5234,11.2,0.0543,2.145,3.456,0,0.95
1,100.0,200.0,50.4512,30.5245,12.5,0.0621,2.678,4.123,1,0.98
...
```

**Columns (11 total):**

| Column | Unit | Description |
|--------|------|-------------|
| `segment_id` | — | Sequential ID (0, 1, 2, ...) |
| `distance_start_m` | m | Segment start (cumulative) |
| `distance_end_m` | m | Segment end (cumulative) |
| `lat_mean` | degrees | Mean latitude |
| `lon_mean` | degrees | Mean longitude |
| `speed_median_mps` | m/s | Median speed |
| `grms` | g | Gravity-corrected RMS accel (Eq.B5) |
| `iri_psd` | m/km | IRI from PSD (Eq.3) |
| `iri_multi` | m/km | IRI multivariable (Eq.6) |
| `num_anomalies` | — | Detected anomalies (RF classifier) |
| `valid_gps_ratio` | — | GPS coverage (0-1) |

**Usage:**
```python
import pandas as pd

df = pd.read_csv('results/results_20250830/road_segments.csv')

# Top 10 roughest segments
top10 = df.nlargest(10, 'iri_multi')
print(top10[['segment_id', 'distance_start_m', 'iri_multi']])

# Average IRI
mean_iri = df['iri_multi'].mean()
print(f'Mean IRI: {mean_iri:.2f} m/km')
```

---

### File 2: `gps_track.html`

**Purpose:** Interactive GPS route map

**Technology:** Folium (Leaflet.js)

**Features:**
- **Basemap:** OpenStreetMap
- **Route polyline:** Blue line (entire track)
- **Markers:** Start (green), End (red)
- **Popups:** Click → distance, speed

**How to use:**
```powershell
# Open у браузері
start results\results_<timestamp>\gps_track.html
```

**Screenshot example:**
```
[Map view]
├── Start marker (green): "Start: 0.0 m"
├── Route polyline (blue)
└── End marker (red): "End: 15140.7 m, Avg speed: 41.7 km/h"
```

---

### File 3: `segments_map.html`

**Purpose:** IRI heatmap per segment

**Features:**
- **Color-coded segments:**
  - 🟢 Green: IRI < 2.5 m/km (good)
  - 🟡 Yellow: 2.5 ≤ IRI < 4.0 (fair)
  - 🟠 Orange: 4.0 ≤ IRI < 6.0 (poor)
  - 🔴 Red: IRI ≥ 6.0 (very poor)

- **Popups (click segment):**
  ```
  Segment 42
  Distance: 4200-4300 m
  IRI: 5.23 m/km
  Grms: 0.0712 g
  Speed: 35.2 km/h
  Anomalies: 2
  ```

**How to use:**
```powershell
start results\results_<timestamp>\segments_map.html
```

---

## Troubleshooting

### Error 1: `FileNotFoundError: [Errno 2] No such file`

**Symptom:**
```
FileNotFoundError: [Errno 2] No such file or directory: 'data/sensor_data.csv'
```

**Cause:** Relative path, но working directory не workspace root

**Solution:**
```powershell
# Option A: Use absolute path
python main.py analyze --input "<full_path_to_data>\sensor_data_20250729_163334.csv"

# Option B: Change directory first (recommended)
cd <workspace_root>
python main.py analyze --input "data\sensor_data_20250729_163334.csv"
```

---

### Error 2: `ValueError: Invalid CSV format`

**Symptom:**
```
ValueError: Expected columns: ['timestamp', 'accel_x', ...], got: ['time', 'ax', ...]
```

**Cause:** CSV headers не співпадають з required format

**Solution:**
Check CSV headers (line 1):
```csv
timestamp,accel_x,accel_y,accel_z,latitude,longitude,speed,accuracy
```

If renamed, update `modules/io_utils.py`:
```python
# Line 15-20 (приклад)
REQUIRED_COLUMNS = ['time', 'ax', 'ay', 'az', 'lat', 'lon', 'v', 'acc']
df = df.rename(columns={
    'time': 'timestamp',
    'ax': 'accel_x',
    ...
})
```

---

### Error 3: `ImportError: No module named 'folium'`

**Symptom:**
```
ImportError: No module named 'folium'
```

**Cause:** Virtual environment не активовано або dependencies не встановлені

**Solution:**
```powershell
# 1. Activate venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify
python -c "import folium; print(folium.__version__)"
# Expected: 0.20.0
```

---

### Error 4: `RuntimeWarning: invalid value encountered in sqrt`

**Symptom:**
```
RuntimeWarning: invalid value encountered in sqrt
IRI_psd = -0.123 (negative)
```

**Cause:** PSD може бути від'ємним через noise → sqrt(PSD) = NaN → IRI_psd negative

**Expected:** See [06_threats](06_threats_to_validity_and_limitations.md#calibration-mismatch) (Eq.3 calibration issue)

**Solution:**
- **Short-term:** Ignore negative IRI_psd (use IRI_multi as primary)
- **Long-term:** Recalibrate Eq.3 (see [07_roadmap P0.1](07_future_work_roadmap.md#p01--recalibrate-eq3-iri_psd-coefficients))

---

### Error 5: `ZeroDivisionError: division by zero`

**Symptom:**
```
ZeroDivisionError: division by zero (у speed_median calculation)
```

**Cause:** Segment з 0 GPS points (all masked) → no speed data

**Solution:**
Check `valid_gps_ratio` у `road_segments.csv`:
```python
df = pd.read_csv('road_segments.csv')
bad_segments = df[df['valid_gps_ratio'] < 0.5]
print(f'Found {len(bad_segments)} segments з low GPS coverage')

# Filter out
df_clean = df[df['valid_gps_ratio'] >= 0.8]
```

---

## FAQ

### Q1: Чому IRI_psd = 0.0 у багатьох сегментах?

**A:** Two cases:

1. **PSD дуже малий (smooth road):**
   ```
   sqrt(PSD) < B/A = 0.825/0.774 = 1.065
   → IRI_psd = 0.774*sqrt(PSD) - 0.825 < 0
   → Clamped to 0 (physical constraint)
   ```

2. **Distress removal aggressive:**
   - Anomaly detected → ±1 sec window removed
   - If many anomalies → little data left → PSD=0

**Solution:** Use **IRI_multi** (Eq.6) as primary metric (more robust).

---

### Q2: Чому num_anomalies = 0 у всіх сегментах?

**A:** RF classifier very conservative (threshold=0.63 default)

**Possible causes:**
1. **Road справді smooth:** No potholes/bumps detected
2. **RF needs recalibration:** See [07_roadmap P0.3](07_future_work_roadmap.md#p03--validate-rf-anomaly-detection)

**Debug:**
```powershell
# Lower threshold to test
python main.py analyze `
  --input data\sensor_data_20250729_163334.csv `
  --rf_threshold 0.5  # More sensitive
```

If anomalies appear → threshold was too high. If still 0 → road may be smooth.

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

**Our dataset:**
- Mean IRI_multi = 3.78 m/km → **GOOD** (borderline FAIR)
- Max IRI_multi = 8.12 m/km → **POOR**

---

### Q4: Чому Grms і IRI_multi не ідеально корелюють?

**A:** IRI_multi (Eq.6) включає additional factors:

```
IRI_multi = 50.32*Grms - 0.06*Speed + 0.17*Npeop - 1.86*Stif - 0.90*DampF - 0.78*TyreS + 6.68
```

**Speed effect:**
- High speed → vehicle "floats" → lower perceived roughness
- Coefficient: -0.06 (negative → damping)

**Vehicle params:**
- Soft suspension (low stif) → lower IRI (absorbs bumps)
- Defaults (stif=1.0, ...) → може не відповідати real vehicle

**Conclusion:** Grms ~ IRI (ρ=0.94 strong), але not 1:1 mapping.

---

### Q5: Як зберегти results для конкретної дати?

**A:** Use `--output` flag:

```powershell
python main.py analyze `
  --input data\sensor_data_20250729_163334.csv `
  --output results\official_run_2025_07_29
```

**Structure:**
```
results/
├── official_run_2025_07_29/    ← named output
│   ├── road_segments.csv
│   ├── gps_track.html
│   └── segments_map.html
├── results_20260110_013358/    ← auto-generated timestamp
│   └── ...
```

---

### Q6: Чи можна запустити на real-time data (Android app)?

**A:** **Currently: NO** (post-processing only)

**Future work:** See [07_roadmap P2.3](07_future_work_roadmap.md#p23--real-time-mobile-app)

**Workaround:** Collect data → transfer CSV → analyze offline (~30 sec latency)

---

### Q7: Як налаштувати для іншого phone/vehicle?

**A:** Two options:

**Option 1: Use defaults** (current approach)
- Assumes generic phone/vehicle
- Good for **relative comparisons** (segment A vs B)
- Absolute IRI може бути biased ±0.5-1.0 m/km

**Option 2: Calibrate parameters** (future work)
- Collect ground truth IRI (profilometer)
- Tune `--stif`, `--damp_f`, `--tyre_s` to minimize error
- See [07_roadmap P0.2](07_future_work_roadmap.md#p02--recalibrate-eq6-iri_multi-coefficients)

---

### Q8: Де знайти sample datasets для testing?

**A:** Included in repo:

```
data/
└── sensor_data_20250729_163334.csv  (15.14 km, 94702 ACCEL, 1799 GPS)
```

**Characteristics:**
- Route: Urban mixed-traffic
- Distance: 15.14 km
- Duration: ~22 min
- Mean speed: 41.7 km/h
- Sampling: 52.6 Hz (ACCEL), 1 Hz (GPS)

**Additional datasets:** See `docs/RESEARCH_RESULTS.md` (може містити links)

---

### Q9: Як експортувати у GeoJSON для QGIS?

**A:** Currently **not implemented** (TODO: [07_roadmap P1 enhancement](07_future_work_roadmap.md))

**Workaround (manual):**
```python
import pandas as pd
import json

df = pd.read_csv('road_segments.csv')

features = []
for idx, row in df.iterrows():
    feature = {
        'type': 'Feature',
        'geometry': {
            'type': 'Point',
            'coordinates': [row['lon_mean'], row['lat_mean']]
        },
        'properties': {
            'segment_id': int(row['segment_id']),
            'iri_multi': float(row['iri_multi']),
            'grms': float(row['grms'])
        }
    }
    features.append(feature)

geojson = {
    'type': 'FeatureCollection',
    'features': features
}

with open('segments.geojson', 'w') as f:
    json.dump(geojson, f, indent=2)
```

**Usage у QGIS:**
```
Layer → Add Layer → Add Vector Layer → segments.geojson
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
3. **Formulas:** `agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md`

### Support

**Issues/Questions:** Create GitHub issue або contact project maintainer

---

**Наступні кроки:**
- Run analysis: `python main.py analyze --input <path>`
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
