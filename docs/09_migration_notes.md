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
- Not imported, not executed, not maintained
- **Станом на зараз** каталогу `archive/legacy_snapshot/` у робочому дереві немає;
  єдина копія legacy-коду — каталог `modules/` в історії git (видалений у комміті
  `83b6a7f`); як його дістати — див. [Legacy Access](#legacy-access)

---

### Added/Updated

**New default:**
- `main.py` — thin wrapper → `python -m road_quality_analyzer analyze`
- Auto-detects latest CSV if `--input` not specified
- Auto-generates `results/results_<timestamp>` if `--out` not specified

**Preserved:**
- `road_quality_analyzer/` package (new pipeline)
- `tests/` (163 unit tests у 11 файлах, all PASS)
- `docs/` (документація STAGE 3, файли 00-09)
- Sample dataset: `data/sensor_data_20250729_163334.csv`

`tools/compare_runs_v2.py` не збережений — його теж видалено.

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
→ 152 segments × 100 m (uniform spatial bins, 2 partial)
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
├── road_segments.csv        (distance-based, 24 колонки з IRI метриками)
├── roughness.geojson        (LineString на сегмент)
├── events.geojson           (Point на кожну аномалію)
├── segments_map.html        (IRI heatmap)
├── report.md                (configuration + diagnostics)
└── plots/                   (4 графіки, PNG + PDF)
```

**Key differences:**
- Інший набір графіків: `speed_vs_distance`, `accel_vs_distance`,
  `metrics_vs_distance`, `iri_psd_vs_distance` (PNG + PDF)
- `road_segments.csv` має IRI columns (`iri_psd_raw`, `iri_psd`, `iri_multi`,
  `grms`, `anomaly_count`, `events_per_km`) та прапорці якості (`partial`,
  `speed_valid`, `dx_le_03_share`, `low_speed_class`, `needs_class12_survey`)
- `segments_map.html` color-coded by IRI_multi (зелений/синій/помаранчевий/червоний,
  шкала відносна в межах запису); сегменти < 20 км/год — пурпурові `#FF00FF`
  поза цією шкалою, з легендою «Потребує обстеження профілометром (клас 1/2)»
- `analyze` дістав необов'язкову опцію `--low-speed-policy`
  (`very-poor|poor|invalid|ignore`, за замовчуванням `invalid`); у legacy
  аналога не було

---

### Metrics Mapping

| Legacy Metric | New Equivalent | Notes |
|---------------|----------------|-------|
| RMSA (m/s²) | Grms (g) | 5.6x lower (gravity removed) |
| Peaks count | anomaly_count | абсолютний поріг \|a_vertical\| > 10 м/с² (не ML) |
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
  --out results/my_analysis
```

Інших прапорців немає: `--dx`, `--gravity_cutoff`, `--anomaly_abs`, `--min_speed`,
`--npeop`, `--stif`, `--damp_f`, `--tyre_s`, `--config` **не реалізовані**.
Ці величини — константи в `road_quality_analyzer/cli.py` та
`segmentation/segment_100m.py`; фактичні значення кожного прогону друкуються
у секцію `Configuration` файлу `report.md`.

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
   ├── road_segments.csv   (152 segments, 100 m each; 2 з них partial)
   ├── roughness.geojson
   ├── events.geojson
   ├── segments_map.html
   ├── report.md
   └── plots/
   ```

3. **Extract metrics:**
   ```python
   import pandas as pd
   
   df = pd.read_csv('results/new_only/road_segments.csv')
   full = df[~df['partial']]          # неповні сегменти не входять у середні
   print(f"Mean IRI: {full['iri_multi'].mean():.2f} m/km")
   print(f"Mean Grms: {full['grms'].mean():.4f} g")
   ```

**Expected (поточний пайплайн на `data/sensor_data_20250729_163334.csv`):**
- Distance у вікні аналізу: 15123.7 m
- Segments: 152 (2 partial)
- Mean IRI_multi: 2.99 m/km (лише повні сегменти)
- Mean Grms: 0.0467 g

> Числа STAGE 1 (15140.7 m, 153 сегменти, IRI 3.78, Grms 0.0590) отримані до
> виправлень пайплайну (обрізання країв ±1 с, відкидання семплів поза покриттям
> GPS, прапорці `partial` / `speed_valid`) і більше не відтворюються.

---

### STAGE 2: Comparison (Legacy vs New)

**Using archived artifacts:**

STAGE 2 comparison results створювались у наведеній структурі; у поточному дереві
каталогу `out/comparison/` **немає** (видалений разом із legacy-кодом):
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

**To re-run comparison:** з поточного дерева неможливо — і `tools/compare_runs_v2.py`,
і `archive/legacy_snapshot/` видалені; відновити їх можна лише з історії git.

---

### Alternative: Trust STAGE 2 Artifacts

**If legacy unavailable:**
1. Артефактів `out/comparison/analysis/` у дереві немає; стабільні копії таблиць
   і графіків збережені у `docs/paper_assets/`
2. Cite validation numbers from [05_results_legacy_vs_new.md](05_results_legacy_vs_new.md):
   - ρ = 0.783 (IRI vs RMSA)
   - ρ = 0.942 (Grms vs RMSA)
   - 152 overlap segments

3. Focus on new pipeline only (absolute IRI values, not relative to legacy)

---

## Legacy Access

### If You Need Legacy Code

**Location:** тільки історія git. У робочому дереві немає ні `modules/`, ні
`archive/legacy_snapshot/` — жоден шлях у поточному дереві на legacy-код не веде.

**Що було в `modules/`** (останній комміт із цим каталогом — `83b6a7f^`):
```
modules/
├── analysis.py
├── preprocessing.py
├── visualization.py
└── io_utils.py
```

**Як відновити (лише за потреби, поза робочим деревом):**
```powershell
# знайти комміт, у якому каталог ще існував
git log --oneline --diff-filter=D -- modules

# витягнути знімок у окремий каталог
git worktree add ../legacy_snapshot 83b6a7f^
```

Тільки після такого відновлення legacy-модулі можна імпортувати; без нього будь-який
`import modules...` падає з `ModuleNotFoundError`.

**WARNING:**
- Not maintained
- Not tested (no unit tests for legacy)
- Use only for historical validation or research

---

## Troubleshooting

### Error: `ModuleNotFoundError: No module named 'modules'`

**Cause:** Legacy code removed from runtime

**Solution:** нового пайплайну це не стосується — він `modules` не імпортує. Якщо
помилка виникає у вашому власному скрипті, спершу відновіть знімок із історії git
(див. [Legacy Access](#legacy-access)); у поточному дереві додавати до `sys.path`
нічого.

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

**Option 1:** відновити legacy-код з історії git (див. [Legacy Access](#legacy-access))

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
- ✅ Legacy code видалено з робочого дерева → доступний лише в історії git
- ✅ `main.py` simplified → always new pipeline
- ✅ One command: `python main.py` (no flags needed)
- ✅ Tests PASS (163/163, 11 файлів)
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
