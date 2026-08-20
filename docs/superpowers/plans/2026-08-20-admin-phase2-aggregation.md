# Web Admin Phase 2 — Aggregation, Reference View, Run Compare, Dashboard, Dissertation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Multi-pass aggregated comparisons (repeatability, bias with CI, endogeneity-free speed term), a reference-dataset detail page on the shared map, run-vs-run deltas, dashboard vehicle-type breakdown, the calibration UX fix (phone_model prefill + resolution preview), and the first full draft wave of dissertation chapters.

**Architecture:** Aggregation math is pure functions in the study package (`profilometer_validation/aggregate.py`, tested — dissertation-grade). The backend adds one entity (AggregateComparison) reusing the Phase-3 job/queue/artifact patterns verbatim. Frontend adds a generic MultiLineChart, a `metricKey` input on SegmentMap, two new detail pages, and a shared create-set dialog. Dissertation chapters are Ukrainian .md working files under `University/Dissertation/chapters/` (outside the git repo), compiled from docs/01–10 and the Phase 1–3 record.

**Tech Stack:** unchanged (FastAPI+SQLAlchemy+SQLite; Angular 22 signals; profilometer_validation; matplotlib Agg; no chart libs).

**Spec:** `docs/superpowers/specs/2026-08-20-admin-phase2-aggregation-design.md`

## Global Constraints

- Branch `v1-1-stage`; no `Co-Authored-By`; no hidden/invisible Unicode anywhere (incl. dissertation files); code/commits English, UI copy and dissertation prose Ukrainian.
- Book constants stay in analyzer code; confirmation is always a human decision; analyzer package untouched (181-test contour); analyzer artifacts never mutated.
- Backend rules (`.claude/rules/web-admin-backend.md`) apply: RQA_* env only, metadata-only DB, traversal-guarded artifacts, NaN→null, error-language policy (404/403 EN, 409/422 UA), coefficient resolution only via `resolve_for_meta`, client `params['coefficients']` stripped.
- Frontend rules apply: DTO mirror, ApiService-only HTTP, tokens-only CSS, all maps via `shared/segment-map.ts`, hand-rolled SVG charts only, low-speed IRI invariant (null never numeric).
- Aggregation matching params = Phase-3 defaults `{endpoint_tolerance_m: 60.0, min_rows_in_window: 9, max_window_m: 160.0}`; bin width 100 m.
- Dissertation: no fabricated numbers or citations; numbers only from our artifacts (stats.json, docs/10, report.md); files in `c:\DEV\my_project\University\Dissertation\chapters\` (NOT in this git repo — no commits for them; hidden-char scan still mandatory).
- Test commands: backend `cd web_admin/backend && ../../.venv/Scripts/python.exe -m pytest -q` (64 green now); study `.venv/Scripts/python.exe -m pytest studies/profilometer_validation/tests -q` (26); frontend `cd web_admin/frontend && npx ng test --watch=false` (63) + `npx ng build`; analyzer contour `.venv/Scripts/python.exe -m pytest analyzer/tests -q` (181).
- Commit per task; explicit `git add <path>`.

---

### Task 1: Aggregation math in the study package

**Files:**
- Create: `studies/profilometer_validation/src/profilometer_validation/aggregate.py`
- Test: `studies/profilometer_validation/tests/test_aggregate.py`

**Interfaces:**
- Consumes: `profilometer_validation.calibrate.effective_n` (existing).
- Produces (all pure, DataFrame in → DataFrame/dict out, JSON-serializable dicts):

```python
BIN_WIDTH_M = 100.0

def bin_pairs(pairs: pd.DataFrame, bin_width_m: float = BIN_WIDTH_M) -> pd.DataFrame
    # pairs columns: run_id, chainage_m, iri_multi, iri_ref, mean_speed_kmh (seg_id passthrough ok)
    # returns a copy with 'bin_center' = floor(chainage_m / bin_width_m) * bin_width_m + bin_width_m / 2

def per_bin_stats(binned: pd.DataFrame) -> pd.DataFrame
    # one row per bin_center, sorted ascending:
    # bin_center, iri_ref (mean over rows), mean_iri, std_iri (ddof=1; NaN when n<2),
    # min_iri, max_iri, n_passes (nunique run_id), mean_speed_kmh, diff (= mean_iri - iri_ref)

def repeatability_sd(binned: pd.DataFrame) -> dict
    # pooled within-bin std over bins with >=2 passes:
    # {'sd': sqrt(mean of within-bin variances (ddof=1)), 'n_bins_used': int} ; sd None when no such bin

def bias_with_ci(bins: pd.DataFrame, confidence: float = 0.95) -> dict
    # bias = mean(diff); se = std(diff, ddof=1)/sqrt(n_eff), n_eff via effective_n on
    # chainage-sorted diff; t-quantile at n_eff-1 dof (scipy.stats.t.ppf)
    # {'bias','se','ci_low','ci_high','n_bins','n_eff','confidence'}

def speed_effect(binned: pd.DataFrame, min_speed_spread_kmh: float = 3.0) -> dict | None
    # per-pass mean speeds: binned.groupby('run_id')['mean_speed_kmh'].mean();
    # if their std < min_speed_spread_kmh -> None
    # demeaned FE estimator over rows in bins with >=2 passes:
    #   y = diff_ib - mean_b(diff),  x = speed_ib - mean_b(speed)  (diff_ib = iri_multi_ib - iri_ref_b)
    #   slope = sum(x*y)/sum(x*x); stderr = sqrt(sum((y-slope*x)**2)/(n-1)/sum(x*x))
    # {'slope_iri_per_kmh','stderr','n_rows','n_bins','speed_spread_kmh'}
```

- [ ] **Step 1: Failing tests** (`test_aggregate.py`) — synthetic data with known truth:

```python
import numpy as np
import pandas as pd
import pytest

from profilometer_validation.aggregate import (
    bias_with_ci, bin_pairs, per_bin_stats, repeatability_sd, speed_effect)


def _passes(n_bins=20, passes=3, bias=-1.5, noise=0.0, speed_by_pass=None, seed=1):
    """Synthetic pairs: iri_ref rises linearly; each pass = ref + bias + noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(passes):
        speed = (speed_by_pass or {}).get(p, 60.0)
        for b in range(n_bins):
            chain = b * 100.0 + 37.0          # arbitrary in-bin offset
            ref = 2.0 + 0.1 * b
            rows.append({'run_id': p, 'chainage_m': chain,
                         'iri_ref': ref,
                         'iri_multi': ref + bias + rng.normal(0, noise),
                         'mean_speed_kmh': speed})
    return pd.DataFrame(rows)


def test_bin_pairs_centers():
    binned = bin_pairs(_passes(n_bins=3, passes=1))
    assert sorted(binned['bin_center'].unique()) == [50.0, 150.0, 250.0]


def test_per_bin_stats_exact_no_noise():
    bins = per_bin_stats(bin_pairs(_passes(bias=-1.5, noise=0.0)))
    assert len(bins) == 20
    assert bins['n_passes'].eq(3).all()
    assert bins['diff'].round(9).eq(-1.5).all()
    assert bins['std_iri'].round(9).eq(0.0).all()
    assert bins['min_iri'].le(bins['max_iri']).all()


def test_std_nan_for_single_pass_bin():
    bins = per_bin_stats(bin_pairs(_passes(passes=1)))
    assert bins['n_passes'].eq(1).all()
    assert bins['std_iri'].isna().all()


def test_repeatability_recovers_noise():
    out = repeatability_sd(bin_pairs(_passes(passes=5, noise=0.3, n_bins=200)))
    assert out['n_bins_used'] == 200
    assert out['sd'] == pytest.approx(0.3, rel=0.15)


def test_bias_ci_covers_truth():
    bins = per_bin_stats(bin_pairs(_passes(bias=-1.5, noise=0.2, n_bins=50)))
    out = bias_with_ci(bins)
    assert out['ci_low'] < -1.5 < out['ci_high']
    assert out['n_bins'] == 50 and out['n_eff'] <= 50
    assert out['bias'] == pytest.approx(-1.5, abs=0.15)


def test_speed_effect_recovers_known_slope():
    # inject diff depending on speed: pass speeds 40/60/80, slope -0.05 IRI per km/h
    df = _passes(passes=3, noise=0.05, n_bins=100,
                 speed_by_pass={0: 40.0, 1: 60.0, 2: 80.0})
    df['iri_multi'] = df['iri_multi'] - 0.05 * (df['mean_speed_kmh'] - 60.0)
    out = speed_effect(bin_pairs(df))
    assert out is not None
    assert out['slope_iri_per_kmh'] == pytest.approx(-0.05, abs=0.01)
    assert out['n_bins'] == 100


def test_speed_effect_none_when_constant_speed():
    assert speed_effect(bin_pairs(_passes())) is None
```

- [ ] **Step 2:** Run `.venv/Scripts/python.exe -m pytest studies/profilometer_validation/tests/test_aggregate.py -q` → fails (module missing).
- [ ] **Step 3:** Implement `aggregate.py` per the interface block (module docstring: this is the dissertation's multi-pass methodology — binning on the reference chainage, pooled within-bin repeatability, t-CI with Bartlett effective n, demeaned fixed-effects speed estimator that removes road-roughness confounding).
- [ ] **Step 4:** Full study suite green: 26 + 8 new. Commit `feat(study): multi-pass aggregation math (binning, repeatability, bias CI, FE speed effect)`.

### Task 2: AggregateComparison — model, migration, job, API

**Files:**
- Modify: `web_admin/backend/src/db/models.py`, `web_admin/backend/src/db/session.py` (extend `_ensure_run_columns` → also `coefficient_sets.aggregate_comparison_id`), `web_admin/backend/src/api/schemas.py`, `web_admin/backend/src/main.py`, `web_admin/backend/src/api/runs.py` (delete_run: mark referencing aggregates stale), `web_admin/backend/src/api/coefficient_sets.py` (draft from aggregate)
- Create: `web_admin/backend/src/services/aggregate.py`, `web_admin/backend/src/api/aggregates.py`
- Test: `web_admin/backend/tests/test_aggregates.py`

**Interfaces:**
- `AggregateComparison` (table `aggregate_comparisons`): `id PK, reference_id FK reference_datasets.id, run_ids JSON (list[int]), created_at UTC, status str default 'queued', params JSON default dict, result_dir str|None, summary JSON|None, error str|None`, relationship `reference`.
- `CoefficientSet.aggregate_comparison_id: Mapped[Optional[int]] = mapped_column(ForeignKey('aggregate_comparisons.id'), default=None)` — provenance is EITHER `comparison_id` OR `aggregate_comparison_id`. Migration: `_ensure_run_columns` grows a small table→columns map: `{'analysis_runs': ['eq3_set_id','eq6_bias_set_id'], 'coefficient_sets': ['aggregate_comparison_id']}` (same PRAGMA+ALTER idempotent pattern; test mirrors Task-2-Phase-3's migration test).
- `services/aggregate.py`:

```python
def execute_aggregate(aggregate_id: int, engine, settings) -> None
    # mirrors execute_comparison: queued->running->done/failed, error UA
    # guards: reference exists/not deleted/step==10 (reuse MSG_* constants);
    #   every run exists+done+artifacts; len(run_ids)>=2 («потрібно щонайменше два рани»);
    #   bbox intersect per run (reuse _geojson_bbox + margin)
    # per run: pairs_r = windowed_reference(segment_midpoints_from_geojson(...), form10, **params)
    #   -> pairs_r['run_id']=run.id ; fail when any run yields <5 pairs (name the run in error)
    # concat -> bin_pairs -> per_bin_stats(bins) ; repeatability_sd ; bias_with_ci ; speed_effect
    # rho/mae of aggregated profile: validation_stats over bins renamed
    #   (mean_iri as metric vs iri_ref) — build a small frame {'m': bins.mean_iri, 'iri_ref': bins.iri_ref}
    # artifacts: per_pass_pairs.csv (concat, float %.10g), per_bin.csv, aggregate_stats.json,
    #   chart_data.json, figures/ (fig_agg_profile: MultiLine matplotlib — ref line + mean line +
    #   fill_between(min,max); fig_agg_speed only when speed_effect) — write via a small local
    #   matplotlib block in the service (Agg), NOT new study figures functions
    # result_dir: settings.storage_results_dir / 'aggregates' / f'agg{id}_{stamp}'
    # summary (rounded 4): {'n_runs','n_bins','bias','bias_ci_low','bias_ci_high',
    #   'repeatability_sd','rho','mae_aggregated','speed_slope' (nullable),'stale': False}

def mark_stale_for_run(session, run_id: int) -> None
    # for every AggregateComparison with run_id in run_ids: summary = {**(summary or {}), 'stale': True}
```

- `chart_data.json`: `{'profile': [{'chainage_m': bin_center, 'iri_ref', 'mean_iri', 'lo': min_iri, 'hi': max_iri, 'n_passes', 'std_iri' (null-safe)}], 'bias': {...bias_with_ci...}, 'repeatability': {...}, 'speed_effect': {...}|null, 'validation': {'rho','mae'}}` — all through the existing `_json_safe`.
- Router `prefix='/aggregate-comparisons'`: `POST ''` (`AggregateCreate{reference_id, run_ids: list[int], params: dict = {}}` — fast-fail 404/409 like comparisons incl. «потрібно щонайменше два рани» 422), `GET ''` newest first, `GET '/{id}'`, `DELETE '/{id}'` (rmtree + null `aggregate_comparison_id` on referencing sets via a `detach` loop like `detach_coefficient_sets`), `GET '/{id}/artifacts/{name:path}'` (traversal guard verbatim). `AggregateOut`: model fields + `reference_road: str|None` + `run_filenames: list[str]` (enrichment; empty-safe).
- `delete_run` additionally calls `mark_stale_for_run` BEFORE deleting comparisons.
- `coefficient_sets.py`: `CoefficientSetCreate` gains `aggregate_comparison_id: int|None = None` (exactly one of `comparison_id`/`aggregate_comparison_id` required → 422 otherwise; `comparison_id` becomes `Optional`). Draft from an aggregate: model must be `eq6_bias` (409 for eq3 — no eq3 fit in aggregates), params `{'bias': stats['bias']['bias']}` from `aggregate_stats.json`, `stats_snapshot = {'bias_ci_low','bias_ci_high','n_passes': n_runs,'n_bins','repeatability_sd','rho','mae_aggregated'}`.

- [ ] **Step 1: Failing tests** (`test_aggregates.py`) — reuse conftest helpers; build 3 synthetic "passes" by calling `_make_run_artifacts` into three run rows (same geometry → same road; vary `iri_multi` by +0/-0.1/+0.1 and `mean_speed_kmh` 40/60/80 via a small local variant of the helper — copy `_make_run_artifacts` body into a parametrizable local `_make_pass(result_dir, iri_shift, speed)`), plus `_make_reference`:
  - happy path: POST → done (inline queue); summary has n_runs 3, n_bins ≥ 5, bias ≈ shift mean, `repeatability_sd` > 0, `speed_slope` present (speeds differ); artifacts per_bin.csv/aggregate_stats.json/chart_data.json/figures exist; chart profile rows carry lo ≤ mean_iri ≤ hi.
  - guards: 1 run → 422; run not done → 409; deleted reference → 409 with `MSG_REFERENCE_DELETED`.
  - draft from aggregate: POST /api/coefficient-sets with `aggregate_comparison_id` → 201, params.bias ≈ summary.bias, snapshot keys exact; model 'eq3' → 409; both provenance ids → 422.
  - delete run in run_ids → aggregate summary.stale is True; delete aggregate → referencing set's `aggregate_comparison_id` is null.
  - migration: synthetic old `coefficient_sets` table without the column → init_db adds it (mirror the Phase-3 migration test shape).
- [ ] **Step 2:** Run → fails. Implement model+migration first, then service, then router; wire `main.py`.
- [ ] **Step 3:** Full backend suite green (64 + new). Commit `feat(web-admin): multi-pass aggregate comparisons with repeatability, bias CI and speed effect`.

### Task 3: Reference intervals/geojson API + SegmentMap metricKey

**Files:**
- Modify: `web_admin/backend/src/api/references.py`, `web_admin/backend/src/services/references.py`, `web_admin/frontend/src/app/shared/segment-map.ts` (+its spec)
- Test: `web_admin/backend/tests/test_references_api.py` (extend)

**Interfaces:**
- `GET /api/references/{id}/intervals` → intervals CSV rows as records + computed `iri_ref` (mean ch1..8), NaN→null; 404 unknown; 409 UA «еталон видалено» when source_deleted.
- `GET /api/references/{id}/geojson` → FeatureCollection `{type Feature, properties {interval_id, chainage_m, iri_ref}, geometry LineString [[lon_start,lat_start],[lon_end,lat_end]]}`; built once and cached as `<data_dir>/intervals.geojson` (service fn `build_reference_geojson(settings, ref) -> dict`); chainage_m = midpoint (km*1000+m mean of start/end).
- SegmentMap: new `metricKey = input<'iri_multi' | 'iri_ref'>('iri_multi')`; `segmentColor(props, metricKey='iri_multi')` reads `props[metricKey]` (magenta rule still checks `needs_class12_survey` first — absent on references, harmless). Popup: uses `seg_id` when present else `interval_id` («Інтервал N»), value from metricKey. Legend unchanged (IRI semantics identical).

- [ ] **Step 1: Failing tests:** intervals endpoint returns `intervals_count` rows with finite `iri_ref` and null-safe channels; geojson endpoint returns FC with `intervals_count` features and the cache file exists; 409 after DELETE. Frontend spec: `segmentColor({iri_ref: 7}, 'iri_ref') === '#d81e2c'`, default key unchanged.
- [ ] **Step 2:** Implement; keep `segmentColor(props)` single-arg calls working (default param). Run backend + frontend suites.
- [ ] **Step 3:** Commit `feat(web-admin): reference intervals/geojson endpoints and metric-aware segment map`.

### Task 4: Reference detail page + generic MultiLineChart

**Files:**
- Create: `web_admin/frontend/src/app/shared/charts/multi-line-chart.ts`, `web_admin/frontend/src/app/calibration/reference-detail.ts|html|css|spec.ts`
- Modify: `web_admin/frontend/src/app/app.routes.ts` (route `calibration/references/:id`), `web_admin/frontend/src/app/calibration/calibration-page.html` (reference row name → routerLink), `web_admin/frontend/src/app/api/api.service.ts` + `dto.ts` (getReferenceIntervals/getReferenceGeojson; `ReferenceIntervalRow`)

**Interfaces:**
- `MultiLineChart` (reuses `chart-scale.ts`; same 640×400 viewBox/margins/tokens/tooltip conventions as existing charts):

```ts
export interface LinePoint { x: number; y: number; }
export interface LineSeries { label: string; colorVar: string; points: LinePoint[]; dashed?: boolean; }
export interface BandPoint { x: number; lo: number; hi: number; }
// inputs: series = input<LineSeries[]>([]); band = input<BandPoint[] | null>(null);
//         xLabel = input(''); yLabel = input('');
// band renders as one <path> fill var(--color-accent-muted) opacity .35 under the lines;
// legend row above (swatch+label per series); crosshair tooltip listing every series value at nearest x.
```

- Page `calibration/references/:id`: meta card (all ReferenceOut fields incl. full `parse_warnings` texts as a list); `<app-segment-map [data]="geo()" [metricKey]="'iri_ref'" />`; profile `MultiLineChart` with one series «IRI профілометра (сер. кан. 1–8)» (`--color-fg`), x = chainage km; intervals table paginated 200 rows (prev/next buttons, «N–M з K»), columns: interval_id, пікетаж (км), iri_ref, ch1..ch8 collapsed to min/max («діапазон каналів»).

- [ ] **Step 1: Failing specs:** MultiLineChart renders one `path` per series + band path when provided (3-point fixtures); reference page shows road_name, full warning texts, and pagination math («1–200 з 1108» fixture).
- [ ] **Step 2:** Implement chart → page → route → link from the references table row.
- [ ] **Step 3:** `ng test` + `ng build` green. Commit `feat(web-admin-ui): reference detail page with interval map and profile chart`.

### Task 5: Aggregate UI — section, creation, detail page, set creation

**Files:**
- Create: `web_admin/frontend/src/app/calibration/aggregate-detail.ts|html|css|spec.ts`, `web_admin/frontend/src/app/calibration/create-set-dialog.ts` (shared)
- Modify: `web_admin/frontend/src/app/calibration/calibration-page.ts|html|css|spec.ts` (new section «Мультипроїзні порівняння»), `web_admin/frontend/src/app/calibration/comparison-detail.ts|html` (reuse the shared dialog), `app.routes.ts` (route `calibration/aggregates/:id`), `api.service.ts` + `dto.ts` (createAggregate/listAggregates/getAggregate/deleteAggregate/aggregateArtifactUrl/getAggregateChartData; `AggregateOut`, `AggregateChartData`)

**Interfaces:**
- Calibration tab section: «Нове мультипроїзне порівняння» dialog — select reference (step 10, not deleted) + checkbox list of done runs (≥2 enforced client-side, button disabled until 2 checked); table: id, еталон, N ранів (title = filenames), status badge, bias±CI / σ_r / ρ from summary, «stale» chip when summary.stale, «Відкрити», delete. Poll while queued/running (same pattern; single shared poller with comparisons is fine).
- `CreateSetDialog` (extracted from comparison-detail's dialog, single source): inputs `provenance: {kind: 'comparison'|'aggregate', id: number}`, `defaultModel`, `eq3Disabled`, `vehicleType`, `phoneOptions: {label, value: string|null}[]`, `defaultName`; emits `created(CoefficientSetOut)`. Comparison-detail refactored to use it (existing specs updated, behavior identical); aggregate-detail uses it with `eq3Disabled=true`, model fixed eq6_bias.
- Aggregate detail page: KPI row (проїздів, бінів, bias ± CI (one tile: «−1.61 [−1.8; −1.4]»), σ_r, MAE агрегованого, ρ); MultiLineChart: band(lo,hi) + series «Еталон» (`--color-fg`) and «Смартфон (середнє проїздів)» (`--color-accent`); speed-effect card («Швидкісний ефект: −0.05 м/км на км/год ± 0.01; n=…» or muted «швидкості проїздів однакові — ефект не оцінюється»); bins table (chainage км, iri_ref, mean, std («—» when null), n_passes, diff) sorted by chainage; «Створити набір коефіцієнтів» via CreateSetDialog; artifacts PNG links.

- [ ] **Step 1: Failing specs:** creation dialog disables submit until 2 runs checked; aggregate page KPI renders bias with CI from fixture; stale chip renders; CreateSetDialog calls `createCoefficientSet` with `aggregate_comparison_id` and model eq6_bias; comparison-detail still creates with `comparison_id` (regression spec survives the refactor).
- [ ] **Step 2:** Implement (DTO/service first, then dialog extraction + comparison-detail refactor, then section, then page).
- [ ] **Step 3:** Full `ng test` + build green. Commit `feat(web-admin-ui): multi-pass aggregate comparisons UI with shared set-creation dialog`.

### Task 6: Calibration UX fix — phone prefill, resolution preview, user-set migration

**Files:**
- Modify: `web_admin/backend/src/services/coefficients.py`, `web_admin/backend/src/api/coefficient_sets.py`, `web_admin/backend/src/api/schemas.py`, `web_admin/backend/src/api/runs.py` (RunOut enrichment), `web_admin/frontend/src/app/api/dto.ts|api.service.ts`, `web_admin/frontend/src/app/calibration/create-set-dialog.ts`, `web_admin/frontend/src/app/calibration/calibration-page.ts|html` (confirm dialog preview)
- Test: `web_admin/backend/tests/test_coefficient_sets_api.py` (extend), frontend specs

**Interfaces:**
- `coefficients.py`: `def files_resolving_to(session, vehicle_type: str|None, phone_model: str|None) -> list[SourceFile]` — non-deleted files whose meta vehicle_type matches AND (`phone_model is None` OR `phone_model_from_meta(meta) == phone_model`). (Existing `_candidate_files` in the router delegates to it with `phone_model=None` — reanalyze semantics unchanged.)
- `POST /api/coefficient-sets/preview-resolution` body `{model: str, vehicle_type: str, phone_model: str|null}` → `{files_matched: int, filenames: list[str]}` (model validated but unused in the count — reserved).
- `RunOut` gains `phone_model: str|None` (enrichment in `_to_out` via `phone_model_from_meta(run.file.recording_meta)` — None-safe). DTO mirrored.
- CreateSetDialog: phone field becomes a **select** with exactly two options built from the run's `phone_model`: «Точний телефон (<device>)» → value device string, «Будь-який телефон цього типу авто» → null. When run.phone_model is null → only the null option. No free text.
- Confirm dialog (calibration-page): on open calls preview; shows «Застосується до N файлів» (list in title tooltip); N=0 → red `.error-banner`-styled warning «Жоден наявний файл не збігається — перевірте телефон/тип авто» (confirm still allowed — the decision is human).
- **User-set migration step (controller-verified data change):** create the corrected draft via the API against the real DB: POST `/api/coefficient-sets` `{comparison_id: 2, model: 'eq6_bias', name: 'eq6_bias_van_SM-S948B_2026-08-20', vehicle_type: 'van', phone_model: 'samsung SM-S948B'}` (script `web_admin/backend/scripts/create_corrected_draft.py` using `TestClient(create_app())` with default env → real admin.db; idempotent: skip on 409 duplicate name). DO NOT confirm it — leave draft for the user. Print the resolution preview for it.

- [ ] **Step 1: Failing tests:** `files_resolving_to` phone-aware (exact device matches; NULL matches all of type; wrong device → 0); preview endpoint counts; RunOut.phone_model enrichment; frontend: dialog renders exactly two options and posts the chosen value; confirm dialog shows «0 файлів» warning from a stubbed preview.
- [ ] **Step 2:** Implement backend → DTO → dialog/preview. Run suites.
- [ ] **Step 3:** Run the migration script against the real backend DB (server on :8000 may keep running — TestClient uses the file directly; ensure the uvicorn process won't clash: SQLite WAL not enabled → run while uvicorn idle, it is single-writer short transaction — acceptable locally). Verify: GET coefficient-sets shows the new draft; preview for it reports ≥3 files.
- [ ] **Step 4:** Commit `feat(web-admin): phone-aware resolution preview and set-creation prefill`.

### Task 7: Run-vs-run comparison of one file

**Files:**
- Modify: `web_admin/backend/src/api/files.py` (or new `src/api/file_compare.py` — keep in files.py, it is one endpoint), `web_admin/backend/src/api/schemas.py`, `web_admin/frontend/src/app/runs/run-detail.ts|html` (button + dialog), `app.routes.ts` (route `runs/:id/compare/:other`), `api.service.ts`/`dto.ts`
- Create: `web_admin/frontend/src/app/runs/run-compare.ts|html|css|spec.ts`
- Test: `web_admin/backend/tests/test_file_compare.py`

**Interfaces:**
- `GET /api/files/{file_id}/compare?run_a=<id>&run_b=<id>` → 404 unknown file/run; 409 UA «ран не належить цьому файлу» / «обидва рани мають бути завершені». Response:

```python
{'file_id', 'run_a': {'id','params','summary'}, 'run_b': {...},
 'segments': [{'seg_id','s_start','iri_multi_a','iri_multi_b','delta_iri_multi',
               'iri_psd_a','iri_psd_b','grms_a','grms_b','mean_speed_a','mean_speed_b'}],
 'summary': {'segments': n, 'matched': m, 'mean_delta_iri_multi', 'max_abs_delta'}}
```

  Inner join both `road_segments.csv` on seg_id; deltas null when either side null (low-speed invariant); NaN→null; `matched` may be < `segments` when policies differ — no error.
- UI: run-detail header button «Порівняти з іншим раном» (visible when the file has ≥2 done runs — needs `listRuns(file_id)` already available) → dialog select → navigate `runs/:id/compare/:other`. Compare page: two params chips rows (policy + coefficient set names from each run's params), summary KPIs, table with |delta|>0.5 rows `--color-warn-bg`, null-safe «—».

- [ ] **Step 1: Failing tests:** two stub-analyze runs of one file with shifted iri_multi → deltas exact; run of another file → 409; queued run → 409; null iri_multi on one side → null delta. Frontend spec: table renders deltas and highlights |delta|>0.5 fixture row.
- [ ] **Step 2:** Implement backend → UI. Suites green.
- [ ] **Step 3:** Commit `feat(web-admin): run-vs-run comparison for a single file`.

### Task 8: Dashboard vehicle-type breakdown

**Files:**
- Modify: `web_admin/backend/src/services/dashboard.py`, `web_admin/backend/src/api/schemas.py` (DashboardOut + `by_vehicle_type`), `web_admin/frontend/src/app/dashboard/dashboard-page.ts|html|css`, `dto.ts`
- Test: `web_admin/backend/tests/test_dashboard_api.py` (extend)

**Interfaces:**
- `DashboardOut.by_vehicle_type: dict[str, VehicleTypeStats]` where key = vehicle_type or `'невідомо'`; `VehicleTypeStats {files_total, runs_done, km_total, low_speed_total, mean_iri_multi (nullable), iri_histogram}` — computed over the latest done run per file (same rule as global map).
- UI: chips row above the cards: «Всі» + one chip per type (hidden when only one key and it is 'невідомо'); selecting a chip swaps KPI cards + histogram to that type's stats; «Всі» = existing global fields (unchanged).

- [ ] **Step 1: Failing tests:** two files with different vehicle_type metas (stub runs) → breakdown has both keys with correct counts; file without meta → 'невідомо'. Frontend spec: chip click swaps the km KPI to the fixture's per-type value.
- [ ] **Step 2:** Implement; suites green.
- [ ] **Step 3:** Commit `feat(web-admin): dashboard vehicle-type breakdown`.

### Task 9: Dissertation chapters — wave 1 (structure + розділи 1–2)

**Files (outside git — `c:\DEV\my_project\University\Dissertation\chapters\`):**
- Create: `00_structure.md`, `01_analysis.md`, `02_methods.md`

**Sources (read, compile, expand — не тези, а зв'язний текст):** `docs/01_background_and_problem_statement.md`, `docs/02_methods_new_pipeline.md`, `docs/03_methods_legacy_pipeline.md`, `docs/06_threats_to_validity_and_limitations.md`, `docs/paper_draft_uk.md`, `analyzer/src/road_quality_analyzer/metrics/iri.py` (формули/константи), ADB guidebook context recorded in docs (НЕ вигадувати сторінкові цитати).

**Content contract:**
- `00_structure.md`: повний зміст дисертації (вступ, 4 розділи, висновки, додатки), цільовий обсяг кожного розділу в сторінках (сумарно 150–220), статус наповнення по файлах (таблиця: файл → чернетковий обсяг у знаках → % готовності), правила ведення (мова, без вигаданих цитат, джерела чисел = наші артефакти).
- `01_analysis.md` (~35–45 тис. знаків): предметна область (стан доріг України, IRI як метрика), огляд методів моніторингу (профілометри класів 1–2, response-type, смартфонні), огляд книги ADB (Eq.3 PSD-шлях, Eq.4–6 Grms-шлях, класи LEV/DSD/GENERIC), постановка задачі дослідження, вимоги до системи.
- `02_methods.md` (~45–60 тис. знаків): конвеєр обробки (часова сітка 100 Гц, фільтрація, сегментація 100 м), метрики (Grms, PSD у смузі 0.5–6 Гц, `psd_sqrt_scalar`), формули Eq.3 (з книжковими константами 0.774/−0.825 і чесним поясненням від'ємних raw та кліпу), Eq.4–6 з таблицею коефіцієнтів (з `iri.py`), low-speed політика і клас 1/2, контракти CSV v2.1/v3 (преамбула, events, футер), методологія калібрування: bias-корекція, LORO-валідація, мультипроїзна агрегація (бінінг, σ_r, t-CI з ефективним n, демінований FE-оцінювач швидкості — з Task 1 docstrings).

- [ ] **Step 1:** Read every source file listed; draft the three files (Ukrainian, зв'язний академічний текст; формули як Unicode/легкий LaTeX-подібний запис у md).
- [ ] **Step 2:** Verify volumes (report chars per file), hidden-char scan over the three files (0 hits), numbers cross-checked against sources (константи з iri.py звірені буквально).
- [ ] **Step 3:** No git commit (outside repo). Report volumes + status table.

### Task 10: Dissertation chapters — wave 2 (розділи 3–4)

**Files:** `03_system.md`, `04_experiments.md` (same directory).

**Sources:** `docs/00_index.md`, `docs/04_experimental_design_and_reproducibility.md`, `docs/05_results_legacy_vs_new.md`, `docs/08_user_guide_and_cli_reference.md` (фази адмінки), `docs/10_profilometer_validation.md`, `web_admin/README.md`, RoadSensorRecorder repo docs: `../RoadSensorRecorder/docs/superpowers/specs/*.md` and README/CHANGELOG (стадії A/B), Phase-2/3 specs+plans у `docs/superpowers/`.

**Content contract:**
- `03_system.md` (~45–60 тис. знаків): архітектура комплексу (три компоненти), Android-застосунок (монотонна часова база, watchdog/StreamHealth, профілі авто, локалізація, CSV контракти — зі стадій A/B), аналізатор (пайплайн, артефакти, звіт, 181 тест), веб-адмінка (фази 1–3: сутності, черга, порівняння, набори коефіцієнтів, резолюція з провенансом, палітра мапи як data-contract), рішення щодо цілісності (книжкові константи в коді, ручне підтвердження, снапшоти).
- `04_experiments.md` (~40–55 тис. знаків): польові дані (двотелефонні одночасні заїзди, форми профілометра М-03/Т1016), валідаційне дослідження (методика матчингу віконним 10 м еталоном, результати: ρ=0.941 Т1016, нуль-результат М-03 з поясненням стелі чутливості, ендогенність швидкості, чесний негативний результат Eq.3, підтвердження структури Eq.6, bias −1.55, LORO), рантайм-відтворення в адмінці (n=164, ρ=0.9407), калібрувальний воркфлоу як метрологічна процедура, польовий протокол мультипроїздів (3 проїзди × 2–3 швидкості; що дає і чого не дає — з обґрунтуванням потреби 4–5 доріг), майбутні результати агрегації (задел під заповнення після польових вимірів).

- [ ] Steps 1–3 як у Task 9 (читання джерел → текст → обсяги + скан).

### Task 11: Dissertation wave 3 (висновки, додатки) + pipeline rule

**Files:** `05_conclusions.md`, `06_appendices.md` (same directory); Create: `c:\DEV\my_project\University\.claude\rules\dissertation-pipeline.md`

- `05_conclusions.md` (~10–15 тис. знаків): наукова новизна (мультипроїзна агрегація з FE-оцінювачем; чесна негативна валідація Eq.3; калібрувальний воркфлоу з провенансом), практичне значення, межі застосовності, напрями подальших досліджень (4–5 доріг, повний рефіт, класи авто).
- `06_appendices.md` (~15–25 тис. знаків): контракт CSV v2.1/v3 повністю, REST API таблиці (з docs/08), структури артефактів, схема БД, глосарій термінів UA/EN.
- `dissertation-pipeline.md` rule (коротке, ~20 рядків): де живуть розділи; після кожного наукового результату — дописати відповідний розділ у тій же сесії; українська; числа тільки з артефактів; без вигаданих цитат; hidden-char скан перед завершенням; статусна таблиця в 00_structure.md оновлюється при кожному дописі.

- [ ] Steps як у Task 9; додатково оновити статусну таблицю в `00_structure.md` фактичними обсягами всіх шести розділів.

### Task 12: Docs, rules, full regression, hidden-char scan

**Files:**
- Modify: `docs/08_user_guide_and_cli_reference.md` (розділи: мультипроїзні порівняння з методологією, сторінка еталона, run-vs-run, дашборд-розбивка, preview-resolution), `docs/00_index.md` (Phase 2 статус), `web_admin/README.md`, `.claude/rules/web-admin-backend.md` (aggregates: artifacts під `storage/results/aggregates/`; математика агрегації ТІЛЬКИ з `profilometer_validation.aggregate`), `.claude/rules/web-admin-frontend.md` (MultiLineChart — спільний лінійний чарт; CreateSetDialog — єдиний діалог створення наборів)

- [ ] **Step 1:** Docs updates (українська проза, English code).
- [ ] **Step 2:** Full regression: analyzer 181; study (26+8=34); backend (all); frontend ng test + build; combined analyzer+study single invocation; e2e analyzer sanity 152/19.
- [ ] **Step 3:** Hidden-char scan over ВСІ файли фази (git diff --name-only від стартового коміту фази + три dissertation-файли поза репо + rule file).
- [ ] **Step 4:** Commit `docs(web-admin): phase-2 aggregation documentation and rules`.

---

## Self-review notes

- **Spec coverage:** §1 → Tasks 3–4; §2 → Tasks 1–2, 5; §3 → Task 7; §4 → Task 8; §5 → Task 6 (incl. міграційний draft, підтвердження лишається за користувачем); §6 → Tasks 9–11; §7 межі дотримані (без auth/Postgres/app-змін/eq3-рефіту); §8 тестування розподілене по тасках; §9 порядок збережений.
- **Type consistency:** `bias_with_ci` keys (`bias, ci_low, ci_high, n_bins, n_eff`) ↔ summary/snapshot keys у Task 2/5; `chart_data.profile` keys ↔ `AggregateChartData` DTO ↔ MultiLineChart band mapping (lo/hi); `files_resolving_to` reused by preview і (з phone=None) кандидатами reanalyze; `phone_model` enrichment consumed by CreateSetDialog.
- **Known judgment calls:** aggregate unit = 100 м бін на пікетажі еталона (не сегменти ранів — вони не вирівняні між проїздами); speed_effect тільки при розкиді швидкостей ≥3 км/год; stale-агрегат зберігається (історія), а не видаляється; матфункції в study-пакеті (дисертаційна цінність + тестованість), а серверні фігури агрегатів — локальний matplotlib-блок сервісу (не розширюємо figures.py без потреби); dissertation-файли поза git — скан обов'язковий, комітів немає.
