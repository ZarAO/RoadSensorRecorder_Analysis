# 04 — Acceptance Checklist (UNIFIED) + Runbook

## A) Canonical one-command run (must work)
```bash
python -m road_quality_analyzer analyze --input sensor_data_20250729_163334.csv --config configs/default.yaml --out out/run_001
```

### Expected canonical outputs in `out/run_001/`
- `segments.csv`
- `events.geojson`
- `roughness.geojson`
- `traffic_events.csv`
- `segments_map.html`
- `plots/` (at least: speed.png, rmsa.png, peaks.png)
- `report.md`

---

## B) Legacy compatibility (must keep working)
`python main.py` must still run.
Acceptable behaviors:
1) It calls the canonical CLI internally and prints the out directory, OR
2) It produces the canonical artifacts in a timestamped `results/results_<timestamp>/` directory.

If `output.legacy_export.enabled=true`, then `main.py` should produce:
- a `results/results_<timestamp>/` folder
- containing at least equivalents/aliases of canonical outputs.

---

## C) Minimum quality gates

### 1) Correctness
- Mixed-stream CSV ingestion works (Accelerometer/Gyroscope/Location).
- GPS speed handles dt=0 and missing GPS rows.
- Stop/slow detection detects obvious stops in the sample.
- Distance segmentation count ≈ total_distance/100.

### 2) Determinism
- Same input/config → same canonical outputs.

### 3) Documentation
- `docs/baseline.md`
- `docs/formulas.md` (LaTeX formulas + units + code mapping)
- `docs/methodology.md` (pipeline + flags + low-speed handling)

### 4) Tests
- `pytest` passes.
- Coverage across:
  - geo, sampling, gravity, filters, metrics, traffic, masks, peaks, distance segmentation.

### 5) Style & CI
- `ruff` clean
- GitHub Actions: lint + tests

---

## D) “Done” definition
✅ canonical analyze runs end-to-end  
✅ canonical outputs exist  
✅ tests pass + CI green  
✅ docs consistent with code  
✅ stop-and-go handled with flags (no crashes)  
✅ segments include stop_ratio & valid_ratio and confidence status  
✅ main.py still works (legacy compatibility)

