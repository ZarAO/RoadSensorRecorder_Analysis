# 03 — Methods, Quality Flags, Traffic & Low-Speed Rules (UNIFIED)

## Key design principle
Real roads include jams, stoplights, and “unmotorable” sections. Speed can be < 20 km/h.
Therefore:
- do not crash or refuse,
- separate roughness interpretation from defect detection,
- compute in distance-domain for segment statistics.

---

## 1) Two quality layers (independent)

### Layer A — Sampling compliance (geometric)
Compute:
- `fs_acc_hz` (F4)
- `dx_m = v_mps * dt` (F5)
- `v_max_kmh` per class (F6)

Flags:
- `sampling_noncompliant` if dx exceeds chosen class limit (default: Class III dx≤0.30 m).

### Layer B — Dynamics validity (physical)
Mark roughness-invalid intervals when:
- speed < `min_roughness_kmh`
- strong turns (gyro magnitude proxy above threshold)
- hard accel/brake (prefer forward axis if configured; else speed derivative proxy)
- unstable speed (high variance window)

Outputs:
- per-sample `valid_for_roughness`
- per-segment `valid_ratio`
- per-run warning if valid_ratio is low globally.

---

## 2) Motion states + jams (required)

### State machine
Using smoothed GPS speed:
- STOP: v < stop_kmh for >= T_stop (implement default 5–10 s if not configurable)
- SLOW: stop_kmh ≤ v < slow_kmh
- MOVING: v ≥ slow_kmh

Export:
- `traffic_events.csv` with start/end time, duration, mean speed, representative lat/lon.

### Jam heuristic (simple)
Jam if:
- prolonged SLOW, OR
- frequent STOP transitions with low mean speed.

---

## 3) Orientation + gravity compensation (required for continuity)

### Orientation mapping
Use config `axis_mapping` + `axis_sign` to compute:
- `a_vert_raw` (vertical component)
- `a_forward_raw`, `a_lateral_raw` where possible

### Gravity compensation (optional but enabled by default)
If `gravity.enabled`:
- estimate gravity vector by moving average window `gravity.window_s`
- linear acceleration vector: `a_lin = a - g_est`
- choose vertical signal for roughness:
  - if `metrics.rmsa.use_linear_accel`: use `a_vert_lin`
  - else: use `a_vert_raw`

Always report whether gravity compensation was enabled.

---

## 4) Filtering rules (required)
Apply Butterworth band-pass 0.5–6 Hz to the chosen vertical signal (raw or linear).
Use zero-phase filtering (`filtfilt`).
Keep pre/post signals in debug mode.

---

## 5) Roughness metrics (required)
### RMSA
- window RMSA over time (config window_s)
- per-segment RMSA using distance-domain samples

### RMSA_3D (continuity metric)
Also compute RMSA_3D (R1) to keep comparability with your existing results.

### PSD features
Compute Welch PSD and PSD scalar in [0.5, 6] Hz band.

### IRI-like estimate modes
- `psd_linear`: IRI = A*√PSD + B (explicitly report as estimate/proxy)
- `multi_linear`: demo regression mode with constants in config
- `quarter_car`: scaffold only (optional)

Confidence rules:
- if segment is mostly STOP or valid_ratio too low:
  - set `roughness_status = "insufficient_motion"` or `"low_confidence"`
  - keep metrics but mark them.

---

## 6) Defect detection (required)
Use MAD-based peak detection on filtered vertical signal.
Constraints:
- enforce minimum separation by **distance** (`min_distance_m`)
- cluster nearby peaks into one event
- exclude strong turns

Export:
- `events.geojson` as Point features: timestamp, severity, segment_id.

---

## 7) Distance-domain segmentation (required)
Stop-and-go breaks time-window statistics; fix by distance-domain:

1) cumulative distance s(t) (F3)
2) resample signals to uniform distance grid (F18)
3) compute segment metrics per 100m bin (F19)

Per-segment required fields:
- id, start/end distance, representative lat/lon
- mean_speed_kmh, stop_ratio, valid_ratio
- rmsa, rmsa_3d, psd_scalar, optional iri_est
- peak_count, max_peak_severity
- flags: sampling_noncompliant, mounting_risk, low_speed_validity_risk

---

## 8) Reporting requirements (report.md)
Must include:
- total time + total distance
- fs estimates (accel, gyro, gps)
- sampling compliance summary (dx stats, v_max by class)
- STOP/SLOW/MOVING share
- warnings list (mounting risk, low validity, noncompliant sampling)
- top N worst segments by roughness (with ids)

---

## 9) AI track (only after deterministic pipeline)
Build dataset of 100m segments:
- features: rmsa, rmsa_3d, psd_scalar(s), speed stats, stop_ratio, turn_ratio, peak_density
- labels: proxy (quantiles) or manual annotation CSV
Models:
- baseline classification + anomaly detection
Export predicted map layer.

