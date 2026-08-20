# Profilometer Validation & Eq.3 Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate smartphone roughness metrics against certified profilometer IRI on М-03/Т1016 and fit the first device-specific Eq.3 coefficients (`UA_2026_TRANSIT_S948B`), per the study spec.

**Architecture:** A self-contained, deterministic study pipeline in `studies/profilometer_validation/` (pure, unit-tested `match.py` + `calibrate.py`, orchestrated by `run_study.py`), reading analyzer outputs from `storage/results/field_*` and derived form CSVs from `storage/field_measurements/derived/`. One minimal analyzer change: optional `--iri-psd-A/--iri-psd-B` CLI flags (defaults = book values, pinned). Deliverables: stats JSON + figures + `docs/10_profilometer_validation.md` + dissertation `.docx`.

**Tech Stack:** Python 3.14 (numpy/pandas/scipy/matplotlib/scienceplots in .venv), python-docx (install), pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-profilometer-validation-design.md`

## Global Constraints

- Branch `v1-1-stage`; no co-author trailers; no hidden characters in ANY generated file (incl. the .docx — scan before handoff).
- `IRI_PSD_COEFFICIENTS` in `iri.py` stays byte-identical (test-pinned); fitted values only as new named set + CLI flags.
- Never fabricate a number or citation; failed gates are reported as failures.
- Determinism: same inputs → identical outputs (fixed seeds; stable sorts; no wall-clock in results — study date passed explicitly).
- Reference IRI = mean(ch1..ch8); ch9/ch10 dropped (byte-duplicates of ch8).
- Match tolerance 60 m primary; 40/80 m sensitivity. Exclude partial, needs_class12_survey, out-of-span.
- All prose deliverables UA; code/comments EN.

---

### Task 1: Geo-matching module (`match.py`)

**Files:**
- Create: `studies/profilometer_validation/__init__.py`, `studies/profilometer_validation/match.py`
- Test: `studies/profilometer_validation/tests/test_match.py` (+ `tests/__init__.py`, `pytest.ini` at study root with `pythonpath = ../..`? — no: run pytest from repo root with `python -m pytest studies/profilometer_validation/tests`; add `conftest.py` inserting the study dir into `sys.path`)

**Interfaces:**
- Produces:
  - `load_form_intervals(csv_path) -> pd.DataFrame` — columns `km_start,m_start,km_end,m_end,iri_ref (mean ch1..8), lat_mid, lon_mid, chainage_m` (chainage = km*1000+m midpoint; iri_ref from `iri_ch1..iri_ch8` only).
  - `segment_midpoints(segments_df, gps_track_df) -> pd.DataFrame` — for each full non-survey segment, midpoint lat/lon interpolated from the recording's GPS track at mid-chainage `s_mid=(s_start+s_end)/2`; consumes `road_segments.csv` + a `time_s,lat,lon,s` track table.
  - `build_gps_track(csv_path) -> pd.DataFrame` — Location rows → `time_s, lat, lon, s` (haversine cumulative), reusing haversine from a local `_geo.py` helper (NOT importing analyzer internals — study stays decoupled).
  - `match_segments(seg_mid_df, intervals_df, tolerance_m=60.0) -> pd.DataFrame` — one-to-one nearest matching within tolerance; columns include `match_dist_m`.
- Haversine radius 6371000 m (same as analyzer, keeps distances comparable).

- [ ] **Step 1: Failing tests** — synthetic geometry: a straight north road, intervals every 100 m; a fake segments table + GPS track; assertions:
  - iri_ref = mean of ch1..8 (ch9/10 present but ignored);
  - midpoint interpolation lands between GPS fixes;
  - nearest-match one-to-one: two segments competing for one interval → nearer wins, other unmatched;
  - tolerance excludes far segments; partial/survey segments dropped;
  - determinism: shuffled input rows → identical matched output (stable sort by segment id).
- [ ] **Step 2:** Run, verify fail. **Step 3:** Implement. **Step 4:** Green. **Step 5:** Commit `feat(study): geo-matching of smartphone segments to profilometer intervals`.

### Task 2: Statistics & calibration module (`calibrate.py`)

**Files:**
- Create: `studies/profilometer_validation/calibrate.py`
- Test: `studies/profilometer_validation/tests/test_calibrate.py`

**Interfaces:**
- Produces:
  - `validation_stats(pairs_df, metric_col, ref_col='iri_ref') -> dict` — n, spearman_rho+p, pearson_r+p, mae, bias (mean err), rmse.
  - `bland_altman(pairs_df, metric_col, ref_col) -> dict` — bias, loa_low, loa_high, sd.
  - `fit_eq3(pairs_df) -> dict` — OLS A,B (+stderr), theil_sen A,B, r2, mae, rmse, n; input col `sqrt_psd`, target `iri_ref`.
  - `loro(pairs_df, fit_fn) -> dict` — per held-out road: r2, mae, rmse of the fit trained on the other road.
  - `fit_grms_speed(pairs_df) -> dict` — OLS `iri_ref ~ a*grms + b*v_kmh + c`, same reporting (P0.2-lite).
  - All pure; scipy.stats + numpy only.

- [ ] **Step 1: Failing tests** — synthetic pairs with known slope/intercept + noise (seeded rng): fit recovers A,B within tolerance; r2 near expected; LORO on two synthetic "roads" returns both directions; Bland–Altman on constant offset returns that bias; validation_stats on monotone data → spearman 1.0.
- [ ] **Steps 2-4:** fail → implement → green. **Step 5:** Commit `feat(study): validation statistics and Eq.3 calibration fits`.

### Task 3: Analyzer CLI flags for calibrated coefficients

**Files:**
- Modify: `analyzer/src/road_quality_analyzer/cli.py` (argparse + analyze() params + report Configuration section), `analyzer/src/road_quality_analyzer/metrics/iri.py` (`compute_iri_psd(..., A=None, B=None)` optional overrides defaulting to book constants), `analyzer/src/road_quality_analyzer/segmentation/segment_100m.py` (thread the override through `create_segments_dataframe`/`aggregate_segment_metrics`)
- Test: `analyzer/tests/test_iri.py` or new cases in `test_cli.py`

**Interfaces:**
- `analyze(input_path, output_dir, low_speed_policy=..., iri_psd_A=None, iri_psd_B=None)`; CLI `--iri-psd-A/--iri-psd-B` (floats, default None → book).
- Report prints `IRI_psd coefficients: book (A=0.774, B=-0.825)` or `custom set (A=..., B=...)`.

- [ ] **Step 1: Failing tests** — (a) pin: `IRI_PSD_COEFFICIENTS == {'A_sqrt_psd': 0.774, 'B_const': -0.825}`; (b) `compute_iri_psd(x, A=2, B=0)` uses overrides; (c) analyze() with overrides writes different `iri_psd_raw` and prints the custom set in report; default run byte-identical to before (compare `road_segments.csv` of a fixture drive with/without flags absent).
- [ ] **Steps 2-4.** **Step 5:** Full analyzer suite green (177+new). Commit `feat(analyzer): optional calibrated Eq.3 coefficients via CLI flags, book values untouched`.

### Task 4: Study orchestrator (`run_study.py`) + figures

**Files:**
- Create: `studies/profilometer_validation/run_study.py`, `studies/profilometer_validation/figures.py`, `studies/profilometer_validation/README.md`

**Interfaces:**
- `python studies/profilometer_validation/run_study.py --out studies/profilometer_validation/out` — inputs hardcoded to the two calibration pairs (М-03: `field_new_sensor_data_20260820_100807` + `derived/М-03_км19-км30смуга2_100.csv`; Т1016: `field_new_sensor_data_20260820_102552` + `derived/Т1016_км17-км0+200зворотній_100.csv`) with the source recordings for GPS tracks; study date passed via `--study-date 2026-08-20`.
- Outputs to `out/`: `matched_pairs.csv`, `stats.json` (validation per road+pooled, fits, LORO, sensitivity at 40/60/80 m, gates verdict), `figures/*.pdf+png` (scatter+fit, Bland–Altman before/after, chainage overlay per road), `study_report.md` (UA summary tables).
- Figures per scientific-figure skill: scienceplots style, labeled axes with units, vector PDF + PNG.

- [ ] **Step 1:** Implement (no TDD for glue; underlying logic is tested) — but assert invariants inline: n_pairs > 50 per road expected (М-03 ~100+, Т1016 ~160), gates evaluated explicitly.
- [ ] **Step 2:** Run; inspect `stats.json`; sanity-check numbers (spearman sign, plausible A>0).
- [ ] **Step 3:** Determinism check: run twice → `matched_pairs.csv` and `stats.json` byte-identical.
- [ ] **Step 4:** Commit `feat(study): end-to-end validation/calibration study with figures and report`.

### Task 5: Adversarial verification (workflow)

- [ ] Independent recomputation: agents re-derive key numbers from `matched_pairs.csv` with independent code paths (numpy.polyfit vs scipy) + critique matching (duplicate assignments? out-of-span leakage? tolerance sensitivity consistent?) + verify every number quoted in `study_report.md` traces to `stats.json`. Fix findings; re-run.

### Task 6: Docs + dissertation docx

**Files:**
- Create: `docs/10_profilometer_validation.md`; `C:\DEV\my_project\University\Dissertation\Валідація_смартфон_vs_профілометр.docx`
- Modify: `docs/00_index.md` (link), `docs/07_future_work_roadmap.md` (P0.1 status)

- [ ] **Step 1:** `docs/10` (UA): методика (geo-matching, D1, tolerance), результати (таблиці зі stats.json), обмеження (§8 спеки), як відтворити (`run_study.py`).
- [ ] **Step 2:** docx via python-docx (office-export skill; install python-docx): structure П.1 постановка, П.2 дані (обидві таблиці інвентаря), П.3 методика, П.4 результати (таблиці + вставлені PNG фігури), П.5 обмеження, П.6 висновки. Ukrainian, no fabricated citations: Eq.3 → ADB guidebook; форма — за назвою документа.
- [ ] **Step 3:** Hidden-character scan over all new files incl. docx XML parts.
- [ ] **Step 4:** Full regression: analyzer suite + backend suite + study tests green.
- [ ] **Step 5:** Commit `docs+study: profilometer validation results, dissertation draft chapter`.
