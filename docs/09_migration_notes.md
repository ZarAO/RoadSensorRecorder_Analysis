# 09 — Migration Notes (Legacy → New Pipeline)

## Зміст
1. [What Changed](#what-changed)
2. [Why Migration](#why-migration)
3. [Before vs After](#before-vs-after)
4. [How to Use New Pipeline](#how-to-use-new-pipeline)
5. [Reproducing STAGE 1–2](#reproducing-stage-1-2)
6. [Legacy Access](#legacy-access)

---

## What Changed

### Removed (January 2026, STAGE 4 Cleanup)

**Code:**
- `modules/` directory (legacy analysis, preprocessing, visualization, io_utils)
- `main.py` legacy mode (no more `--use-new-pipeline` flag)
- `tools/compare_runs.py`, `tools/quick_compare.py` (old comparison scripts)

**Behavior:**
- `python main.py` now **always** runs new pipeline (no legacy option)
- Default pipeline: `road_quality_analyzer` (world-frame, distance-based, IRI metrics)

**Archived:**
- Legacy code moved to `archive/legacy_snapshot/` (for historical reference only)
- Not imported, not executed, not maintained

---

### Added/Updated

**New default:**
- `main.py` — thin wrapper → `python -m road_quality_analyzer analyze`
- Auto-detects latest CSV if `--input` not specified
- Auto-generates `results/results_<timestamp>` if `--out` not specified

**Preserved:**
- `road_quality_analyzer/` package (new pipeline)
- `tools/compare_runs_v2.py` (for STAGE 2 artifacts, if needed)
- `tests/` (22 unit tests, all PASS)
- `docs/` (8 documentation files from STAGE 3)
- Sample dataset: `data/sensor_data_20250729_163334.csv`

---

## Why Migration

### Legacy Pipeline Limitations

**Problem 1: Gravity Contamination (5.6x)**
```python
# Legacy (body-frame)
rmsa = sqrt(ax² + ay² + az²)
→ az contains gravity (~9.8 m/s²) + road vibrations
→ RMSA = 0.334 m/s² (inflated)

# New (world-frame)
grms = RMS(a_vertical) after quaternion rotation
→ gravity aligned to vertical, removed from horizontal
→ Grms = 0.059 g = 0.058 m/s² (true road vibrations)

Factor: 0.334 / 0.058 = 5.76x
```

**Problem 2: Time-Based Segmentation**
```python
# Legacy: segments based on time
→ 1799 segments (variable distance per segment)
→ Cannot compare different speeds fairly

# New: segments based on distance
→ 153 segments × 100m (uniform spatial bins)
→ IRI directly comparable across routes
```

**Problem 3: No IRI Estimation**
```python
# Legacy: only RMSA (proxy metric)
→ No international standard compliance
→ Cannot compare with reference datasets

# New: IRI (International Roughness Index)
→ Eq.3 (PSD-based), Eq.6 (multivariable)
→ World Bank classification (0-2 excellent, 2-4 good, ...)
```

### Validation Preserved

**Despite fundamental differences, correlation strong:**
- Spearman ρ = 0.783 (IRI_multi vs legacy RMSA)
- Spearman ρ = 0.942 (Grms vs legacy RMSA)
- 152/153 segments overlap (99.3%)

**Conclusion:** New pipeline captures same roughness ranking, but with:
- Better absolute accuracy (gravity-corrected)
- Distance-domain consistency (100m bins)
- IRI compliance (international standard)

---

## Before vs After

### CLI Commands

**Before (STAGE 1–3):**
```powershell
# Legacy mode (default)
python main.py

# New pipeline (opt-in)
python main.py --use-new-pipeline

# Direct analyzer call
python -m road_quality_analyzer analyze --input data/sensor_data.csv --out results/
```

**After (STAGE 4+):**
```powershell
# Default (always new pipeline)
python main.py

# With explicit input/output
python main.py --input data/sensor_data_20250729.csv --out results/my_run

# Direct analyzer call (unchanged)
python -m road_quality_analyzer analyze --input data/sensor_data.csv --out results/
```

---

### Output Structure

**Legacy outputs:**
```
results/results_<timestamp>/
├── accel_z.png              (z-axis acceleration plot)
├── gyro_y.png               (gyroscope plot)
├── rmsa.png                 (RMSA time series)
├── peaks.png                (detected peaks)
├── gps_track.html           (GPS route map)
└── road_segments.csv        (time-based segments, RMSA)
```

**New pipeline outputs:**
```
results/results_<timestamp>/
├── road_segments.csv        (distance-based, IRI metrics)
├── gps_track.html           (GPS route map)
└── segments_map.html        (IRI heatmap)
```

**Key differences:**
- No individual plots (accel_z, gyro_y, rmsa, peaks) — фокус на GPS maps + CSV metrics
- `road_segments.csv` має IRI columns (iri_psd, iri_multi, grms, num_anomalies)
- `segments_map.html` color-coded by IRI (green/yellow/orange/red)

---

### Metrics Mapping

| Legacy Metric | New Equivalent | Notes |
|---------------|----------------|-------|
| RMSA (m/s²) | Grms (g) | 5.6x lower (gravity removed) |
| Peaks count | num_anomalies | RF classifier (fewer false positives) |
| Time segments | Distance segments | 100m bins (spatial consistency) |
| N/A | IRI_psd (m/km) | PSD-based IRI (Eq.3) |
| N/A | IRI_multi (m/km) | Multivariable IRI (Eq.6) |

**Conversion (approximate):**
```
IRI_multi ≈ 50.32 * Grms - 0.06 * Speed + ... (Eq.6)

For typical values:
Grms = 0.06 g, Speed = 40 km/h
→ IRI_multi ≈ 3.8 m/km (GOOD classification)
```

---

## How to Use New Pipeline

### Quick Start

```powershell
# Activate environment
.venv\Scripts\Activate.ps1

# Run analysis (auto-detect latest CSV)
python main.py

# Or specify input
python main.py --input data/sensor_data_20250729_163334.csv
```

**Output:** `results/results_<timestamp>/`

### Full CLI Options

```powershell
python -m road_quality_analyzer analyze `
  --input data/sensor_data_20250729_163334.csv `
  --out results/my_analysis `
  --dx 100.0 `
  --gravity_cutoff 0.25 `
  --anomaly_abs 10.0 `
  --min_speed 1.0 `
  --npeop 1 `
  --stif 1.0 `
  --damp_f 1.0 `
  --tyre_s 1.0
```

**See:** [08_user_guide_and_cli_reference.md](08_user_guide_and_cli_reference.md) for details

---

## Reproducing STAGE 1–2

### STAGE 1: Inventory (Legacy vs New)

**Without legacy code (archived):**

1. **Run new pipeline only:**
   ```powershell
   python main.py --input data/sensor_data_20250729_163334.csv --out results/new_only
   ```

2. **Check outputs:**
   ```
   results/new_only/
   ├── road_segments.csv   (153 segments, 100m each)
   ├── gps_track.html
   └── segments_map.html
   ```

3. **Extract metrics:**
   ```python
   import pandas as pd
   
   df = pd.read_csv('results/new_only/road_segments.csv')
   print(f"Mean IRI: {df['iri_multi'].mean():.2f} m/km")
   print(f"Mean Grms: {df['grms'].mean():.4f} g")
   ```

**Expected (from STAGE 1 comparison):**
- Distance: 15140.7 m
- Segments: 153
- Mean IRI_multi: 3.78 m/km
- Mean Grms: 0.0590 g

---

### STAGE 2: Comparison (Legacy vs New)

**Using archived artifacts:**

STAGE 2 comparison results already saved in:
```
out/comparison/analysis/
├── tables/
│   ├── table_metrics_overall.csv     (summary: distance, segments, mean metrics)
│   └── table_rank_correlation.csv    (Spearman ρ, p-values, n=152)
├── plots/
│   ├── scatter_iri_multi_vs_legacy_rmsa.png
│   ├── scatter_grms_vs_legacy_rmsa.png
│   ├── speed_profile_100m.png
│   └── bar_top10_segments.png
└── geojson/
    └── segments_100m_aligned.geojson
```

**To re-run comparison (requires legacy snapshot):**

```powershell
# 1. Temporarily restore legacy modules to sys.path
$env:PYTHONPATH = "archive\legacy_snapshot"

# 2. Run comparison script
python tools/compare_runs_v2.py `
  --legacy results/legacy_run/road_segments.csv `
  --new results/new_run/road_segments.csv `
  --input data/sensor_data_20250729_163334.csv `
  --out out/comparison_rerun
```

**Note:** Legacy run (`results/legacy_run/`) може бути відсутній → використовуй збережені STAGE 2 artifacts.

---

### Alternative: Trust STAGE 2 Artifacts

**If legacy unavailable:**
1. Use existing `out/comparison/analysis/` artifacts (already validated)
2. Cite validation numbers from [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md):
   - ρ = 0.783 (IRI vs RMSA)
   - ρ = 0.942 (Grms vs RMSA)
   - 152 overlap segments

3. Focus on new pipeline only (absolute IRI values, not relative to legacy)

---

## Legacy Access

### If You Need Legacy Code

**Location:** `archive/legacy_snapshot/`

**Structure:**
```
archive/legacy_snapshot/
├── README.md              (usage instructions)
├── modules/
│   ├── analysis.py
│   ├── preprocessing.py
│   ├── visualization.py
│   └── io_utils.py
├── compare_runs.py        (old comparison)
└── quick_compare.py
```

**How to use:**
```python
import sys
sys.path.insert(0, 'archive/legacy_snapshot')

from modules.io_utils import load_data
from modules.preprocessing import preprocess_data
from modules.analysis import compute_rmsa

df = load_data('data/sensor_data_20250729_163334.csv')
df = preprocess_data(df)
rmsa = compute_rmsa(df, df['accel_x_cal'], df['accel_y_cal'], df['accel_z_cal'])

print(f"Legacy RMSA mean: {rmsa.mean():.4f} m/s²")
# Expected: ~0.334 m/s²
```

**WARNING:**
- Not maintained
- Not tested (no unit tests for legacy)
- Use only for historical validation or research

---

## Troubleshooting

### Error: `ModuleNotFoundError: No module named 'modules'`

**Cause:** Legacy code removed from runtime

**Solution:**
```python
# If you need legacy, add archive to path
import sys
sys.path.insert(0, 'archive/legacy_snapshot')
```

### Error: `main.py --use-new-pipeline` not recognized

**Cause:** Flag removed in STAGE 4

**Solution:**
```powershell
# Old command (no longer works)
python main.py --use-new-pipeline

# New command (always new pipeline)
python main.py
```

### Q: How to get legacy plots (accel_z.png, rmsa.png)?

**A:** Legacy plots не генеруються new pipeline. Alternatives:

**Option 1:** Use archived legacy code (see above)

**Option 2:** Create custom plots from new outputs:
```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('results/new_run/road_segments.csv')

plt.figure(figsize=(12, 4))
plt.plot(df['distance_start_m'], df['grms'], label='Grms (g)')
plt.xlabel('Distance (m)')
plt.ylabel('Grms (g)')
plt.title('Road Roughness Profile')
plt.legend()
plt.savefig('grms_profile.png')
```

---

## Summary

**Key changes:**
- ✅ Legacy code archived → `archive/legacy_snapshot/`
- ✅ `main.py` simplified → always new pipeline
- ✅ One command: `python main.py` (no flags needed)
- ✅ Tests PASS (22/22)
- ✅ Documentation updated (00-08 + this 09)

**Migration complete:** Repository now has single, consistent pipeline (`road_quality_analyzer`).

**Next steps:**
- Use `python main.py` for all new analyses
- Refer to [08_user_guide](08_user_guide_and_cli_reference.md) for CLI options
- Cite STAGE 2 validation (ρ = 0.783) in publications

---

**Previous sections:**
- [00 — Index](00_index.md) — navigation
- [08 — User Guide](08_user_guide_and_cli_reference.md) — CLI reference

**Related:**
- [05 — Results](05_results_legacy_vs_new.md) — validation numbers
- [06 — Threats](06_threats_to_validity_and_limitations.md) — limitations
