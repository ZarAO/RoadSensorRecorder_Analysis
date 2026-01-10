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

# Install dependencies
pip install -r requirements.txt
```

**Requirements (версії фіксовані):**
```
pandas==2.3.2
numpy==2.3.2
scipy==1.16.1
matplotlib==3.10.6
folium==0.20.0
```

### Крок 3: Verify input data

```bash
# Check CSV integrity
md5sum data/sensor_data_20250729_163334.csv
# Expected: <hash> (якщо надано)

# Check structure
head -5 data/sensor_data_20250729_163334.csv
```

**Expected output:**
```csv
Time,Type,X,Y,Z,Latitude,Longitude
1722261414023,ACCEL,0.2345,-0.1234,9.8765,,
1722261414043,ACCEL,0.2401,-0.1198,9.8812,,
1722261414000,GPS,,,,,50.450123,30.523456
```

### Крок 4: Run experiments

**Legacy run:**
```bash
python main.py
# Output: results/results_YYYYMMDD_HHMMSS/
```

**New run:**
```bash
python -m road_quality_analyzer analyze \
  --input data/sensor_data_20250729_163334.csv \
  --out out/comparison/new_run
```

**Comparison:**
```bash
python tools/compare_runs_v2.py
# Output: out/comparison/analysis/
```

---

## Input Dataset

**Файл:** `data/sensor_data_20250729_163334.csv`

### Характеристики

| Parameter | Value |
|-----------|-------|
| **Filename** | sensor_data_20250729_163334.csv |
| **Size** | ~15 MB |
| **Date recorded** | 2025-07-29 (літо, суха погода) |
| **Distance** | 15.14 km (15140.7 м) |
| **Duration** | ~30 хвилин |
| **Total rows** | 188596 |
| **ACCEL rows** | 94702 (Type=='ACCEL') |
| **GPS rows** | 1799 (Type=='GPS') |
| **Accelerometer fs** | ~52.6 Hz (median dt) |
| **GPS fs** | ~1 Hz |
| **Route type** | Міські вулиці + заміська траса |
| **Vehicle** | Легковий автомобіль (sedan) |
| **Phone model** | [Unknown, можна додати] |
| **Mounting** | Dashboard holder |

### CSV Structure

```csv
Time,Type,X,Y,Z,Latitude,Longitude
1722261414023,ACCEL,0.2345,-0.1234,9.8765,,    ← Accelerometer (X,Y,Z in m/s²)
1722261414043,ACCEL,0.2401,-0.1198,9.8812,,
1722261414062,ACCEL,0.2456,-0.1162,9.8858,,
1722261414000,GPS,,,,,50.450123,30.523456      ← GPS (Lat,Lon in degrees)
1722261415000,GPS,,,,,50.450234,30.523567
```

**Колонки:**
- **Time:** Unix timestamp (мілісекунди)
- **Type:** `ACCEL` або `GPS`
- **X, Y, Z:** Accelerometer (м/с²) або пусті для GPS
- **Latitude, Longitude:** GPS coordinates (градуси) або пусті для ACCEL

### Pre-processing requirements

**Для нового пайплайну:**
- ✅ Separates ACCEL/GPS streams
- ✅ Drops NaN в X,Y,Z для ACCEL
- ✅ Drops NaN в Latitude,Longitude для GPS
- ✅ NO ffill/bfill
- ✅ Time conversion: ms → seconds

**Для legacy:**
- ⚠️ Uses ffill/bfill (non-causal)
- ⚠️ Mixed streams до розділення

---

## Команди для запуску

### Legacy Pipeline

**Main script:** `main.py`

```bash
python main.py
```

**Outputs (default location):** `results/results_YYYYMMDD_HHMMSS/`

**Files created:**
- `road_segments.csv` — 1799 time-based segments
- `road_quality_map.html` — Folium interactive map
- `grms_plot.png` — RMSA vs time
- `rmsa_plot.png` — RMSA distribution
- `peaks_plot.png` — Detected peaks overlay
- `time_series_plot.png` — Accelerometer raw data
- `debug.log` — Processing log

**Runtime:** ~15 секунд

### New Pipeline

**Main command:** `python -m road_quality_analyzer analyze`

```bash
python -m road_quality_analyzer analyze \
  --input data/sensor_data_20250729_163334.csv \
  --out out/comparison/new_run \
  --segment-length 100 \
  --threshold-anomaly 10.0 \
  --filter-low 0.5 \
  --filter-high 6.0 \
  --npeop 1 \
  --stif 1.0 \
  --damp-f 1.0 \
  --tyre-s 1.0
```

**Параметри (всі опціональні):**
- `--segment-length 100` — довжина сегмента (м)
- `--threshold-anomaly 10.0` — threshold для anomalies (м/с²)
- `--filter-low 0.5` — band-pass low cutoff (Hz)
- `--filter-high 6.0` — band-pass high cutoff (Hz)
- `--npeop 1` — кількість людей у авто (Eq.4-6)
- `--stif 1.0` — stiffness factor (0.8-1.2)
- `--damp-f 1.0` — damping factor (0.8-1.2)
- `--tyre-s 1.0` — tyre size factor (0.7-1.0)

**Outputs:** `out/comparison/new_run/`

**Files created:**
- `road_segments.csv` — 153 distance-based 100m segments
- `roughness.geojson` — GeoJSON LineStrings (для QGIS/Kepler.gl)
- `roughness_map.html` — Folium map з color-coded segments
- `plot_grms_profile.png` — Grms vs distance
- `plot_iri_profile.png` — IRI_multi vs distance
- `plot_speed_profile.png` — Speed vs distance
- `plot_psd_heatmap.png` — PSD spectrogram
- `report.md` — текстовий звіт з acceptance criteria

**Runtime:** ~25 секунд

### Comparison Script

**Script:** `tools/compare_runs_v2.py`

```bash
python tools/compare_runs_v2.py \
  --legacy out/comparison/legacy_run \
  --new out/comparison/new_run \
  --input data/sensor_data_20250729_163334.csv \
  --out out/comparison/analysis
```

**Outputs:** `out/comparison/analysis/`

**Artifacts:**
- **Tables (4 CSV):**
  - `tables/table_metrics_overall.csv` — overall metrics
  - `tables/table_metrics_per_100m.csv` — 152 overlap segments
  - `tables/table_top10_worst_segments.csv` — worst 10 by IRI
  - `tables/table_rank_correlation.csv` — Spearman correlations

- **Plots (4 PNG):**
  - `plots/plot_speed_profile.png` — швидкість vs відстань
  - `plots/plot_grms_vs_rmsa.png` — scatter (ρ = 0.942)
  - `plots/plot_iri_multi_vs_legacy_proxy.png` — scatter (ρ = 0.783)
  - `plots/plot_top10_segments_bar.png` — bar chart

- **GeoJSON (2 files):**
  - `geojson/new_roughness_100m.geojson` — 153 LineStrings
  - `geojson/legacy_proxy_roughness_100m.geojson` — 152 Points

- **Summary (updated):**
  - `comparison_summary.md` — 3100+ words, auto-updated з реальними числами

**Runtime:** ~30 секунд

---

## Outputs та артефакти

### Legacy Run Directory Structure

```
results/results_20260110_182841/
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
out/comparison/new_run/
├── road_segments.csv           (153 rows, 9 columns)
├── roughness.geojson           (153 features, LineString)
├── roughness_map.html          (Folium map, ~800 KB)
├── plot_grms_profile.png       (150 DPI, 12x4 inches)
├── plot_iri_profile.png
├── plot_speed_profile.png
├── plot_psd_heatmap.png
└── report.md                   (acceptance criteria check)
```

**road_segments.csv columns:**
```
seg_id, s_start, s_end, iri_multi, iri_psd, grms, mean_speed_kmh, valid_ratio, anomaly_count
```

### Comparison Analysis Directory

```
out/comparison/analysis/
├── tables/
│   ├── table_metrics_overall.csv           (1 row × 17 columns)
│   ├── table_metrics_per_100m.csv          (153 rows × 10 columns)
│   ├── table_top10_worst_segments.csv      (10 rows)
│   └── table_rank_correlation.csv          (3 rows)
├── plots/
│   ├── plot_speed_profile.png              (150 DPI)
│   ├── plot_grms_vs_rmsa.png               (ρ = 0.942)
│   ├── plot_iri_multi_vs_legacy_proxy.png  (ρ = 0.783)
│   └── plot_top10_segments_bar.png
├── geojson/
│   ├── new_roughness_100m.geojson          (153 features)
│   └── legacy_proxy_roughness_100m.geojson (152 features)
└── comparison_summary.md                    (3100+ words)
```

---

## Фіксація версій

### Software Environment

```yaml
OS: Windows 11 (або Linux, macOS)
Python: 3.13.5
Virtual environment: .venv/

Dependencies:
  pandas: 2.3.2
  numpy: 2.3.2
  scipy: 1.16.1
  matplotlib: 3.10.6
  folium: 0.20.0
  pytest: 9.0.2
```

### Repository State

```
Repository: ZarAO/RoadSensorRecorder_Analysis
Branch: main
Commit: <commit hash from 2025-01-10>
Date: 2025-01-10

Key files:
- road_quality_analyzer/ (8 modules)
- modules/ (4 modules, legacy)
- tests/ (22 unit tests)
- tools/compare_runs_v2.py (500 lines)
- agent_prompt_pack/02_FORMULAS_TEST_MAP_UNIFIED.md
```

**Як отримати commit hash:**
```bash
git rev-parse HEAD
```

### Configuration Snapshot

**New pipeline (defaults в коді):**
```python
# preprocessing.py
fs_hz: auto-detect (median dt)

# orientation.py
f_cutoff_gravity: 0.25 Hz
butterworth_order: 4

# filtering.py
f_low: 0.5 Hz
f_high: 6.0 Hz
filter_order: 4

# analysis.py
threshold_anomaly: 10.0 m/s²
iri_psd_A: 0.774  (Eq.3)
iri_psd_B: 0.825
iri_multi: Eq.6 (generic vehicle)
npeop: 1
stif: 1.0
damp_f: 1.0
tyre_s: 1.0

# segmentation.py
segment_length_m: 100.0

# PSD (Welch)
nperseg: min(256, len/4)
window: 'hann'
scaling: 'density'
f_band: [0.5, 6.0] Hz
```

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

**Обов'язкові колонки:**
```
Time, Type, X, Y, Z, Latitude, Longitude
```

**Формат:**
- **Time:** Unix timestamp (мілісекунди)
- **Type:** `ACCEL` або `GPS` (case-sensitive)
- **X, Y, Z:** Float (м/с²) для ACCEL, пусті/NaN для GPS
- **Latitude, Longitude:** Float (градуси) для GPS, пусті/NaN для ACCEL

**Приклад запису:**
```csv
Time,Type,X,Y,Z,Latitude,Longitude
1722261414023,ACCEL,0.234,-0.123,9.876,,
1722261414000,GPS,,,,,50.450,30.523
```

### Крок 1: Підготовка CSV

```bash
# Перевірити структуру
head -10 your_data.csv

# Перевірити Type values
cut -d',' -f2 your_data.csv | sort | uniq
# Має бути: Type, ACCEL, GPS

# Підрахувати rows
wc -l your_data.csv
```

### Крок 2: Run new pipeline

```bash
python -m road_quality_analyzer analyze \
  --input your_data.csv \
  --out out/your_analysis
```

**Очікувані попередження:**
- Якщо fs < 50 Hz → warning про sampling compliance
- Якщо GPS gaps > 10 sec → warning про distance errors
- Якщо IRI_psd < 0 → info про calibration mismatch

### Крок 3: Inspect outputs

```bash
# Перевірити road_segments.csv
head -5 out/your_analysis/road_segments.csv

# Відкрити карту
open out/your_analysis/roughness_map.html  # Linux/Mac
# або: start out/your_analysis/roughness_map.html  # Windows

# Читати звіт
cat out/your_analysis/report.md
```

### Крок 4: Compare з legacy (опціонально)

```bash
# Run legacy
python main.py  # manually edit input path in main.py

# Run comparison
python tools/compare_runs_v2.py \
  --input your_data.csv \
  --legacy results/results_YYYYMMDD_HHMMSS \
  --new out/your_analysis \
  --out out/your_comparison
```

---

## Determinism Checklist

### Фіксовані параметри

- [x] **Random seed:** `np.random.seed(42)` (якщо є stochastic operations)
- [x] **Filter parameters:** f_low=0.5, f_high=6.0, order=4 (фіксовані)
- [x] **Threshold:** 10.0 m/s² (константа)
- [x] **IRI coefficients:** Eq.3 (A=0.774, B=0.825), Eq.6 (фіксовані)
- [x] **Segmentation:** 100 м (конфігурований, але default фіксований)
- [x] **PSD parameters:** nperseg, window='hann' (детерміністичні)

### Reproducible operations

- [x] **Haversine distance:** pure math (no randomness)
- [x] **Quaternion rotation:** deterministic linear algebra
- [x] **Welch PSD:** deterministic FFT
- [x] **Savgol filter:** deterministic polynomial fit
- [x] **Linear interpolation:** deterministic (np.interp)
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
4. ✅ 22 unit tests (validation)
5. ✅ Documented input format
6. ✅ Exact commands для запуску

**Для наукової публікації вказати:**
- Repository + commit hash
- Python 3.13.5
- OS (Windows/Linux/macOS)
- Dependencies versions (pandas 2.3.2, numpy 2.3.2, scipy 1.16.1)
- Input CSV checksum (MD5/SHA256)
- Configuration snapshot (якщо змінювали defaults)

**Наступні розділи:**
- [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md) — числові результати
- [06_threats_to_validity_and_limitations.md](06_threats_to_validity_and_limitations.md) — обмеження
