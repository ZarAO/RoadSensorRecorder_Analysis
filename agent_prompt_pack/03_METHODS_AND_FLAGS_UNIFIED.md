# 03 — METHODS, MODES & FLAGS (UNIFIED)

Цей файл описує “що саме агент має реалізувати” у вигляді режимів, конфігів та CLI.

---

## 1) CLI (новий рекомендований)
Додай модульний CLI:

```bash
python -m road_quality_analyzer analyze --input data/sensor_data_*.csv --out out/run_001 --config configs/default.yaml
```

Вихід:
- `out/.../segments.csv`
- `out/.../roughness.geojson`
- `out/.../events.geojson`
- `out/.../segments_map.html`
- `out/.../plots/*.png`
- `out/.../report.md`

## 2) Конфіг (YAML) — повний schema
> Все, що стосується книги (Eq.*, Table 3, threshold) — описано в `02_...`.

```yaml
pipeline:
  segment_length_m: 100              # як у книзі
  distance_grid_step_m: 0.25         # для distance-domain ресемплінгу
  stop_speed_mps: 0.5                # нижче — stop-and-go
  min_valid_ratio: 0.7               # мін частка валідних семплів у сегменті

orientation:
  enabled: true
  gravity_lp_cutoff_hz: 0.35         # low-pass для g_hat
  gravity_lp_order: 4
  use_gyro: false                    # опціонально (можна додати fusion, але не обовʼязково)
  heading_from_gps: true
  heading_min_speed_mps: 1.0         # нижче — heading undefined
  output_world_axes: true

filters:
  bandpass_enabled: true
  bandpass_low_hz: 0.5
  bandpass_high_hz: 6.0
  bandpass_order: 4

psd:
  enabled: true
  welch_nperseg: 256
  welch_noverlap: 128
  f_low_hz: 0.5
  f_high_hz: 6.0
  distress_remove_enabled: true
  distress_window_s: 0.75            # ±w секунд навколо distress

iri:
  mode: "both"                       # psd_linear | multi_linear | both
  psd_linear:
    A: 0.774
    B: -0.825
  multi_linear:
    vehicle_type: "GENERIC"          # LEV | DSD | GENERIC
    speed_source: "segment_mean_kmh" # або gps_instant_kmh
    Npeop: 1
    Stif: 1.0
    DampF: 1.0
    TyreS: 1.0
    wheel_size_in: 17                # метадані (не використовується у формулах книги)

sampling_compliance:
  enabled: true
  max_dx_m: 0.30                     # 300 мм з книги
  recommended_fs_low: 80
  recommended_fs_high: 120

anomaly:
  enabled: true
  mode: "threshold_10ms2"            # threshold_10ms2 | rf | mad_peaks
  threshold_10ms2:
    threshold_mps2: 10.0             # з книги
  rf:
    enabled: false                   # вмикати лише якщо є дані/мітки
    moving_avg_window_s: 0.5
    features:
      - a_vertical_mps2
      - a_perp_mps2
      - speed_mps
  mad_peaks:
    zscore_like_threshold: 3.5
    min_peak_distance_m: 5.0

reporting:
  map_tile: "OpenStreetMap"
  plot_enabled: true
  write_intermediate_parquet: false
```

## 3) Vehicle classification — що реально є в книзі
Книга містить лише:
- `vehicle_type`: **LEV** (large European van) або **DSD** (D-class sedan) і “без типу” (Eq.6),
- фактори: `Npeop`, `Stif`, `DampF`, `TyreS`.

Тому агент має:
- реалізувати enum `VehicleType = {LEV, DSD, GENERIC}`,
- застосовувати Eq.4/5/6 відповідно,
- приймати wheel size як метадані (для майбутнього), але **не використовувати** у формулах.

## 4) Додатково: legacy compatibility
`python main.py` має продовжити працювати. Можна:
- залишити існуючі модулі,
- але нову логіку винести в `road_quality_analyzer/` і підключити з legacy.
