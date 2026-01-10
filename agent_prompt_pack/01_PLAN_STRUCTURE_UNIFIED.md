# 01 — Plan & Architecture (UNIFIED, primary execution guide)

## Goal
Refactor and extend the current repository into a robust, reproducible, testable pipeline that:
- works on real stop-and-go roads (20 km/h may be impossible),
- produces segment-level roughness indices + defect candidates,
- generates maps/plots/reports deterministically,
- stays compatible with the existing `v-ghc-1` runner (`main.py` + `modules/`).

---

## Strategy: “evolution, not rewrite”
You must NOT break current usage. Do it in 3 layers:

### Layer 1 — Baseline (today’s code)
- Run `python main.py` on the provided sample CSV.
- Record behavior, outputs, and issues in `docs/baseline.md`.

### Layer 2 — Canonical package + CLI (new)
- Create package `road_quality_analyzer/` with CLI `analyze`.
- Implement deterministic output contract into `out/<run_id>/`.

### Layer 3 — Compatibility wrapper (keep old entry point)
- Update `main.py` to be a thin wrapper:
  - parse args (or keep default “latest CSV” logic),
  - call `road_quality_analyzer` pipeline,
  - optionally write legacy `results/results_<timestamp>/` artifacts if enabled.

---

## Target architecture (adapt to repo, keep responsibilities)
```
road_quality_analyzer/
  __init__.py
  cli.py
  config.py

  io/
    reader.py

  preprocessing/
    sync.py
    gps.py
    traffic.py
    orientation.py
    gravity.py          # NEW: gravity estimation / linear acceleration
    filters.py
    quality.py

  segmentation/
    by_distance.py

  metrics/
    rmsa.py             # includes RMSA_3D
    psd.py
    peaks.py
    iri_models.py
    quarter_car.py      # optional scaffold

  viz/
    plots.py
    maps.py

  outputs/
    writers.py
    legacy_export.py    # NEW: optional export into results/results_<timestamp> format

modules/               # existing; can be kept or gradually migrated
main.py                # must keep working (wrapper)
tests/
configs/
docs/
```

---

## Canonical CLI (must implement)
Command:
```bash
python -m road_quality_analyzer analyze --input <csv> --config <yaml> --out <dir>
```

### Required artifacts in `--out`
- `segments.csv`
- `events.geojson`
- `roughness.geojson`
- `traffic_events.csv`
- `segments_map.html`
- `plots/*.png`
- `report.md`

---

## Configuration (YAML) — must implement
Create `configs/default.yaml` with these keys (keys must exist; values tunable):

```yaml
input:
  timezone: "Europe/Kyiv"

mounting:
  mode: "unknown"            # rigid|handheld|unknown
  phone_orientation: "unknown"
  axis_mapping:
    vertical: "Z"            # X|Y|Z
    forward: "Y"
    lateral: "X"
  axis_sign:
    X: 1
    Y: 1
    Z: 1

gravity:
  enabled: true
  window_s: 2.0              # moving average window for gravity estimate
  mode: "moving_average"     # moving_average|lowpass

speed:
  stop_kmh: 2
  slow_kmh: 10
  min_roughness_kmh: 5
  smoothing_window_s: 5
  hard_brake_mps2: 2.0
  hard_accel_mps2: 2.0

sampling:
  expected_fs_hz: 100
  class_limits:
    class1_dx_m: 0.025
    class2_dx_m: 0.150
    class3_dx_m: 0.300

filters:
  bandpass_hz: [0.5, 6.0]
  order: 4

segmentation:
  length_m: 100
  distance_resample_step_m: 0.2

metrics:
  rmsa:
    enabled: true
    window_s: 1.0
    use_linear_accel: true       # use gravity-compensated accel if enabled
    also_compute_rmsa_3d: true   # keep existing v-ghc-1 metric
  psd:
    enabled: true
    welch:
      nperseg: 1024
      noverlap: 512
    band_hz: [0.5, 6.0]
    scalar: "band_power_sqrt"    # band_power_sqrt|mean_sqrt|median_sqrt
  iri:
    mode: "psd_linear"           # none|psd_linear|multi_linear|quarter_car
    psd_linear:
      A: 0.774
      B: -0.825
    multi_linear:
      Grms_coeff: 55.25
      Speed_coeff: -0.07
      Npeople_coeff: 0.19
      Stif_coeff: -2.93
      DampF_coeff: -1.09
      TyreS_coeff: -1.44
      Intercept: 7.66
      defaults:
        Npeople: 1
        Stif: 0
        DampF: 0
        TyreS: 0

events:
  peak:
    method: "mad"
    threshold: 6.0
    min_distance_m: 2.0

output:
  make_plots: true
  make_map: true
  export_geojson: true
  legacy_export:
    enabled: true
    root_dir: "results"
```

---

## Step-by-step execution plan (commit after each milestone)

### Step 0 — Baseline reproduction
- Run `python main.py` (as-is) on the sample CSV.
- Capture:
  - command used,
  - produced files,
  - known issues,
  in `docs/baseline.md`.

### Step 1 — Canonical CLI skeleton
- Add `road_quality_analyzer/cli.py` with `analyze` command.
- Add config loader `config.py`.
- Add `configs/default.yaml`.

### Step 2 — Robust mixed-stream CSV ingestion
- Implement `io/reader.py` to produce `SensorStreams`:
  - accel: t, ax, ay, az
  - gyro: t, gx, gy, gz
  - gps: t, lat, lon
- Handle sorting, duplicates, dt=0, missing blocks.
- Tests: schema + counts + monotonic time.

### Step 3 — Time alignment + GPS speed + distance
- Canonical timebase = accel stream.
- Interpolate GPS to accel timeline.
- Compute speed and cumulative distance.
- Save debug plot: speed vs time.

### Step 4 — Traffic layer: stop/slow/jam
- Implement motion states + jam events.
- Export `traffic_events.csv`.

### Step 5 — Orientation + gravity compensation (keep v-ghc-1 logic)
- Apply axis mapping/sign.
- If `gravity.enabled`:
  - estimate gravity vector (moving average window),
  - compute linear acceleration: `a_lin = a - g_est`.
- Output both:
  - `a_vert_raw`, `a_vert_lin` (vertical component)
  - and optionally `a_lin_3d`.

### Step 6 — Filtering + validity masks
- Band-pass 0.5–6 Hz on chosen vertical signal (raw or linear).
- Build masks:
  - `valid_for_roughness`
  - `valid_for_defects`

### Step 7 — Metrics: RMSA, RMSA_3D, PSD, IRI modes, peaks
- Implement formula map from file 02.
- Keep RMSA_3D as additional metric for continuity.

### Step 8 — Distance-domain resample + 100m segmentation
- Resample signals onto distance grid.
- Compute segment metrics in 100m bins.
- Add segment-level flags: stop_ratio, valid_ratio, sampling_noncompliant, mounting_risk.

### Step 9 — Outputs: CSV/GeoJSON/Map/Report
- Write canonical output contract in `--out`.
- If legacy_export enabled:
  - also write into `results/results_<timestamp>/` using existing naming where applicable.

### Step 10 — Hardening
- Add `pytest` + `ruff`.
- Add GitHub Actions.

---

## Optional AI track
Defined in file 03 + 04, only after deterministic pipeline works.

