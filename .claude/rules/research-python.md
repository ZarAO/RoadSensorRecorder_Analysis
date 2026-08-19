---
paths:
  - "**/*.py"
---

# Research Python rules (path-scoped)

Loaded whenever a `.py` file is in play. Terse invariants only — depth lives in the
research-toolkit skills (`research-accelerometer-iri-pipeline`, `research-signal-processing`,
`research-geospatial-mapping`, `research-satellite-screening`, `scientific-figure`,
`academic-writing`). Install ONLY in a research / dissertation project.

## Integrity (overriding)
- Never fabricate, interpolate, or invent data points, results, or citations to fill a
  figure or table. If data is missing or ambiguous, say so and stop.
- Don't substitute a linear counter (`s = 0.1*i`) for missing GPS distance; equal 100 m
  bins don't guarantee equal sample density without real distance. No GPS = fail loud.

## Units & sign conventions
- Hold the unit contract: `Grms` in g, `speed` in km/h, PSD in g²/Hz, anomaly thresholds
  in m/s². Mixing units (g vs m/s², km/h vs m/s) shifts results by an order of magnitude.
- Compute `Grms` / `sqrt(bandpower)` ONLY after orientation correction + gravity removal
  in the world-frame vertical; body-frame RMS is inflated ~5–6× by residual gravity.

## Signal processing
- Resample to a uniform time grid BEFORE any Welch PSD or IIR filter — they assume a
  constant `fs`. Derive `fs` from `dt = median(diff(t))` (median, not mean — robust to
  dropped-packet gaps).
- Never `ffill`/`bfill` across sensor types; split by `Type` first, clean each stream alone.
- Trim the first/last ~1 s (e.g. `[100:-100]`) before computing any metric — `filtfilt`
  transients and edge extrapolation make the ends unreliable.
- Compute Welch PSD / `IRI_psd` only when `n >= fs*2`; otherwise store `NaN`, never a
  fabricated value.
- Clip a negative `IRI_psd` to 0 for use but keep the raw value — a negative reading is a
  calibration signal, not a perfect road.
- Never retune published IRI equation coefficients to fit a dataset.

## Spatial / segmentation
- Segment by distance: `seg_id = floor(s/100)`, never by time — time segments have
  speed-dependent spatial length.
- Always compute and report `dx = v/fs` and the fraction where `dx <= 0.3 m`; never
  silently assume spatial-sampling validity.
- Convert lat/lon to radians BEFORE any trig. Use `atan2(sqrt(a), sqrt(1-a))` (not `asin`)
  for haversine cumulative distance; equirectangular/ENU with `cos(lat0)` for local heading.
- Smooth (~1 s moving average) BEFORE differentiating GPS for speed/heading — numeric
  gradient amplifies noise. Mask heading to `NaN` below `v = 1 m/s` (GPS spins 360° when
  stationary).

## Geo / satellite output
- GeoJSON coordinate order is `[lon, lat]`, never `(lat, lon)` — a swap drops geometry into
  the ocean. Serialize a missing metric as `null`, never `NaN` (strict parsers reject
  invalid JSON).
- Divide Sentinel-2 SR pixels by 10000 (DN → reflectance) before thresholds/visuals. Apply
  the cloud mask BEFORE the temporal median composite, never after.

## Reproducibility
- Pin the data path, units, and random seed at the top of a script; keep data loading
  separate from analysis. Iterate segments by `np.unique(seg_id)` and sort each stream by
  time so two runs on the same CSV produce byte-identical output.
- Vectorize with NumPy; avoid Python-level loops over large arrays.

## Figures
- Use matplotlib + SciencePlots for paper/thesis figures: vector export (PDF/SVG), legible
  fonts, axes labelled with units. Don't hand-tune a one-off plot when a `scientific-figure`
  archetype fits.
