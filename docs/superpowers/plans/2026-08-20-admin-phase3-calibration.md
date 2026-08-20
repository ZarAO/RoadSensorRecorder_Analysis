# Web Admin Phase 3 — Reference Data & DB-Backed Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin manages profilometer reference forms, runs runtime run-vs-reference comparisons, and confirms named coefficient sets that future runs pick up automatically — plus the unified high-contrast Leaflet map the user asked for.

**Architecture:** The validation study's `match`/`calibrate`/`figures` modules become an installable package (`profilometer_validation`) that the FastAPI backend imports as a library. Three new DB entities (ReferenceDataset, Comparison, CoefficientSet) hold metadata only; parsed intervals and comparison artifacts live on disk. Coefficient resolution happens at run creation (exact key → vehicle-only → book constants), snapshotted into the run for reproducibility. Frontend gains a «Калібрування» tab with dependency-free SVG charts and a shared SegmentMap Leaflet component (new contrast palette + casing) used by both the global map and the run page.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0, SQLite, openpyxl, pytest; Angular 22 (standalone, signals, OnPush), Leaflet, hand-rolled SVG charts (no chart libs, no KaTeX).

**Spec:** `docs/superpowers/specs/2026-08-20-admin-calibration-design.md`

## Global Constraints

- Branch `v1-1-stage`; no `Co-Authored-By`; no hidden/invisible characters in any generated file; code/commits English, UI copy Ukrainian.
- Book constants stay in analyzer code under test-pin — the DB stores only additional named sets (spec §0/§6). No auto-confirmation by gates: gates are indicators, decisions are human (§3.3/§4).
- Analyzer package internals are NOT modified; the analyzer suite (181 tests) is an independent regression contour. The only external knobs used are `analyze(..., iri_psd_A=, iri_psd_B=)` (already exist) and post-processing of artifacts by the backend.
- Backend rules in `.claude/rules/web-admin-backend.md` apply (app factory, `RQA_*` env only, SQLAlchemy 2.0 style, metadata-only DB, traversal-guarded artifact serving, NaN→null). New env var: `RQA_REFERENCE_DIR`.
- Frontend rules in `.claude/rules/web-admin-frontend.md` apply (signals, DTO mirror, ApiService only, tokens-only colors, low-speed IRI invariant, magenta `#FF00FF` data contract).
- No heavy chart libraries; interactive charts are our own SVG components on signals (perf requirement, spec §5).
- Reference upload does not edit forms — upload/view/delete only (§6). Eq.6 full refit and run-vs-run comparison are out of scope (§6).
- Python: `.venv/Scripts/python.exe`; backend tests run from `web_admin/backend`; frontend tests `npx ng test --watch=false` from `web_admin/frontend`.
- Commit after every green task; `git add <explicit paths>` only.

## Spec deviation (documented up front)

Spec §1 gives `AnalysisRun` a single `coefficient_set_id`, but §2 resolves the confirmed set **per model** (`eq3` AND `eq6_bias` fall back independently — "Eq.3 book + Eq.6 без корекції"). The two models affect different pipeline stages (Eq.3 → `analyze()` params; Eq.6 bias → post-processing of `iri_multi`), so a run can legitimately carry one of each. Implementation: **two nullable FKs** `eq3_set_id` and `eq6_bias_set_id`, plus the full snapshot in `run.params['coefficients']`. This implements §2 faithfully; flag it to the user at review.

---

### Task 1: Package the study code as `profilometer_validation`

**Files:**
- Create: `studies/profilometer_validation/pyproject.toml`
- Move (git mv): `studies/profilometer_validation/{__init__.py,match.py,calibrate.py,figures.py}` → `studies/profilometer_validation/src/profilometer_validation/`
- Modify: `studies/profilometer_validation/run_study.py`, `studies/profilometer_validation/tests/conftest.py` (and any test files importing `match`/`calibrate` flat)

**Interfaces:**
- Produces: installable package `profilometer_validation` with submodules `match`, `calibrate`, `figures` — exact same public functions as today (`windowed_reference`, `load_form_10m`, `segment_midpoints_from_geojson`, `match_segments`, `validation_stats`, `bland_altman`, `fit_eq3`, `effective_n`, `influence_on_eq3`, `scatter_fit`, `bland_altman_plot`, `chainage_overlay`, constants `REFERENCE_CHANNELS`, `SQRT_PSD_COL`, `REF_COL`). No function bodies change in this task.

- [ ] **Step 1:** `git mv` the four modules into `src/profilometer_validation/` (keep `run_study.py` and `tests/` where they are). Write `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "profilometer-validation"
version = "1.0.0"
description = "Smartphone-vs-profilometer matching, validation stats and figures (study 2026-08-20, reused by the web admin)"
requires-python = ">=3.12"
dependencies = ["numpy", "pandas", "scipy", "matplotlib", "scienceplots"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 2:** Fix imports. In `run_study.py`: delete the `sys.path.insert(0, str(STUDY_DIR))` line and change to `from profilometer_validation.calibrate import (...)`, `from profilometer_validation.match import (...)`; the in-function `from figures import ...` becomes `from profilometer_validation.figures import ...`. In `tests/conftest.py` and test modules: remove any path hacks; import `from profilometer_validation import match` / `from profilometer_validation.calibrate import ...` (read the current imports first and translate 1:1). `match.py`/`calibrate.py`/`figures.py` have no intra-package imports — nothing to change inside them.
- [ ] **Step 3:** `.venv/Scripts/python.exe -m pip install -e studies/profilometer_validation`
- [ ] **Step 4:** Run: `.venv/Scripts/python.exe -m pytest studies/profilometer_validation/tests -q` → 21 passed. Also prove `run_study.py` still executes end-to-end (imports incl. figures): `.venv/Scripts/python.exe studies/profilometer_validation/run_study.py --out <scratchpad>/study_out` → prints the same «Matched pairs …» counts (М-03: 110, Т1016: 164) and verdict.
- [ ] **Step 5:** Analyzer regression untouched: `.venv/Scripts/python.exe -m pytest analyzer/tests -q` → 181 passed.
- [ ] **Step 6:** Commit `refactor(study): package profilometer_validation as installable library`.

### Task 2: Settings, DB entities, SQLite column migration

**Files:**
- Modify: `web_admin/backend/src/core/config.py`, `web_admin/backend/src/db/models.py`, `web_admin/backend/src/db/session.py`, `web_admin/backend/tests/conftest.py`
- Test: `web_admin/backend/tests/test_phase3_models.py`

**Interfaces:**
- Produces:
  - `Settings.storage_reference_dir: Path` (env `RQA_REFERENCE_DIR`, default `REPO_ROOT / 'storage' / 'reference'`), created in `ensure_dirs()`.
  - `ReferenceDataset`: `id int PK`, `filename str unique` (original xlsx name), `uploaded_at datetime(UTC)`, `road_name str`, `direction str|None`, `lane int|None`, `category int|None`, `step_m float`, `measured_at str|None` (manual ISO date — the form's date cell is stale by policy), `intervals_count int`, `chainage_span_m float`, `bbox JSON|None` (`[min_lat, min_lon, max_lat, max_lon]`), `parse_warnings JSON default list`, `source_deleted bool default False`, relationship `comparisons`.
  - `Comparison`: `id int PK`, `run_id FK analysis_runs.id`, `reference_id FK reference_datasets.id`, `created_at datetime(UTC)`, `status str default 'queued'` (queued|running|done|failed), `params JSON default dict`, `result_dir str|None`, `summary JSON|None`, `error str|None`, relationships `run`, `reference`.
  - `CoefficientSet`: `id int PK`, `name str unique`, `model str` ('eq3'|'eq6_bias'), `params JSON` (`{A,B}` or `{bias}`), `vehicle_type str|None`, `phone_model str|None`, `status str default 'draft'` (draft|confirmed|archived), `comparison_id FK|None`, `stats_snapshot JSON|None`, `created_at datetime(UTC)`, `confirmed_at datetime|None`, `confirmed_note str|None`.
  - `AnalysisRun` gains `eq3_set_id: Mapped[Optional[int]] = mapped_column(ForeignKey('coefficient_sets.id'), default=None)` and `eq6_bias_set_id` likewise (see “Spec deviation”).
  - `init_db(engine)` = `create_all` + `_ensure_run_columns(engine)`: SQLite `create_all` never alters existing tables, so add the two columns via `PRAGMA`-inspect + `ALTER TABLE analysis_runs ADD COLUMN ...` when missing (idempotent; keeps the existing `admin.db` with runs 1–3 working).

- [ ] **Step 1: Failing tests** (`test_phase3_models.py`):

```python
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


def test_phase3_models_roundtrip(tmp_path):
    from src.db.session import make_engine, init_db
    from src.db.models import (AnalysisRun, Comparison, CoefficientSet,
                               ReferenceDataset, SourceFile)
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    with Session(engine) as s:
        ref = ReferenceDataset(filename='f.xlsx', road_name='Т1016', step_m=10.0,
                               intervals_count=164, chainage_span_m=1640.0,
                               bbox=[50.1, 30.1, 50.4, 30.9], parse_warnings=[])
        f = SourceFile(filename='a.csv', size_bytes=1)
        s.add_all([ref, f]); s.commit()
        run = AnalysisRun(file_id=f.id)
        cs = CoefficientSet(name='UA_test', model='eq6_bias', params={'bias': -1.55},
                            vehicle_type='van', phone_model='samsung SM-S948B')
        s.add_all([run, cs]); s.commit()
        cmp_ = Comparison(run_id=run.id, reference_id=ref.id, params={})
        s.add(cmp_); s.commit()
        assert cmp_.reference.road_name == 'Т1016'
        assert cmp_.run.id == run.id
        run.eq6_bias_set_id = cs.id; s.commit()
        assert s.get(AnalysisRun, run.id).eq6_bias_set_id == cs.id


def test_init_db_migrates_existing_runs_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE analysis_runs (id INTEGER PRIMARY KEY, file_id INTEGER)'))
    from src.db.session import init_db
    init_db(engine)
    cols = {col['name'] for col in inspect(engine).get_columns('analysis_runs')}
    assert {'eq3_set_id', 'eq6_bias_set_id'} <= cols
    init_db(engine)  # idempotent


def test_reference_dir_setting(tmp_path, monkeypatch):
    from src.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv('RQA_REFERENCE_DIR', str(tmp_path / 'ref'))
    assert get_settings().storage_reference_dir == tmp_path / 'ref'
    get_settings.cache_clear()
```

- [ ] **Step 2:** Run `cd web_admin/backend && ../../.venv/Scripts/python.exe -m pytest tests/test_phase3_models.py -q` → fails.
- [ ] **Step 3:** Implement models/settings/migration. Migration helper in `session.py`:

```python
def _ensure_run_columns(engine) -> None:
    # SQLite create_all() never ALTERs an existing table; add Phase-3 columns in place
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if 'analysis_runs' not in inspector.get_table_names():
        return
    existing = {c['name'] for c in inspector.get_columns('analysis_runs')}
    with engine.begin() as conn:
        for column in ('eq3_set_id', 'eq6_bias_set_id'):
            if column not in existing:
                conn.execute(text(f'ALTER TABLE analysis_runs ADD COLUMN {column} INTEGER'))
```

Also add `monkeypatch.setenv('RQA_REFERENCE_DIR', str(tmp_path / 'reference'))` to the `client` fixture in `tests/conftest.py`.
- [ ] **Step 4:** Whole backend suite green: `../../.venv/Scripts/python.exe -m pytest -q` (25 existing + 3 new).
- [ ] **Step 5:** Commit `feat(web-admin): phase-3 entities, reference storage setting, sqlite column migration`.

### Task 3: Profilometer xlsx form parser service

**Files:**
- Create: `web_admin/backend/src/services/reference_forms.py`
- Modify: `web_admin/backend/requirements.txt` (add `openpyxl==3.1.5`)
- Test: `web_admin/backend/tests/test_reference_forms.py` (+ fixture builder in `tests/conftest.py`)

**Interfaces:**
- Produces:

```python
@dataclass
class ParsedForm:
    road_name: str            # "Об'єкт (ділянка)" cell; fallback: xlsx stem
    direction: str | None     # "Напрям руху"
    lane: int | None          # "Номер смуги руху"
    category: int | None      # "Технічна категорія"
    step_m: float             # median |chainage_end - chainage_start| over data rows
    intervals: pd.DataFrame   # columns: km_start,m_start,km_end,m_end,iri_ch1..iri_ch10,
                              #          lat_start,lon_start,alt_start,lat_end,lon_end,alt_end
    chainage_span_m: float
    bbox: list                # [min_lat, min_lon, max_lat, max_lon]
    warnings: list[str]

def parse_form_xlsx(path: str) -> ParsedForm   # raises ValueError on structural failure
```

- The `intervals` column set matches the study's derived-CSV format **exactly**, so `profilometer_validation.match.load_form_10m` reads the stored CSV unchanged.

**Real form layout** (recon of `storage/field_measurements/sample_official_measurements/*.xlsx`): one sheet, 20 columns; metadata rows 1–19 (label cells: `Об'єкт (ділянка):` row 2 value col 6; `Технічна категорія` row 6 value col 6 and `Номер смуги руху:` same row value col 14; `Напрям руху:` row 7 value col 6 — but SEARCH by label text, never by fixed row); header row (row 22 in samples) = `км|м|км|м|канал 1..канал 10|широта|довгота|висота|широта|довгота|висота`; data rows follow until the first row with empty `км`.

- [ ] **Step 1:** Add a fixture builder to `tests/conftest.py`:

```python
def build_form_xlsx(path, n_rows=12, step_m=10, road='Т-9999', lane=1, category=2,
                    direction='Прямий', duplicate_ch9_10=True, break_continuity_at=None):
    """Miniature profilometer form with the real sheet layout (header row 22)."""
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.cell(row=2, column=1, value="Об'єкт (ділянка):"); ws.cell(row=2, column=6, value=road)
    ws.cell(row=6, column=1, value='Технічна категорія'); ws.cell(row=6, column=6, value=category)
    ws.cell(row=6, column=10, value='Номер смуги руху:'); ws.cell(row=6, column=14, value=lane)
    ws.cell(row=7, column=1, value='Напрям руху:'); ws.cell(row=7, column=6, value=direction)
    header = ['км', 'м', 'км', 'м'] + [f'канал {i}' for i in range(1, 11)] + \
             ['широта', 'довгота', 'висота', 'широта', 'довгота', 'висота']
    for col, text in enumerate(header, start=1):
        ws.cell(row=22, column=col, value=text)
    for i in range(n_rows):
        start = i * step_m
        end = start + step_m + (5 if break_continuity_at == i else 0)
        iri = [1.0 + 0.1 * i + 0.01 * ch for ch in range(1, 9)]
        ch8 = iri[-1]
        iri += [ch8, ch8] if duplicate_ch9_10 else [ch8 + 0.5, ch8 + 0.6]
        row = [start // 1000, start % 1000, end // 1000, end % 1000, *iri,
               50.0 + i * 1e-4, 30.0 + i * 1e-4, 120.0,
               50.0 + (i + 1) * 1e-4, 30.0 + (i + 1) * 1e-4, 120.0]
        for col, v in enumerate(row, start=1):
            ws.cell(row=23 + i, column=col, value=v)
    wb.save(path)
    return path
```

- [ ] **Step 2: Failing tests** (`test_reference_forms.py`):

```python
import pytest
from tests.conftest import build_form_xlsx


def test_parse_happy_path(tmp_path):
    from src.services.reference_forms import parse_form_xlsx
    p = build_form_xlsx(tmp_path / 'f.xlsx', n_rows=12, step_m=10)
    form = parse_form_xlsx(str(p))
    assert form.road_name == 'Т-9999' and form.lane == 1 and form.category == 2
    assert form.step_m == 10 and len(form.intervals) == 12
    assert form.chainage_span_m == 120
    assert list(form.intervals.columns)[:4] == ['km_start', 'm_start', 'km_end', 'm_end']
    assert form.bbox[0] <= 50.0 and form.bbox[2] >= 50.0012
    assert any('канал' in w or 'channel' in w for w in form.warnings)  # ch9/10 duplicate warning


def test_parse_no_header_raises(tmp_path):
    from src.services.reference_forms import parse_form_xlsx
    import openpyxl
    wb = openpyxl.Workbook(); wb.active.cell(row=1, column=1, value='garbage')
    p = tmp_path / 'bad.xlsx'; wb.save(p)
    with pytest.raises(ValueError, match='header'):
        parse_form_xlsx(str(p))


def test_parse_continuity_warning(tmp_path):
    from src.services.reference_forms import parse_form_xlsx
    p = build_form_xlsx(tmp_path / 'gap.xlsx', break_continuity_at=5)
    form = parse_form_xlsx(str(p))
    assert any('gap' in w.lower() or 'розрив' in w.lower() for w in form.warnings)


def test_loadable_by_study_matcher(tmp_path):
    """The stored CSV must feed profilometer_validation.match.load_form_10m unchanged."""
    from src.services.reference_forms import parse_form_xlsx
    from profilometer_validation.match import load_form_10m
    p = build_form_xlsx(tmp_path / 'f.xlsx')
    form = parse_form_xlsx(str(p))
    csv = tmp_path / 'intervals_10m.csv'
    form.intervals.to_csv(csv, index=False, encoding='utf-8', lineterminator='\n')
    table = load_form_10m(str(csv))
    assert {'iri_ref_10', 'lat_mid', 'lon_mid', 'chainage_m'} <= set(table.columns)
    assert len(table) == 12
```

- [ ] **Step 3:** Run → fails. Implement `parse_form_xlsx`:
  - `openpyxl.load_workbook(path, read_only=True, data_only=True)`, active sheet; wrap `InvalidFileException`/zip errors into `ValueError('не вдалося прочитати xlsx: ...')`.
  - Header search over rows 1–40: the first row whose first four string cells strip to `('км','м','км','м')` and whose 5th cell starts with `канал`. Not found → `ValueError("header row not found: expected 'км|м|км|м|канал 1…'")`.
  - Metadata: scan rows above the header; for each of the label substrings (`"Об'єкт"`, `'Технічна категорія'`, `'Номер смуги'`, `'Напрям руху'`) find the label cell and take the first non-empty cell to its right in the same row; int-coerce lane/category (failures → warning + None).
  - Data rows: from header+1 until first row with `km_start is None`; require ≥ 5 rows else `ValueError('too few data rows')`; coerce all 20 cells to float (a non-numeric row is dropped with a warning naming the 1-based row).
  - `chainage(row) = km*1000 + m`; `step_m = float(np.median(|chain_end - chain_start|))`; rows deviating from the median step → warning with count.
  - Continuity: `chain_start[i+1] != chain_end[i]` (works for increasing and decreasing forms) → warning `f'{n} chainage gap/overlap rows'`.
  - Duplicate channels: if `iri_ch9` and `iri_ch10` equal `iri_ch8` elementwise → warning `'канали 9–10 дублюють канал 8; еталон рахується з каналів 1–8'`.
  - `chainage_span_m = abs(chain_end.iloc[-1] - chain_start.iloc[0])`; bbox over all four coord columns.
- [ ] **Step 4:** Tests pass; add `openpyxl==3.1.5` to `requirements.txt`.
- [ ] **Step 5:** Commit `feat(web-admin): profilometer xlsx form parser with structural validation`.

### Task 4: References API (upload / list / detail / delete)

**Files:**
- Create: `web_admin/backend/src/api/references.py`, `web_admin/backend/src/services/references.py`
- Modify: `web_admin/backend/src/api/schemas.py` (add `ReferenceOut`), `web_admin/backend/src/main.py` (include router)
- Test: `web_admin/backend/tests/test_references_api.py`

**Interfaces:**
- Produces:
  - `services/references.py`: `store_reference(session, settings, tmp_xlsx: Path, original_name: str, measured_at: str|None, road_name: str|None) -> ReferenceDataset` — parses (ValueError propagates), commits the row, then writes `settings.storage_reference_dir/<id>/original.xlsx` (copy) and `intervals_{int(step_m)}m.csv` (`to_csv(index=False, encoding='utf-8', lineterminator='\n')`); `reference_dir(settings, ref) -> Path`; `delete_reference_data(settings, ref)` (rmtree, ignore_errors).
  - `ReferenceOut` (mirrors the model + `comparisons_count: int = 0`): `id, filename, uploaded_at, road_name, direction, lane, category, step_m, measured_at, intervals_count, chainage_span_m, bbox, parse_warnings, source_deleted, comparisons_count`.
  - Router `prefix='/references'`:
    - `POST ''` multipart (`file: UploadFile`, form fields `measured_at: str|None = Form(None)`, `road_name: str|None = Form(None)`) → 201 `ReferenceOut`; 409 duplicate filename; 422 on parse `ValueError` (temp file cleaned up — mirror `files.py` upload pattern).
    - `GET ''` → `list[ReferenceOut]` newest first.
    - `GET '/{ref_id}'` → `ReferenceOut` (404).
    - `DELETE '/{ref_id}'` → 204; removes the data dir, sets `source_deleted=True`, KEEPS the row and its comparisons (mirrors the file-delete contract).

- [ ] **Step 1: Failing tests:**

```python
from tests.conftest import build_form_xlsx


def _upload(client, tmp_path, name='form.xlsx', **kwargs):
    p = build_form_xlsx(tmp_path / name, **kwargs)
    with open(p, 'rb') as f:
        return client.post('/api/references', files={'file': (name, f)},
                           data={'measured_at': '2026-08-20'})


def test_upload_list_detail(client, tmp_path):
    r = _upload(client, tmp_path)
    assert r.status_code == 201
    body = r.json()
    assert body['road_name'] == 'Т-9999' and body['step_m'] == 10
    assert body['measured_at'] == '2026-08-20'
    assert body['intervals_count'] == 12 and len(body['parse_warnings']) >= 1
    assert client.get('/api/references').json()[0]['id'] == body['id']
    assert client.get(f"/api/references/{body['id']}").status_code == 200


def test_upload_duplicate_409_and_bad_422(client, tmp_path):
    assert _upload(client, tmp_path).status_code == 201
    assert _upload(client, tmp_path).status_code == 409
    import openpyxl
    bad = tmp_path / 'bad.xlsx'
    wb = openpyxl.Workbook(); wb.active.cell(row=1, column=1, value='x'); wb.save(bad)
    with open(bad, 'rb') as f:
        assert client.post('/api/references', files={'file': ('bad.xlsx', f)}).status_code == 422


def test_delete_keeps_row_marks_deleted(client, tmp_path):
    ref_id = _upload(client, tmp_path).json()['id']
    assert client.delete(f'/api/references/{ref_id}').status_code == 204
    body = client.get(f'/api/references/{ref_id}').json()
    assert body['source_deleted'] is True
```

- [ ] **Step 2:** Run → fails. Implement service + router (upload streams to a temp file first, exactly like `files.py`; storage dir written only after the row exists so the dir name is the id).
- [ ] **Step 3:** Verify the intervals CSV landed: extend `test_upload_list_detail` with a filesystem assert via `RQA_REFERENCE_DIR` (`os.environ['RQA_REFERENCE_DIR']` inside the test): `assert (Path(os.environ['RQA_REFERENCE_DIR']) / str(body['id']) / 'intervals_10m.csv').is_file()`.
- [ ] **Step 4:** Backend suite green. Commit `feat(web-admin): reference dataset upload/list/delete with parsed intervals storage`.

### Task 5: Coefficient resolution at run creation + application in the pipeline

**Files:**
- Create: `web_admin/backend/src/services/coefficients.py`
- Modify: `web_admin/backend/src/api/runs.py` (`_create_and_submit`, `get_segments`), `web_admin/backend/src/services/analysis.py` (`execute_run`, `build_summary`)
- Test: `web_admin/backend/tests/test_coefficients.py`

**Interfaces:**
- Produces (`services/coefficients.py`):

```python
def phone_model_from_meta(recording_meta: dict | None) -> str | None
    # preamble 'device' = 'samsung SM-S948B, android=16' -> 'samsung SM-S948B'

def resolve(session, model: str, vehicle_type: str | None,
            phone_model: str | None) -> CoefficientSet | None
    # 1) confirmed + exact (model, vehicle_type, phone_model)
    # 2) confirmed + (model, vehicle_type, phone_model IS NULL)
    # 3) None  (caller falls back to book constants)

def resolve_for_meta(session, recording_meta: dict | None) -> dict
    # {'eq3': {'set_id', 'name', 'params'} | None, 'eq6_bias': {...} | None}
```

- `_create_and_submit` stores the snapshot: `params['coefficients'] = snapshot` (key omitted entirely when both are None), sets `run.eq3_set_id` / `run.eq6_bias_set_id`.
- `execute_run`: passes `iri_psd_A/B` from the eq3 snapshot into `analyze()`; on success writes `result_dir/calibration.json` (the snapshot, `ensure_ascii=False, indent=1`) and `build_summary(result_dir, coefficients)` adds `'coefficients'` plus `mean_iri_multi_corrected = mean_iri_multi - bias` when an eq6_bias snapshot exists (None-safe). Analyzer artifacts are never mutated — correction is applied in responses.
- `get_segments`: when the run's params carry an eq6_bias snapshot, add `iri_multi_corrected` per row (`iri_multi - bias`; NaN stays null). The low-speed invariant holds: null `iri_multi` yields null corrected.

- [ ] **Step 1: Failing tests:**

```python
from sqlalchemy.orm import Session

META_VAN = {'preamble': {'device': 'samsung SM-S948B, android=16'},
            'vehicle': {'vehicle_type': 'van'}}


def _add_set(engine, **kw):
    from src.db.models import CoefficientSet
    defaults = dict(name=kw.pop('name'), model='eq6_bias', params={'bias': -1.55},
                    vehicle_type='van', phone_model=None, status='confirmed')
    defaults.update(kw)
    with Session(engine) as s:
        cs = CoefficientSet(**defaults); s.add(cs); s.commit(); return cs.id


def test_resolution_fallback_chain(client):
    from src.services.coefficients import resolve_for_meta
    engine = client.app.state.engine
    generic = _add_set(engine, name='van_any')
    exact = _add_set(engine, name='van_s948', phone_model='samsung SM-S948B')
    with Session(engine) as s:
        snap = resolve_for_meta(s, META_VAN)
        assert snap['eq6_bias']['set_id'] == exact
        assert snap['eq3'] is None
        other = resolve_for_meta(s, {'preamble': {'device': 'pixel 9'},
                                     'vehicle': {'vehicle_type': 'van'}})
        assert other['eq6_bias']['set_id'] == generic
        assert resolve_for_meta(s, {'vehicle': {}})['eq6_bias'] is None


def test_run_snapshot_and_corrected_segments(client, tmp_path, monkeypatch):
    engine = client.app.state.engine
    _add_set(engine, name='van_bias')

    calls = {}
    def fake_analyze(input_path, output_dir, low_speed_policy='invalid',
                     iri_psd_A=None, iri_psd_B=None):
        calls['iri_psd_A'] = iri_psd_A
        import pandas as pd, json
        from pathlib import Path
        out = Path(output_dir)
        pd.DataFrame({'seg_id': [0, 1], 'length_m': [100.0, 100.0],
                      'iri_multi': [4.0, None], 'partial': [False, False],
                      'speed_valid': [True, False],
                      'needs_class12_survey': [False, True]}).to_csv(
            out / 'road_segments.csv', index=False)
        (out / 'recording_meta.json').write_text(json.dumps(
            {'events': [], 'clean_stop': True,
             'vehicle': {'vehicle_type': 'van'}}), encoding='utf-8')
    monkeypatch.setattr('src.services.analysis.analyze', fake_analyze)

    csv = b'# schema=2\n# device: samsung SM-S948B, android=16\n# vehicle_type=van\nTime,Type,X,Y,Z,Latitude,Longitude\n'
    # upload via the real endpoint so recording_meta is parsed from the CSV
    r = client.post('/api/files', files={'file': ('v.csv', csv)})
    assert r.status_code == 201
    run = client.post('/api/runs', json={'file_id': r.json()['id'], 'params': {}}).json()
    assert run['params']['coefficients']['eq6_bias']['params'] == {'bias': -1.55}
    assert calls['iri_psd_A'] is None          # eq3 not confirmed -> book constants
    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail['summary']['coefficients']['eq6_bias']['name'] == 'van_bias'
    assert detail['summary']['mean_iri_multi_corrected'] == 4.0 + 1.55
    rows = client.get(f"/api/runs/{run['id']}/segments").json()
    assert rows[0]['iri_multi_corrected'] == 4.0 + 1.55
    assert rows[1]['iri_multi_corrected'] is None   # low-speed stays null
```

  If the minimal CSV above fails `probe_csv`'s contract check, read `src/services/preview.py` first and extend the byte string with whatever minimal rows the contract requires (e.g. one Accelerometer + one Location row) — do NOT weaken `probe_csv`.
- [ ] **Step 2:** Run → fails. Implement service and wiring. NULL-safe exact-match query (`phone_model` may be None → skip the exact tier). `execute_run` reads `run.params.get('coefficients')`; `calibration.json` written only when a snapshot exists.
- [ ] **Step 3:** Tests pass; whole backend suite green (existing run tests unaffected: no confirmed sets → no `coefficients` key).
- [ ] **Step 4:** Commit `feat(web-admin): confirmed coefficient-set resolution and application per run`.

### Task 6: Comparison job service (match → stats → figures → chart_data)

**Files:**
- Create: `web_admin/backend/src/services/comparison.py`
- Modify: `studies/profilometer_validation/src/profilometer_validation/figures.py` (`chainage_overlay` gains `smartphone_label` param), `studies/profilometer_validation/run_study.py` (pass the honest label)
- Test: `web_admin/backend/tests/test_comparison_service.py`

**Interfaces:**
- Produces: `execute_comparison(comparison_id: int, engine, settings) -> None` — same status-transition shape as `execute_run` (queued→running→done/failed, timestamps via the models' default UTC now pattern, error message into `Comparison.error`).
- Job steps (spec §3):
  1. Guards, each failing with a Ukrainian explanation in `error`: run exists and `status=='done'` with `road_segments.csv` + `roughness.geojson` present; reference exists, not `source_deleted`, `step_m == 10` («еталон має бути 10 м формою»); bbox intersect with 0.01° margin («ділянки рану та еталона не перетинаються географічно») — run bbox computed from all `roughness.geojson` coordinates.
  2. `usable = segment_midpoints_from_geojson(pd.read_csv(.../road_segments.csv), .../roughness.geojson)`; `form10 = load_form_10m(<ref dir>/intervals_10m.csv)`; `pairs = windowed_reference(usable, form10, endpoint_tolerance_m, min_rows_in_window, max_window_m)` with params = `{'endpoint_tolerance_m': 60.0, 'min_rows_in_window': 9, 'max_window_m': 160.0} | comparison.params` (study defaults, spec §3). `len(pairs) < 5` → fail «замало зіставлених пар (N) — перевірте, що ран і еталон покривають ту саму ділянку».
  3. Stats (all from `profilometer_validation.calibrate`; one road → per-comparison honesty):

```python
bias = float((pairs['iri_multi'] - pairs['iri_ref']).mean())
pairs['iri_multi_bias_corrected'] = pairs['iri_multi'] - bias
stats = {
    'n_pairs': int(len(pairs)),
    'validation': {c: validation_stats(pairs, c)
                   for c in ('iri_multi', 'psd_sqrt_scalar', 'grms')},
    'bland_altman_before': bland_altman(pairs, 'iri_multi'),
    'bland_altman_bias_corrected': bland_altman(pairs, 'iri_multi_bias_corrected'),
    'eq3_fit': fit_eq3(pairs),
    'eq6_bias': {'bias': bias,
                 'mae_corrected': validation_stats(pairs, 'iri_multi_bias_corrected')['mae']},
    'effective_n': {c: effective_n(pairs.sort_values('chainage_m')[c])
                    for c in ('iri_ref', 'iri_multi')},
    'influence': influence_on_eq3(pairs),
    'gates': {'r2_min': 0.85, 'mae_max': 0.5,
              'eq3_r2_pass': None, 'eq6_bias_mae_pass': None,   # filled from the numbers
              'note': 'Гейти — індикатори для людини, не автоматичне рішення (spec §3).'},
}
```

  4. Artifacts into `result_dir = settings.storage_results_dir / 'comparisons' / f'cmp{id}_{UTC yyyyMMdd_HHmmss}'`: `matched_pairs.csv` (`float_format='%.10g'`, `lineterminator='\n'`), `stats.json` (`ensure_ascii=False, indent=1, sort_keys=True`), `chart_data.json`, `figures/` via `pairs['road'] = reference.road_name` then `scatter_fit(pairs, stats['eq3_fit'], figures_dir)`, `bland_altman_plot(pairs, 'iri_multi', 'До корекції', figures_dir, 'fig2a_bland_altman_before')`, `bland_altman_plot(pairs, 'iri_multi_bias_corrected', f'Після корекції зсуву ({bias:+.2f} м/км)', figures_dir, 'fig2b_bland_altman_corrected')`, `chainage_overlay(pairs, reference.road_name, figures_dir, calibrated_col='iri_multi_bias_corrected', smartphone_label='Смартфон (корекція зсуву Eq.6)')`.
  5. `chart_data.json` (compact series for the SVG charts):

```python
prof = pairs.sort_values('chainage_m')
chart_data = {
    'scatter': pairs[['seg_id', 'psd_sqrt_scalar', 'iri_ref', 'iri_multi',
                      'chainage_m']].round(6).to_dict('records'),
    'profile': prof[['chainage_m', 'iri_ref', 'iri_multi',
                     'iri_multi_bias_corrected', 'seg_id']].round(6).to_dict('records'),
    'bland_altman': [{'seg_id': int(r.seg_id),
                      'mean': round((r.iri_multi + r.iri_ref) / 2, 6),
                      'diff': round(r.iri_multi - r.iri_ref, 6)}
                     for r in pairs.itertuples()],
    'eq3_fit': {k: stats['eq3_fit'][k] for k in ('A', 'B', 'r2', 'mae', 'n')},
    'bias': bias,
    'gates': stats['gates'],
}
```

  6. `Comparison.summary` (what lists render): `{'n_pairs', 'spearman_rho', 'pearson_r', 'mae', 'bias', 'n_eff' (iri_ref), 'eq3_r2': stats['eq3_fit']['r2'], 'gates': stats['gates']}` — all plain floats (`round(…, 4)`).
- `figures.py` change (backward-compatible):

```python
def chainage_overlay(pairs, road, out_dir, calibrated_col='iri_calibrated',
                     smartphone_label='Смартфон (калібр. Eq.3)') -> list:
    ...
    ax.plot(km, df[calibrated_col], ..., label=smartphone_label)
```

  and `run_study.py` passes `smartphone_label='Смартфон (корекція зсуву Eq.6)'` (fixes a pre-existing label inaccuracy: the study plots the bias-corrected column, not an Eq.3 calibration).

- [ ] **Step 1: Failing test** — synthetic straight road, real matcher end-to-end:

```python
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sqlalchemy.orm import Session


def _make_run_artifacts(result_dir: Path, n_seg=10):
    """10 x 100 m segments heading north along lon=30.5; ~0.000899 deg per 100 m."""
    deg = 100.0 / 111_195.0
    rows, features = [], []
    for i in range(n_seg):
        lat0, lat1 = 50.0 + i * deg, 50.0 + (i + 1) * deg
        rows.append({'seg_id': i, 's_start': i * 100.0, 's_end': (i + 1) * 100.0,
                     'length_m': 100.0, 'grms': 0.5 + 0.02 * i,
                     'psd_sqrt_scalar': 0.010 + 0.001 * i,
                     'iri_psd_raw': 3.0, 'iri_psd': 3.0,
                     'iri_multi': 2.0 + 0.2 * i, 'mean_speed_kmh': 60.0,
                     'partial': False, 'speed_valid': True,
                     'low_speed_class': None, 'needs_class12_survey': False})
        coords = [[30.5, lat0], [30.5, (lat0 + lat1) / 2], [30.5, lat1]]
        features.append({'type': 'Feature', 'properties': {'seg_id': i},
                         'geometry': {'type': 'LineString', 'coordinates': coords}})
    result_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(result_dir / 'road_segments.csv', index=False)
    (result_dir / 'roughness.geojson').write_text(json.dumps(
        {'type': 'FeatureCollection', 'features': features}), encoding='utf-8')


def _make_reference(ref_dir: Path, n10=100):
    deg10 = 10.0 / 111_195.0
    rows = []
    for i in range(n10):
        chain = i * 10
        rows.append({'km_start': chain // 1000, 'm_start': chain % 1000,
                     'km_end': (chain + 10) // 1000, 'm_end': (chain + 10) % 1000,
                     **{f'iri_ch{c}': 2.0 + 0.002 * i for c in range(1, 11)},
                     'lat_start': 50.0 + i * deg10, 'lon_start': 30.5, 'alt_start': 120.0,
                     'lat_end': 50.0 + (i + 1) * deg10, 'lon_end': 30.5, 'alt_end': 120.0})
    ref_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(ref_dir / 'intervals_10m.csv', index=False,
                              encoding='utf-8', lineterminator='\n')


def test_execute_comparison_end_to_end(client, tmp_path):
    import os
    from src.core.config import get_settings
    from src.db.models import AnalysisRun, Comparison, ReferenceDataset, SourceFile
    from src.services.comparison import execute_comparison
    engine = client.app.state.engine
    settings = get_settings()
    with Session(engine) as s:
        f = SourceFile(filename='syn.csv', size_bytes=1); s.add(f); s.commit()
        run = AnalysisRun(file_id=f.id, status='done',
                          result_dir=str(tmp_path / 'run_art'))
        ref = ReferenceDataset(filename='syn.xlsx', road_name='Т-9999', step_m=10.0,
                               intervals_count=100, chainage_span_m=1000.0,
                               bbox=[50.0, 30.4, 50.01, 30.6], parse_warnings=[])
        s.add_all([run, ref]); s.commit()
        _make_run_artifacts(Path(run.result_dir))
        _make_reference(settings.storage_reference_dir / str(ref.id))
        cmp_ = Comparison(run_id=run.id, reference_id=ref.id, params={})
        s.add(cmp_); s.commit(); cmp_id = cmp_.id

    execute_comparison(cmp_id, engine, settings)

    with Session(engine) as s:
        done = s.get(Comparison, cmp_id)
        assert done.status == 'done', done.error
        assert done.summary['n_pairs'] >= 5
        rd = Path(done.result_dir)
        for name in ('matched_pairs.csv', 'stats.json', 'chart_data.json'):
            assert (rd / name).is_file()
        assert list((rd / 'figures').glob('*.png'))
        chart = json.loads((rd / 'chart_data.json').read_text(encoding='utf-8'))
        assert {'scatter', 'profile', 'bland_altman', 'eq3_fit', 'bias'} <= set(chart)


def test_comparison_bbox_mismatch_fails_with_explanation(client, tmp_path):
    from src.core.config import get_settings
    from src.db.models import AnalysisRun, Comparison, ReferenceDataset, SourceFile
    from src.services.comparison import execute_comparison
    engine = client.app.state.engine
    with Session(engine) as s:
        f = SourceFile(filename='syn2.csv', size_bytes=1); s.add(f); s.commit()
        run = AnalysisRun(file_id=f.id, status='done',
                          result_dir=str(tmp_path / 'run2'))
        ref = ReferenceDataset(filename='far.xlsx', road_name='X', step_m=10.0,
                               intervals_count=100, chainage_span_m=1000.0,
                               bbox=[48.0, 20.0, 48.1, 20.1], parse_warnings=[])
        s.add_all([run, ref]); s.commit()
        _make_run_artifacts(Path(run.result_dir))
        _make_reference(get_settings().storage_reference_dir / str(ref.id))
        cmp_ = Comparison(run_id=run.id, reference_id=ref.id, params={})
        s.add(cmp_); s.commit(); cmp_id = cmp_.id
    execute_comparison(cmp_id, engine, get_settings())
    with Session(engine) as s:
        failed = s.get(Comparison, cmp_id)
        assert failed.status == 'failed' and 'перетинаються' in failed.error
```

- [ ] **Step 2:** Run → fails. Implement `execute_comparison` + the `figures.py` label param + the `run_study.py` call-site fix.
- [ ] **Step 3:** Backend suite green; study suite still green: `.venv/Scripts/python.exe -m pytest studies/profilometer_validation/tests -q` (21).
- [ ] **Step 4:** Commit `feat(web-admin): runtime run-vs-reference comparison job with stats, figures and chart data`.

### Task 7: Comparisons API + run artifact list

**Files:**
- Create: `web_admin/backend/src/api/comparisons.py`
- Modify: `web_admin/backend/src/api/schemas.py` (`ComparisonCreate`, `ComparisonOut`), `web_admin/backend/src/api/runs.py` (add `GET /{run_id}/artifact-list`), `web_admin/backend/src/main.py`
- Test: `web_admin/backend/tests/test_comparisons_api.py`

**Interfaces:**
- Produces:
  - `ComparisonCreate`: `run_id: int`, `reference_id: int`, `params: dict = {}`.
  - `ComparisonOut` (`from_attributes`): `id, run_id, reference_id, created_at, status, params, result_dir, summary, error` + enriched `run_filename: str|None`, `reference_road: str|None`.
  - Router `prefix='/comparisons'`:
    - `POST ''` → 201; fast-fail validations before queueing: run exists (404) and `status=='done'` (409 «ран ще не завершено»), reference exists (404), not deleted and `step_m==10` (409). Submits `execute_comparison` to `app.state.queue` exactly like `_create_and_submit` does.
    - `GET ''` (`?run_id=` optional filter) newest first; `GET '/{id}'`; `DELETE '/{id}'` → 204 removing `result_dir` (rmtree).
    - `GET '/{id}/artifacts/{name:path}'` — copy the traversal guard from `runs.get_artifact` verbatim (`resolve()` + `is_relative_to`).
  - `GET /api/runs/{run_id}/artifact-list` → `[{'name': <posix relpath>, 'size_bytes': int}]`, sorted by name, recursive over `result_dir` (404 when no artifacts yet).

- [ ] **Step 1: Failing tests** (reuse `_make_run_artifacts`/`_make_reference` — move them into `tests/conftest.py` in this task and import from both test modules):

```python
def test_comparison_flow_and_artifacts(client, tmp_path):
    # arrange run(done)+reference via conftest helpers (same as service test)
    r = client.post('/api/comparisons', json={'run_id': run_id, 'reference_id': ref_id})
    assert r.status_code == 201
    cmp_id = r.json()['id']
    done = client.get(f'/api/comparisons/{cmp_id}').json()   # RQA_QUEUE_INLINE=1 -> already done
    assert done['status'] == 'done' and done['summary']['n_pairs'] >= 5
    assert done['reference_road'] == 'Т-9999'
    listing = client.get(f'/api/comparisons?run_id={run_id}').json()
    assert [c['id'] for c in listing] == [cmp_id]
    stats = client.get(f'/api/comparisons/{cmp_id}/artifacts/stats.json')
    assert stats.status_code == 200
    assert client.get(f'/api/comparisons/{cmp_id}/artifacts/../secret').status_code in (403, 404)


def test_comparison_create_validations(client, ...):
    assert client.post('/api/comparisons', json={'run_id': 9999, 'reference_id': ref_id}).status_code == 404
    # run with status='queued' -> 409; reference step_m=100 -> 409


def test_run_artifact_list(client, ...):
    rows = client.get(f'/api/runs/{run_id}/artifact-list').json()
    names = {r['name'] for r in rows}
    assert 'road_segments.csv' in names and 'roughness.geojson' in names
    assert all(r['size_bytes'] > 0 for r in rows)
```

Write these as complete tests using the conftest helpers (the fragments above fix the assertions; arrange-code mirrors Task 6's test).
- [ ] **Step 2:** Run → fails. Implement router + artifact-list; wire `comparisons` router in `main.py`.
- [ ] **Step 3:** Suite green. Commit `feat(web-admin): comparisons API and run artifact listing`.

### Task 8: CoefficientSet API — draft, confirm (archives previous), archive, reanalyze

**Files:**
- Create: `web_admin/backend/src/api/coefficient_sets.py`
- Modify: `web_admin/backend/src/api/schemas.py`, `web_admin/backend/src/main.py`
- Test: `web_admin/backend/tests/test_coefficient_sets_api.py`

**Interfaces:**
- Produces schemas (note: a field literally named `model` is fine in Pydantic v2; if a `model_` protected-namespace warning appears, silence it with `model_config = ConfigDict(protected_namespaces=())` on that class):
  - `CoefficientSetCreate`: `comparison_id: int`, `model: str` (validated ∈ {'eq3','eq6_bias'} → 422), `name: str`, `vehicle_type: str`, `phone_model: str|None = None`.
  - `CoefficientSetOut` (`from_attributes`): all model fields + `comparison_id`.
  - `ConfirmIn`: `note: str|None = None`. `ConfirmOut`: `set: CoefficientSetOut`, `archived_set_id: int|None`, `reanalyze_candidates: int`.
- Router `prefix='/coefficient-sets'`:
  - `POST ''` → 201 draft. Pulls params from the comparison's `stats.json`: eq3 → `{'A': stats['eq3_fit']['A'], 'B': stats['eq3_fit']['B']}`; eq6_bias → `{'bias': stats['eq6_bias']['bias']}`. `stats_snapshot` = `{'r2': eq3_fit.r2, 'mae': validation.iri_multi.mae, 'spearman_rho': validation.iri_multi.spearman_rho, 'n_pairs': n_pairs, 'mae_bias_corrected': eq6_bias.mae_corrected}`. 404 unknown comparison, 409 not `done`, 409 duplicate name.
  - `GET ''` → all sets newest first.
  - `POST '/{id}/confirm'` → `ConfirmOut`. Only from `draft` (409 otherwise). Archives the previous `confirmed` of the same `(model, vehicle_type, phone_model)` key (NULL-safe comparison: use `.is_(None)` when `phone_model is None`). `reanalyze_candidates` = count of non-deleted `SourceFile`s whose `recording_meta.vehicle.vehicle_type == set.vehicle_type` (filter in Python — small N).
  - `POST '/{id}/archive'` → 200 `CoefficientSetOut` (from any status except already archived → 409).
  - `POST '/{id}/reanalyze'` → `list[RunOut]`: for each candidate file (same filter as above) create + queue a NEW run via the shared helper (`from src.api.runs import _create_and_submit`) with `params={}` — the new runs resolve the freshly confirmed set naturally; old runs stay untouched (spec §4). Only for `confirmed` sets (409 otherwise).

- [ ] **Step 1: Failing tests:**

```python
def test_draft_from_comparison_and_invariant(client, ...):
    # arrange a done comparison (conftest helpers), then:
    r = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': 'van_v1',
        'vehicle_type': 'van'})
    assert r.status_code == 201 and r.json()['status'] == 'draft'
    assert 'bias' in r.json()['params']
    r2 = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': 'van_v2',
        'vehicle_type': 'van'})
    c1 = client.post(f"/api/coefficient-sets/{r.json()['id']}/confirm", json={'note': 'перший'})
    assert c1.status_code == 200 and c1.json()['archived_set_id'] is None
    c2 = client.post(f"/api/coefficient-sets/{r2.json()['id']}/confirm", json={})
    assert c2.json()['archived_set_id'] == r.json()['id']
    sets = {s['name']: s['status'] for s in client.get('/api/coefficient-sets').json()}
    assert sets == {'van_v1': 'archived', 'van_v2': 'confirmed'}


def test_confirm_only_from_draft_and_duplicate_name(client, ...):
    # confirm an archived set -> 409; POST with existing name -> 409; model='bogus' -> 422


def test_reanalyze_creates_new_runs_with_new_set(client, monkeypatch, ...):
    # arrange: van file uploaded (fake_analyze stub from Task 5 pattern), old done run,
    # confirmed eq6_bias set for 'van'
    runs = client.post(f'/api/coefficient-sets/{set_id}/reanalyze').json()
    assert len(runs) == 1
    assert runs[0]['params']['coefficients']['eq6_bias']['set_id'] == set_id
    all_runs = client.get(f'/api/runs?file_id={file_id}').json()
    assert len(all_runs) == 2      # old run untouched, new run added
```

Write complete arrange-code from the Task 5/6 conftest patterns.
- [ ] **Step 2:** Run → fails; implement router; wire in `main.py`.
- [ ] **Step 3:** Suite green. Commit `feat(web-admin): coefficient sets with draft->confirm->archive workflow and reanalysis`.

### Task 9: Frontend DTOs + ApiService extensions

**Files:**
- Modify: `web_admin/frontend/src/app/api/dto.ts`, `web_admin/frontend/src/app/api/api.service.ts`
- Test: `web_admin/frontend/src/app/api/api.service.spec.ts` (extend)

**Interfaces:**
- `dto.ts` additions (mirror `schemas.py` verbatim):

```ts
export interface ReferenceOut {
  id: number; filename: string; uploaded_at: string; road_name: string;
  direction: string | null; lane: number | null; category: number | null;
  step_m: number; measured_at: string | null; intervals_count: number;
  chainage_span_m: number; bbox: number[] | null; parse_warnings: string[];
  source_deleted: boolean; comparisons_count: number;
}

export interface ComparisonSummary {
  n_pairs: number; spearman_rho: number; pearson_r: number; mae: number;
  bias: number; n_eff: number; eq3_r2: number;
  gates: Record<string, unknown>;
}

export interface ComparisonOut {
  id: number; run_id: number; reference_id: number;
  run_filename: string | null; reference_road: string | null;
  created_at: string; status: 'queued' | 'running' | 'done' | 'failed';
  params: Record<string, number>; result_dir: string | null;
  summary: ComparisonSummary | null; error: string | null;
}

export interface CoefficientSetOut {
  id: number; name: string; model: 'eq3' | 'eq6_bias';
  params: { A?: number; B?: number; bias?: number };
  vehicle_type: string | null; phone_model: string | null;
  status: 'draft' | 'confirmed' | 'archived'; comparison_id: number | null;
  stats_snapshot: Record<string, number> | null;
  created_at: string; confirmed_at: string | null; confirmed_note: string | null;
}

export interface ConfirmOut {
  set: CoefficientSetOut; archived_set_id: number | null; reanalyze_candidates: number;
}

export interface ArtifactEntry { name: string; size_bytes: number; }

export interface CoefficientSnapshot {
  set_id: number; name: string; params: { A?: number; B?: number; bias?: number };
}
export interface RunCoefficients {
  eq3: CoefficientSnapshot | null; eq6_bias: CoefficientSnapshot | null;
}

export interface ChartScatterPoint { seg_id: number; psd_sqrt_scalar: number;
  iri_ref: number; iri_multi: number; chainage_m: number; }
export interface ChartProfilePoint { chainage_m: number; iri_ref: number;
  iri_multi: number; iri_multi_bias_corrected: number; seg_id: number; }
export interface ChartBAPoint { seg_id: number; mean: number; diff: number; }
export interface ChartData {
  scatter: ChartScatterPoint[]; profile: ChartProfilePoint[];
  bland_altman: ChartBAPoint[];
  eq3_fit: { A: number; B: number; r2: number; mae: number; n: number };
  bias: number; gates: Record<string, unknown>;
}
```

  Also extend `RunOut['params']` type to `{ low_speed_policy?: string; coefficients?: RunCoefficients }`, `RunSummary` with `coefficients?: RunCoefficients | null; mean_iri_multi_corrected?: number | null`, and `SegmentRow` with `iri_multi_corrected?: number | null`.
- `api.service.ts` additions (all through the `/api` base):

```ts
listReferences(): Observable<ReferenceOut[]>
uploadReference(file: File, measuredAt?: string): Observable<ReferenceOut>  // FormData: file (+ measured_at when set)
deleteReference(id: number): Observable<void>
createComparison(runId: number, referenceId: number): Observable<ComparisonOut>
listComparisons(runId?: number): Observable<ComparisonOut[]>
getComparison(id: number): Observable<ComparisonOut>
deleteComparison(id: number): Observable<void>
comparisonArtifactUrl(id: number, name: string): string        // `${base}/comparisons/${id}/artifacts/${name}`
getComparisonChartData(id: number): Observable<ChartData>      // GET artifacts/chart_data.json
listCoefficientSets(): Observable<CoefficientSetOut[]>
createCoefficientSet(payload: {comparison_id: number; model: string; name: string;
                               vehicle_type: string; phone_model?: string | null}): Observable<CoefficientSetOut>
confirmCoefficientSet(id: number, note?: string): Observable<ConfirmOut>
archiveCoefficientSet(id: number): Observable<CoefficientSetOut>
reanalyzeCoefficientSet(id: number): Observable<RunOut[]>
listRunArtifacts(runId: number): Observable<ArtifactEntry[]>
```

- [ ] **Step 1:** Extend `api.service.spec.ts` with HttpTestingController expectations for `uploadReference` (FormData + measured_at), `confirmCoefficientSet` (POST body `{note}`), `listComparisons(5)` (query `?run_id=5`) — follow the existing spec file's pattern exactly.
- [ ] **Step 2:** `npx ng test --watch=false` → new specs fail → implement → green.
- [ ] **Step 3:** Commit `feat(web-admin-ui): phase-3 DTOs and API client methods`.

### Task 10: Shared SegmentMap component — contrast palette, casing, one map everywhere

The two user feedback items: (1) segments hard to see → higher-chroma palette + thicker lines + theme-inverse casing; (2) the run page must show the SAME Leaflet map as the global map (folium iframe goes away; the folium html stays available as an artifact).

**Palette (validated with the dataviz six-checks validator):** `#00a63e` (<2.5), `#f5c400` (2.5–4), `#ff7300` (4–6), `#d81e2c` (≥6), `#FF00FF` class-1/2 (data contract, unchanged), `#8b93a3` no-data. Worst adjacent-pair CVD ΔE 12.3 (target ≥8), normal-vision floor 16.9 (≥15) — PASS. The yellow's weak contrast on light tiles is compensated by the casing (the validator's required "relief"): every line is drawn twice — casing weight 10 in the theme-inverse color (`rgba(15,18,25,0.85)` on light tiles, `rgba(245,245,244,0.9)` on dark), data line weight 6 on top. These hexes are a data-visualization contract like the magenta — they live in the component, not in theme tokens.

**Files:**
- Create: `web_admin/frontend/src/app/shared/segment-map.ts`, `web_admin/frontend/src/app/shared/segment-map.spec.ts`
- Modify: `web_admin/frontend/src/app/map/global-map-page.ts|html|css` (use the component; KPI panel and rebuild button stay in the page), `web_admin/frontend/src/app/runs/run-detail.ts|html|css` (replace the folium iframe)

**Interfaces:**
- Produces (single-file component, template inline or colocated css — follow the shared/ components' existing style):

```ts
/** IRI_multi severity scale — data contract shared by all maps (incl. #FF00FF class-1/2). */
export function segmentColor(props: Record<string, unknown>): string {
  if (props['needs_class12_survey']) return '#FF00FF';
  const iri = props['iri_multi'];
  if (typeof iri !== 'number') return '#8b93a3';
  if (iri < 2.5) return '#00a63e';
  if (iri < 4) return '#f5c400';
  if (iri < 6) return '#ff7300';
  return '#d81e2c';
}

@Component({ selector: 'app-segment-map', ... })
export class SegmentMap {
  readonly data = input<GeoJsonFeatureCollection | null>(null);
  readonly showRunLink = input(false);        // global map: popup links to the run
  readonly runClick = output<number>();
  // internals: Leaflet map init in afterNextRender, CARTO dark/light tiles following
  // ThemeService (same TILES/TILE_ATTR as today), TWO L.geoJSON layers per render:
  //   casing: { color: theme==='dark' ? 'rgba(245,245,244,0.9)' : 'rgba(15,18,25,0.85)',
  //             weight: 10, opacity: 1 }
  //   line:   { color: segmentColor(props), weight: 6, opacity: 0.95 }
  // hover raises the line to weight 9; popups: filename/seg/IRI (+ run link when
  // showRunLink, emitting runClick like today's popupopen handler);
  // fitBounds on first data render; effect() re-renders casing+tiles on theme flip.
}
```

  - The legend moves INTO the component (bottom-right overlay, tokens for surface/ink): 4 IRI classes + «Потребує обстеження профілометром (клас 1/2)» magenta + no-data gray — take the current legend markup/labels from `global-map-page.html` as the base.
- Consumes: `ThemeService`, `GeoJsonFeatureCollection`.

- [ ] **Step 1: Failing spec** (`segment-map.spec.ts`): unit-test `segmentColor` — thresholds 2.4→`#00a63e`, 2.5→`#f5c400`, 4→`#ff7300`, 6→`#d81e2c`, `needs_class12_survey`→`#FF00FF` wins over any iri, non-number→`#8b93a3`; component spec: renders host element + legend with 6 entries (stub ThemeService as `{ theme: signal('dark') }`, Leaflet works in jsdom? — if `L.map` fails under vitest, guard map init behind `typeof window !== 'undefined' && !('__vitest__' in globalThis)`… do NOT fight jsdom: assert legend DOM only, and keep map init in `afterNextRender` which vitest never fires without a real layout — read `global-map-page` spec-lessons if any exist first).
- [ ] **Step 2:** Implement the component. Then refactor `global-map-page`: delete its own Leaflet/`segmentColor` code, keep KPI/rebuild/empty-state; template embeds `<app-segment-map [data]="fc()" [showRunLink]="true" (runClick)="goToRun($event)" />`; page holds `fc = signal<GeoJsonFeatureCollection|null>(null)` fed by `getGlobalMap()`/`rebuildGlobalMap()`.
- [ ] **Step 3:** Run page: in `run-detail.ts` replace `mapUrl`/iframe with `mapData = signal<GeoJsonFeatureCollection | null>(null)`; in `loadResults()` fetch `getArtifactText(runId, 'roughness.geojson')` → `JSON.parse` → set. Template: `<app-segment-map [data]="mapData()" />` in place of the iframe (folium `segments_map.html` remains reachable from the artifacts list, Task 11).
- [ ] **Step 4:** `npx ng test --watch=false` green; `npx ng build` clean.
- [ ] **Step 5:** Visual sanity: `uvicorn src.main:app` (from `web_admin/backend`, venv) + `npx ng serve --proxy-config proxy.conf.json`; open `/map` in both themes — casing visible, colors distinct; run page shows the unified map. (The admin DB already has 3 done field runs.)
- [ ] **Step 6:** Commit `feat(web-admin-ui): shared SegmentMap with contrast palette and casing; unified run-page map`.

### Task 11: Run page additions — coefficient chip, artifacts list, comparisons block, corrected IRI

**Files:**
- Modify: `web_admin/frontend/src/app/runs/run-detail.ts|html|css`, `web_admin/frontend/src/app/runs/run-detail.spec.ts`

**Interfaces:**
- Consumes: `listRunArtifacts`, `listComparisons(runId)`, `RunCoefficients`, `SegmentRow.iri_multi_corrected`.

- [ ] **Step 1: Failing specs** (extend `run-detail.spec.ts`, stub ApiService with `of()` fixtures):
  - run with `params.coefficients.eq6_bias` renders a chip with the set name; run without → chip «Книжкові константи».
  - artifacts fixture `[{name:'report.md',size_bytes:10},{name:'figures/f.png',size_bytes:20}]` renders 2 rows with human-readable sizes.
  - segments fixture with `iri_multi_corrected` renders the extra column; without it the column is absent.
- [ ] **Step 2:** Implement:
  - Header chip block: `@if (run()?.params?.coefficients; as c)` → for each non-null of `c.eq3`/`c.eq6_bias` a chip `title="{{model}}: {{name}}"` showing `name` (+ params inline: `A/B` or `bias`); else a muted chip «Книжкові константи». Style with `--chip-radius`, `--color-muted`, `--color-accent-muted` tokens.
  - «Всі артефакти» section (after the plots): table name → link `artifactUrl(name)` (target `_blank`), size formatted KB/MB; loaded in `loadResults()` via `listRunArtifacts`.
  - «Порівняння з профілометром» section: visible when `comparisons().length > 0`; rows: reference_road, status badge, `ρ`, `MAE`, link `routerLink="/calibration/comparisons/{{c.id}}"`; loaded via `listComparisons(this.runId)`.
  - Segments table: add column «IRI кориг.» only when any row has `iri_multi_corrected != null`; cell renders `row.iri_multi_corrected?.toFixed(2) ?? '—'` — the low-speed label logic for `iri_multi` stays untouched.
- [ ] **Step 3:** Tests green; build clean. Commit `feat(web-admin-ui): run page coefficient chip, artifact list, comparisons block`.

### Task 12: «Калібрування» tab — references, comparisons list, coefficient sets + confirm workflow

**Files:**
- Create: `web_admin/frontend/src/app/calibration/calibration-page.ts|html|css`, `web_admin/frontend/src/app/calibration/calibration-page.spec.ts`
- Modify: `web_admin/frontend/src/app/app.routes.ts` (route `calibration`), `web_admin/frontend/src/app/app.html` (nav link «Калібрування» after «Глобальна мапа»)

**Interfaces:**
- Produces: `CalibrationPage` with three sections (cards, same visual language as files/runs pages):
  1. **Еталони профілометра** — upload row (file input `.xlsx` + date input «Дата вимірювання (ручне поле)» + button «Завантажити»; on 422 show the backend detail in an error banner); table: дорога, крок, інтервалів, пікетаж (span km), дата вимірювання, попередження (count with title tooltip), delete button (confirm dialog — reuse the pattern/styles of the existing delete dialogs in files-page).
  2. **Порівняння** — «Нове порівняння» opens a dialog: select run (done runs only, label `#id — filename`) × select reference (step 10, not deleted) → `createComparison`; table: id, ран, еталон, статус badge (queued/running/done/failed + error title), ρ / MAE / bias from summary, link «Відкрити» → `/calibration/comparisons/:id`, delete. Poll `listComparisons()` every 2 s while any is queued/running (same pattern as runs-page).
  3. **Набори коефіцієнтів** — table: name, model, vehicle_type, phone_model (`—` when null), status badge (draft/confirmed/archived), params inline (`A=…, B=…` / `bias=…`), метрики зі snapshot (ρ, MAE), provenance link «порівняння #N» → detail page, buttons: «Підтвердити» (draft only) / «Архівувати» (confirmed only).
  - **Confirm dialog** (spec §4): textarea «Нотатка підтвердження», text «Підтвердження активує набір лише для майбутніх ранів; попередній confirmed того ж ключа буде архівовано.»; on success, when `reanalyze_candidates > 0` → second dialog «Перерахувати {{n}} наявних ранів (vehicle_type={{vt}})? Старі рани лишаться недоторканими.» → `reanalyzeCoefficientSet` → success note «Створено N нових ранів» with link to /runs + hint «після завершення перебудуйте глобальну мапу».
- Routes: `{ path: 'calibration', loadComponent: ... }` (detail route comes in Task 13).

- [ ] **Step 1: Failing specs** (`calibration-page.spec.ts`, ApiService stubbed):
  - renders the three section headings («Еталони профілометра», «Порівняння», «Набори коефіцієнтів»).
  - confirm flow: click «Підтвердити» on a draft-set row → dialog appears → enter note, submit → spy `confirmCoefficientSet(id, 'note')` called; stub returns `reanalyze_candidates: 2` → reanalyze dialog appears with «2» in its text; submit → `reanalyzeCoefficientSet` called.
  - a reference row with `parse_warnings.length===2` shows «2 попередж.».
- [ ] **Step 2:** Implement page + dialogs + polling; nav link; route. All colors/spaces via tokens; status badges reuse the runs-page badge classes (extract to a shared css class only if runs-page already exposes one — otherwise copy the 4-line style).
- [ ] **Step 3:** Tests green; build clean. Commit `feat(web-admin-ui): calibration tab with references, comparisons and coefficient-set workflow`.

### Task 13: Comparison detail page with interactive SVG charts

**Files:**
- Create: `web_admin/frontend/src/app/shared/charts/scatter-chart.ts`, `web_admin/frontend/src/app/shared/charts/profile-chart.ts`, `web_admin/frontend/src/app/shared/charts/ba-chart.ts`, `web_admin/frontend/src/app/shared/charts/chart-scale.ts`, `web_admin/frontend/src/app/shared/charts/charts.spec.ts`, `web_admin/frontend/src/app/calibration/comparison-detail.ts|html|css`, `web_admin/frontend/src/app/calibration/comparison-detail.spec.ts`
- Modify: `web_admin/frontend/src/app/app.routes.ts` (route `calibration/comparisons/:id`)

**Interfaces:**
- `chart-scale.ts` — tiny pure helpers shared by the three charts (unit-testable without DOM):

```ts
export interface Scale { domain: [number, number]; range: [number, number]; }
export function linearScale(domain: [number, number], range: [number, number]) {
  const [d0, d1] = domain, [r0, r1] = range, k = (r1 - r0) / (d1 - d0 || 1);
  return (v: number) => r0 + (v - d0) * k;
}
export function niceTicks(min: number, max: number, count = 5): number[] { ... }  // 1-2-5 stepping
```

- Chart components — all: standalone, inline SVG via template, `viewBox="0 0 640 400"` + `width:100%`, margins {t:16,r:16,b:40,l:48}, grid lines `stroke: var(--color-border)`, axis text `fill: var(--color-muted-fg); font-size: 11px`, series colors: smartphone `var(--color-accent)`, reference `var(--ink)`, corrected `var(--color-success)`; dots r=4 (hover r=6), lines stroke-width 2; every chart has a legend row above (color swatch + label, text in ink tokens); tooltips = absolutely-positioned div fed by signals (`--color-surface-raised` bg, `--shadow-e2`); no animations (charts are static SVG; honors reduced-motion by construction).
  - `ScatterChart`: `points = input<ChartScatterPoint[]>([])`, `fit = input<{A,B}|null>(null)`, `selectedSegId = input<number|null>(null)`, `segClick = output<number>()`. x=`psd_sqrt_scalar` (label «√PSD, g/√Гц (0.5–6 Гц)»), y=`iri_ref` («IRI профілометра, м/км»). Fit line drawn across the x-domain. Hover: nearest point within 14 px → tooltip `сегмент N: √PSD…, IRI_ref…`; click emits `segClick`. Zoom: `(wheel)` handler scales the x/y domains around the cursor (clamped to data extent, factor 1.2), `(dblclick)` resets — domains are signals, everything re-computes.
  - `ProfileChart`: `points = input<ChartProfilePoint[]>([])`, `range = output<[number, number] | null>()` (brush). Three lines: iri_ref (ink), iri_multi (accent), iri_multi_bias_corrected (success, dashed `stroke-dasharray="6 4"`); x=chainage km. Crosshair + tooltip with all three values at nearest chainage. Brush: pointerdown-move-up draws a `rect` (`fill: var(--color-accent-muted); opacity:.35`); on pointerup emits the chainage range (null when width < 5 px = click-clear).
  - `BaChart`: `points = input<ChartBAPoint[]>([])`, `bias = input(0)`, `loa = input<[number, number]>([0,0])`. Dots mean vs diff; solid bias line + two dashed LoA lines, right-edge labels («зсув», «±1.96σ»). Per-dot tooltip.
- `ComparisonDetail` page: loads `getComparison(id)` + `getComparisonChartData(id)`; failed → error banner with `error`; done →
  - KPI row (reuse the dashboard card/CountUp pattern): ρ, r (Pearson), MAE, зсув, n, n_eff.
  - Gates indicators: two chips «R² {{r2}} {{pass ? '≥' : '<'}} 0.85» (success/warn token bg) + «MAE …  0.5», caption «Індикатори, не автоматичне рішення».
  - Charts: scatter (+fit), profile (+brush), BA (bias/loa from `chart.bias` and stats via `bland_altman_before` — include `loa_low/loa_high` in `ComparisonSummary`? No: compute in-page from chart_data: `sd = std(diff)`, `loa = bias ± 1.96·sd` — 3 lines of TS, keep the DTO thin).
  - «Формули» card (plain HTML, no KaTeX): `IRI = A·√PSD + B` with substituted `A`/`B` from `eq3_fit` (`<i>IRI</i> = 146.23·√PSD − 1.87`, `<sub>/<sup>` typography) and `IRI_кориг = IRI_multi − ({{bias}})`.
  - Buttons «PNG» / «PDF» per figure: plain `<a target="_blank">` to `comparisonArtifactUrl(id, 'figures/fig1_scatter_eq3_fit.png')` etc. (4 figures × 2 formats, compact link row).
  - Pairs table (from `chart.scatter` joined with profile rows by seg_id): seg_id, chainage (km, 2 dec), iri_ref, iri_multi, різниця; sorted by |різниця| desc; top-10% |diff| rows get `background: var(--color-warn-bg)`; brush range from ProfileChart filters the rows (signal); scatter `segClick`/row click sync `selectedSegId` (row highlight + enlarged scatter dot).
  - «Створити набір коефіцієнтів» button → dialog: model radio (`eq6_bias` recommended default, `eq3`), name input (default `{{model}}_{{vehicle_type}}_{{yyyy-MM-dd}}`), vehicle_type + phone_model inputs prefilled from the run's file `recording_meta` (fetch the run, then its file via `listFiles()`? — no: `getRun(run_id)` gives `summary.vehicle_type`; phone_model leave empty input with placeholder) → `createCoefficientSet` → success banner with link to the calibration tab.
- Route: `calibration/comparisons/:id` → `ComparisonDetail`.

- [ ] **Step 1: Failing specs:**
  - `charts.spec.ts`: `linearScale` maps domain→range; `niceTicks(0, 9.7)` returns 1-2-5-stepped ticks within bounds; `ScatterChart` with a 3-point fixture renders 3 `circle`s and 1 fit `line`; click on a circle emits `segClick` with its seg_id; `ProfileChart` fixture renders 3 `path`s; `BaChart` renders bias line + 2 dashed lines.
  - `comparison-detail.spec.ts`: with stubbed done comparison + `ChartData` fixture: KPI row shows ρ value; gates chips render; pairs table sorted by |diff| desc; create-set dialog calls `createCoefficientSet` with the chosen model.
- [ ] **Step 2:** Implement (scale helpers → charts → page). Keep each chart under ~180 lines; no external deps.
- [ ] **Step 3:** Tests green; build clean; visual check on a real comparison: create one via the UI against an uploaded real form (`storage/field_measurements/sample_official_measurements/Т1016_км17-км0+200зворотній_10.xlsx`) and the T1016 run (id 2 or 3 in admin.db) — expect ρ ≈ 0.94, n ≈ 164 (the study's numbers) — this is the live cross-check that the runtime pipeline reproduces the study.
- [ ] **Step 4:** Commit `feat(web-admin-ui): comparison detail with interactive SVG charts and set creation`.

### Task 14: Docs, rules, full regression, hidden-char scan

**Files:**
- Modify: `docs/08_*.md` (web-admin doc — read `docs/` index first for the exact name), `docs/00_*.md` (overview: Phase 3 status), `web_admin/README.md` (run instructions + new env var + editable install of `profilometer_validation`), `.claude/rules/web-admin-backend.md`, `.claude/rules/web-admin-frontend.md`

- [ ] **Step 1:** Docs (Ukrainian prose, English code samples): Phase-3 section — сутності, резолюція коефіцієнтів (3 рівні, snapshot у рані), воркфлоу confirm/archive/reanalyze, порівняння (артефакти result_dir), формат `chart_data.json`, нова палітра мапи (hex values + casing rationale + magenta contract), `RQA_REFERENCE_DIR`.
- [ ] **Step 2:** Rules updates: backend — «Reference intervals are stored as derived CSV consumed by `profilometer_validation.match.load_form_10m`; comparison artifacts under `storage/results/comparisons/`; coefficient resolution only via `src/services/coefficients.resolve_for_meta`; book constants never in DB»; frontend — «All maps render through `shared/segment-map.ts`; the IRI severity palette + #FF00FF live there as a data contract; SVG charts only (no chart libs)».
- [ ] **Step 3:** Full regression from repo root:
  - `.venv/Scripts/python.exe -m pytest analyzer/tests -q` → 181
  - `.venv/Scripts/python.exe -m pytest studies/profilometer_validation/tests -q` → 21
  - `cd web_admin/backend && ../../.venv/Scripts/python.exe -m pytest -q` → 25 + all new
  - `cd web_admin/frontend && npx ng test --watch=false && npx ng build`
  - E2E analyzer sanity: `.venv/Scripts/python.exe -m road_quality_analyzer analyze --input storage/data/sensor_data_20250729_163334.csv --out <scratchpad>/e2e` → 152 segments, 19 low-speed.
- [ ] **Step 4:** Hidden-character scan over every file this plan touched (the project's established scan: check for zero-width/invisible Unicode in changed files via `git diff --name-only <base>` + a Python scan of U+200B..U+200F, U+202A..U+202E, U+2060..U+2064, U+FEFF; Cyrillic is fine).
- [ ] **Step 5:** Commit `docs(web-admin): phase-3 calibration documentation and rules`.

---

## Self-review notes

- **Spec coverage:** §1 entities → Task 2 (single-FK deviation documented up top); §2 resolution → Task 5; §3 comparison job incl. gates-as-indicators and one-click draft → Tasks 6–8, 13; §4 confirm workflow + reanalysis dialog → Tasks 8, 12; §5 frontend tab, SVG charts, run-page artifacts/comparisons → Tasks 9–13; §6 boundaries respected (no book constants in DB, no auto-confirm, no form editing, no eq3 refit UI beyond draft creation); §7 test matrix → distributed per task (resolution fallback, invariant, workflow states, xlsx parse, comparison job stub+synthetic, integration confirm→new-run; frontend chip/confirm-dialog/scatter fixtures); §8 order followed. User map feedback items 1–2 → Task 10.
- **Known judgment calls for the reviewer:** two FKs instead of one (documented); comparison requires a 10 m form (windowed matcher needs the 10 m profile — nearest-100 fallback deliberately not built, YAGNI); eq6 bias correction applied in API responses + summary, analyzer artifacts never mutated; `measured_at` stored as plain ISO string (manual field, no tz semantics needed).
