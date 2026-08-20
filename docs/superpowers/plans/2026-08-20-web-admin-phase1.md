# Web Admin (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local web admin managing the full analysis cycle — upload CSVs, queue `analyze()` runs, browse artifacts/reports, global Leaflet map, dashboard — per the approved spec.

**Architecture:** FastAPI + SQLAlchemy + SQLite backend under `web_admin/backend`, importing `road_quality_analyzer` as a library (in-process `analyze()`, `ThreadPoolExecutor(max_workers=1)` queue). Angular 22 standalone frontend under `web_admin/frontend` talking to `/api` via dev proxy. DB stores metadata only; artifacts stay on disk in `storage/results/`.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0, SQLite, pytest + httpx TestClient; Angular 22 (standalone, OnPush default, signals, `httpResource`), Leaflet, marked.

**Spec:** `docs/superpowers/specs/2026-08-19-web-admin-design.md` (incl. Stage D update)

## Global Constraints

- Branch `v1-1-stage`; no `Co-Authored-By`; no hidden/invisible characters; code/commits in English, UI copy Ukrainian.
- Analyzer package is NOT modified; its suite (177) is an independent regression contour.
- No auth, no Celery/Redis, no Docker (spec §11). SQLite file `web_admin/backend/admin.db` is gitignored.
- No numeric IRI for low-speed segments anywhere in the UI (analyzer invariant extends to admin).
- Deleting a file keeps its runs (`source_deleted=true`); deleting a run removes its artifacts dir.
- Vehicle/metadata parsing reuses `road_quality_analyzer.io.parse_recording_metadata` — no duplicate parser.
- Result dirs: `storage/results/<csv-stem>__run<N>_<UTC yyyyMMdd_HHmmss>/`.

---

### Task 1: Backend scaffold, config, health endpoint

**Files:**
- Create: `web_admin/backend/requirements.txt`, `web_admin/backend/src/__init__.py`, `web_admin/backend/src/core/__init__.py`, `web_admin/backend/src/core/config.py`, `web_admin/backend/src/main.py`, `web_admin/backend/tests/__init__.py`, `web_admin/backend/tests/conftest.py`, `web_admin/backend/pytest.ini`
- Modify: `.gitignore` (add `web_admin/backend/admin.db`, `web_admin/frontend/node_modules/`, `web_admin/frontend/dist/`)

**Interfaces:**
- Produces: `Settings` dataclass — `storage_data_dir: Path`, `storage_results_dir: Path`, `db_url: str`; `get_settings()` cached factory reading env overrides `RQA_DATA_DIR`, `RQA_RESULTS_DIR`, `RQA_DB_URL` (tests point these at tmp dirs); `create_app() -> FastAPI` app factory mounting routers under `/api`, CORS for `http://localhost:4200`.

- [ ] **Step 1:** `pip install fastapi uvicorn[standard] sqlalchemy python-multipart httpx sse-starlette` into `.venv`; freeze exact versions into `web_admin/backend/requirements.txt` (only these packages + deps comment).
- [ ] **Step 2: Failing test** `tests/test_app.py`:

```python
def test_health(client):
    r = client.get('/api/health')
    assert r.status_code == 200 and r.json() == {'status': 'ok'}

def test_settings_env_override(tmp_path, monkeypatch):
    from src.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv('RQA_DATA_DIR', str(tmp_path / 'd'))
    s = get_settings()
    assert s.storage_data_dir == tmp_path / 'd'
    get_settings.cache_clear()
```

`conftest.py` builds the app with tmp dirs:

```python
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('RQA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('RQA_RESULTS_DIR', str(tmp_path / 'results'))
    monkeypatch.setenv('RQA_DB_URL', f"sqlite:///{tmp_path / 'admin.db'}")
    from src.core.config import get_settings
    get_settings.cache_clear()
    from src.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
```

`pytest.ini`: `[pytest]` + `pythonpath = .` + `testpaths = tests` (run from `web_admin/backend`).
- [ ] **Step 3:** Run `cd web_admin/backend && ../../.venv/Scripts/python.exe -m pytest -q` → fails (no module).
- [ ] **Step 4:** Implement `config.py` (frozen dataclass, `functools.lru_cache` on `get_settings()`, defaults resolved from repo root = `Path(__file__).resolve().parents[4]`, dirs `mkdir(parents=True, exist_ok=True)` on access) and `main.py` `create_app()` with `/api/health` router and `CORSMiddleware(allow_origins=['http://localhost:4200'], allow_methods=['*'], allow_headers=['*'])`.
- [ ] **Step 5:** Tests pass. Commit `feat(web-admin): backend scaffold with config and health endpoint`.

### Task 2: DB models and session

**Files:**
- Create: `web_admin/backend/src/db/__init__.py`, `web_admin/backend/src/db/models.py`, `web_admin/backend/src/db/session.py`
- Test: `web_admin/backend/tests/test_models.py`

**Interfaces:**
- Produces (SQLAlchemy 2.0 `Mapped`/`mapped_column`, `DeclarativeBase` named `Base`):
  - `SourceFile`: `id int PK`, `filename str unique`, `size_bytes int`, `uploaded_at datetime(UTC)`, `source_deleted bool default False`, `duration_s float|None`, `fs_hz float|None`, `gps_coverage_ratio float|None`, `recording_meta JSON|None`, relationship `runs: list[AnalysisRun]`.
  - `AnalysisRun`: `id int PK`, `file_id FK`, `created_at/started_at/finished_at datetime|None`, `status str default 'queued'`, `params JSON`, `result_dir str|None`, `summary JSON|None`, `error str|None`, `log_path str|None`, relationship `file`.
  - `session.py`: `make_engine(db_url)`, `init_db(engine)` (Base.metadata.create_all), `get_session` FastAPI dependency yielding `Session` bound to app-state engine (engine created in `create_app()` lifespan from settings, stored on `app.state`).

- [ ] **Step 1: Failing test:**

```python
def test_models_roundtrip(tmp_path):
    from src.db.session import make_engine, init_db
    from src.db.models import SourceFile, AnalysisRun
    from sqlalchemy.orm import Session
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    init_db(engine)
    with Session(engine) as s:
        f = SourceFile(filename='a.csv', size_bytes=10,
                       recording_meta={'vehicle': {'vehicle_type': 'sedan'}})
        f.runs.append(AnalysisRun(params={'low_speed_policy': 'invalid'}))
        s.add(f); s.commit()
        assert f.runs[0].status == 'queued'
        assert f.recording_meta['vehicle']['vehicle_type'] == 'sedan'
```

- [ ] **Step 2:** Fails (no module). **Step 3:** Implement; wire `init_db` into `create_app()` lifespan. **Step 4:** Pass. **Step 5:** Commit `feat(web-admin): SQLAlchemy models for files and runs`.

### Task 3: CSV preview probe service

**Files:**
- Create: `web_admin/backend/src/services/__init__.py`, `web_admin/backend/src/services/preview.py`
- Test: `web_admin/backend/tests/test_preview.py`

**Interfaces:**
- Produces: `probe_csv(path: str) -> dict` → `{duration_s, fs_hz, gps_coverage_ratio, recording_meta}`; raises `ValueError` on a header that violates the v2 contract (message includes expected columns). `recording_meta` = `dataclasses.asdict(parse_recording_metadata(path))` + `clean_stop`.
- Consumes: `road_quality_analyzer.io.ingestion.EXPECTED_COLUMNS`, `parse_recording_metadata`.

- [ ] **Step 1: Failing tests** — build a tiny CSV inline (20 accel rows @100Hz + 3 GPS rows over 2 s, v3 vehicle line, footer):

```python
def _write_csv(tmp_path, preamble=True):
    rows = ["Time,Type,X,Y,Z,Latitude,Longitude"]
    for i in range(200):
        rows.append(f"{1753796576000+i*10},Accelerometer,0.0,0.0,9.81,,")
    for i in range(3):
        rows.append(f"{1753796576000+i*1000},Location,,,,50.4{i},30.5")
    text = ("# schema=2\n# vehicle_type=sedan\n" if preamble else "") \
        + "\n".join(rows) + "\n# end: duration_ms=2000, rows_accel=200, rows_gyro=0, rows_gps=3, events=0, battery_end_pct=90, reason=user\n"
    p = tmp_path / 'probe.csv'; p.write_text(text, encoding='utf-8'); return str(p)

def test_probe_extracts_preview(tmp_path):
    from src.services.preview import probe_csv
    info = probe_csv(_write_csv(tmp_path))
    assert 1.9 < info['duration_s'] <= 2.1
    assert 90 < info['fs_hz'] < 110
    assert info['gps_coverage_ratio'] == pytest.approx(1.0, abs=0.1)
    assert info['recording_meta']['vehicle']['vehicle_type'] == 'sedan'
    assert info['recording_meta']['clean_stop'] is True

def test_probe_rejects_wrong_header(tmp_path):
    from src.services.preview import probe_csv
    p = tmp_path / 'bad.csv'; p.write_text("Time,Kind\n1,Accelerometer\n", encoding='utf-8')
    with pytest.raises(ValueError):
        probe_csv(str(p))
```

- [ ] **Step 2:** Fails. **Step 3:** Implement with `pandas.read_csv(path, comment='#', usecols=['Time','Type'], index_col=False)` after a raw header check (first non-`#` line == exact contract header); `duration_s` = (max−min Time)/1000 for ms-scale values; `fs_hz` = accel-row count / duration; `gps_coverage_ratio` = (max−min Time of Location rows)/(max−min Time overall), 0.0 when no Location rows. **Step 4:** Pass. **Step 5:** Commit `feat(web-admin): CSV preview probe with recording metadata`.

### Task 4: Files API

**Files:**
- Create: `web_admin/backend/src/api/__init__.py`, `web_admin/backend/src/api/files.py`, `web_admin/backend/src/api/schemas.py`
- Modify: `web_admin/backend/src/main.py` (include router)
- Test: `web_admin/backend/tests/test_files_api.py`

**Interfaces:**
- Produces: `POST /api/files` (multipart `file`) → 201 `FileOut`; 422 on bad header (upload not persisted); 409 on duplicate filename. `GET /api/files` → `list[FileOut]` (`runs_count`, newest first). `DELETE /api/files/{id}` → 204, sets `source_deleted=True`, removes the CSV from `storage/data/`, keeps runs. `FileOut` pydantic schema mirrors `SourceFile` + `runs_count: int`.

- [ ] **Step 1: Failing tests** (reuse `_write_csv` via a shared `tests/helpers.py`):

```python
def _upload(client, path, name='drive.csv'):
    with open(path, 'rb') as fh:
        return client.post('/api/files', files={'file': (name, fh, 'text/csv')})

def test_upload_list_delete_cycle(client, tmp_path):
    r = _upload(client, make_probe_csv(tmp_path))
    assert r.status_code == 201
    body = r.json()
    assert body['filename'] == 'drive.csv' and body['runs_count'] == 0
    assert body['recording_meta']['vehicle']['vehicle_type'] == 'sedan'
    listed = client.get('/api/files').json()
    assert len(listed) == 1
    assert client.delete(f"/api/files/{body['id']}").status_code == 204
    assert client.get('/api/files').json()[0]['source_deleted'] is True

def test_upload_rejects_bad_contract(client, tmp_path):
    p = tmp_path / 'bad.csv'; p.write_text('Time,Kind\n1,x\n', encoding='utf-8')
    assert _upload(client, p, 'bad.csv').status_code == 422
    assert client.get('/api/files').json() == []

def test_duplicate_filename_conflict(client, tmp_path):
    p = make_probe_csv(tmp_path)
    assert _upload(client, p).status_code == 201
    assert _upload(client, p).status_code == 409
```

- [ ] **Step 2:** Fails. **Step 3:** Implement: stream upload to `storage_data_dir/<filename>` via temp file, `probe_csv` it, on `ValueError` delete temp and 422 with the message; insert row with preview fields. **Step 4:** Pass. **Step 5:** Commit `feat(web-admin): files API — upload with contract validation, list, delete`.

### Task 5: Run queue, analysis service, runs API

**Files:**
- Create: `web_admin/backend/src/core/queue.py`, `web_admin/backend/src/services/analysis.py`, `web_admin/backend/src/api/runs.py`
- Modify: `web_admin/backend/src/main.py`, `web_admin/backend/src/api/schemas.py`
- Test: `web_admin/backend/tests/test_runs_api.py`

**Interfaces:**
- Produces:
  - `queue.py`: `JobQueue` wrapping `ThreadPoolExecutor(max_workers=1)`; `submit(fn, *args)`; test mode `JobQueue(inline=True)` runs jobs synchronously; instance on `app.state.queue`.
  - `analysis.py`: `execute_run(run_id: int, engine, settings)` — sets `running`+`started_at`, builds `result_dir` `<stem>__run<N>_<ts>`, redirects stdout to `<result_dir>/run.log`, calls `road_quality_analyzer.cli.analyze(csv_path, result_dir, low_speed_policy=params['low_speed_policy'])`, then `build_summary(result_dir) -> dict` (reads `road_segments.csv` + `recording_meta.json`: `segments_total`, `km_total` = sum(length_m)/1000, `mean_iri_multi` over full & speed-valid rows, `low_speed_count`, `partial_count`, `events_total`, `incidents_total`, `clean_stop`, `vehicle_type`), sets `done`/`failed`+`error`+`finished_at`.
  - `runs.py`: `POST /api/runs {file_id, params}` → 201 `RunOut` (queued + submitted); `POST /api/runs/run-all-unanalyzed` → list of created runs (files with no `done` run and not `source_deleted`); `GET /api/runs?file_id=` newest first; `GET /api/runs/{id}`; `DELETE /api/runs/{id}` → 204 removes `result_dir` tree.
- Consumes: Task 2 models, Task 1 settings.

- [ ] **Step 1: Failing tests** — conftest gains a `client` whose app uses `JobQueue(inline=True)` and a `fake_analyze` monkeypatch writing minimal artifacts:

```python
@pytest.fixture
def fake_analyze(monkeypatch):
    def _fake(input_path, output_dir, low_speed_policy='invalid'):
        out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({'seg_id': [0, 1], 'length_m': [100.0, 100.0],
                      'iri_multi': [3.2, float('nan')], 'iri_psd': [2.0, 2.5],
                      'partial': [False, False], 'speed_valid': [True, False],
                      'needs_class12_survey': [False, True],
                      'low_speed_class': ['', 'invalid'],
                      'mean_speed_kmh': [45.0, 12.0], 'events_per_km': [0.0, 30.0],
                      's_start': [0, 100], 's_end': [100, 200], 'grms': [.01, .02],
                      'iri_psd_raw': [2.0, 2.5]}).to_csv(out / 'road_segments.csv', index=False)
        (out / 'recording_meta.json').write_text(json.dumps(
            {'clean_stop': True, 'vehicle': {'vehicle_type': 'sedan'},
             'events': [{'t_ms': 1, 'type': 'gps_lost', 'attrs': {}},
                        {'t_ms': 2, 'type': 'accuracy_changed', 'attrs': {}}],
             'footer': {'reason': 'user'}, 'warnings': []}), encoding='utf-8')
        (out / 'report.md').write_text('# ok', encoding='utf-8')
        print('progress line')
    monkeypatch.setattr('src.services.analysis.analyze', _fake)

def test_run_lifecycle(client, tmp_path, fake_analyze):
    fid = upload_probe_csv(client, tmp_path)['id']
    r = client.post('/api/runs', json={'file_id': fid,
                                       'params': {'low_speed_policy': 'invalid'}})
    assert r.status_code == 201
    run = client.get(f"/api/runs/{r.json()['id']}").json()
    assert run['status'] == 'done'
    assert run['summary']['segments_total'] == 2
    assert run['summary']['low_speed_count'] == 1
    assert run['summary']['incidents_total'] == 1      # accuracy_changed excluded
    assert run['summary']['vehicle_type'] == 'sedan'
    assert run['summary']['mean_iri_multi'] == pytest.approx(3.2)

def test_failed_run_records_error(client, tmp_path, monkeypatch):
    monkeypatch.setattr('src.services.analysis.analyze',
                        lambda *a, **k: (_ for _ in ()).throw(ValueError('boom')))
    fid = upload_probe_csv(client, tmp_path)['id']
    rid = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()['id']
    run = client.get(f'/api/runs/{rid}').json()
    assert run['status'] == 'failed' and 'boom' in run['error']

def test_run_all_unanalyzed_skips_done(client, tmp_path, fake_analyze):
    fid = upload_probe_csv(client, tmp_path)['id']
    client.post('/api/runs', json={'file_id': fid, 'params': {}})
    assert client.post('/api/runs/run-all-unanalyzed').json() == []

def test_delete_run_removes_artifacts(client, tmp_path, fake_analyze):
    fid = upload_probe_csv(client, tmp_path)['id']
    rid = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()['id']
    result_dir = client.get(f'/api/runs/{rid}').json()['result_dir']
    assert Path(result_dir).exists()
    assert client.delete(f'/api/runs/{rid}').status_code == 204
    assert not Path(result_dir).exists()
```

- [ ] **Step 2:** Fails. **Step 3:** Implement (import `from road_quality_analyzer.cli import analyze` at module top of `analysis.py` so tests can monkeypatch `src.services.analysis.analyze`; `mean_iri_multi` computed over rows where `partial == False` and `speed_valid == True`, `None` if no such rows — never fabricate). **Step 4:** Pass. **Step 5:** Commit `feat(web-admin): run queue, analysis service and runs API`.

### Task 6: Artifacts, segments JSON and run log endpoints

**Files:**
- Modify: `web_admin/backend/src/api/runs.py`
- Test: `web_admin/backend/tests/test_artifacts_api.py`

**Interfaces:**
- Produces: `GET /api/runs/{id}/artifacts/{name:path}` → `FileResponse` (404 unknown; 403 on path escaping `result_dir` — resolve + `is_relative_to`); `GET /api/runs/{id}/segments` → JSON rows of `road_segments.csv` with `NaN → null`; `GET /api/runs/{id}/log?follow=true|false` — `follow=false` returns plain text; `follow=true` returns `text/event-stream` tailing the log until run leaves `running` (poll 0.5 s, `data:` per line).

- [ ] **Step 1: Failing tests:**

```python
def test_artifact_served_and_traversal_blocked(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    assert client.get(f'/api/runs/{rid}/artifacts/report.md').status_code == 200
    assert client.get(f'/api/runs/{rid}/artifacts/../../secret').status_code in (403, 404)

def test_segments_json_serializes_nan_as_null(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    rows = client.get(f'/api/runs/{rid}/segments').json()
    assert rows[1]['iri_multi'] is None      # NaN → null, never a number

def test_log_plain(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    assert 'progress line' in client.get(f'/api/runs/{rid}/log?follow=false').text
```

- [ ] **Step 2:** Fails. **Step 3:** Implement (segments via `pd.read_csv(...).replace({np.nan: None}).to_dict('records')`). **Step 4:** Pass. **Step 5:** Commit `feat(web-admin): artifact, segments and log endpoints`.

### Task 7: Global map and dashboard

**Files:**
- Create: `web_admin/backend/src/services/global_map.py`, `web_admin/backend/src/services/dashboard.py`, `web_admin/backend/src/api/global_map.py`, `web_admin/backend/src/api/dashboard.py`
- Modify: `web_admin/backend/src/main.py`
- Test: `web_admin/backend/tests/test_global_map_dashboard.py`

**Interfaces:**
- Produces:
  - `global_map.py`: `rebuild_global_map(session, settings) -> dict` — for each non-deleted file take its latest `done` run, read `<result_dir>/roughness.geojson`, tag every feature's `properties` with `run_id`/`file_id`/`filename`, concatenate into one `FeatureCollection`, write `storage_results_dir/global_map.geojson`, return it; `load_global_map(settings)` returns the cached file or rebuilds.
  - `dashboard.py`: `build_dashboard(session) -> dict` — `{files_total, runs_done, km_total, iri_histogram: [{bin_start, bin_end, count}] (1 m/km bins 0..12 over latest-run full+speed-valid segments), worst_segments: top 10 by iri_psd across latest runs [{run_id, seg_id, iri_psd, iri_multi, filename}], low_speed_total}`.
  - Endpoints: `POST /api/global-map/rebuild`, `GET /api/global-map`, `GET /api/dashboard`.
- Consumes: fake_analyze fixture extended to also write a 2-feature `roughness.geojson`.

- [ ] **Step 1: Failing tests:**

```python
def test_global_map_merges_latest_runs(client, tmp_path, fake_analyze):
    make_done_run(client, tmp_path, name='a.csv')
    make_done_run(client, tmp_path, name='b.csv')
    fc = client.post('/api/global-map/rebuild').json()
    assert fc['type'] == 'FeatureCollection' and len(fc['features']) == 4
    assert {f['properties']['filename'] for f in fc['features']} == {'a.csv', 'b.csv'}
    assert client.get('/api/global-map').json() == fc

def test_dashboard_aggregates(client, tmp_path, fake_analyze):
    make_done_run(client, tmp_path)
    d = client.get('/api/dashboard').json()
    assert d['files_total'] == 1 and d['runs_done'] == 1
    assert d['km_total'] == pytest.approx(0.2)
    assert len(d['worst_segments']) == 2
    assert d['worst_segments'][0]['iri_psd'] >= d['worst_segments'][1]['iri_psd']
```

- [ ] **Step 2:** Fails. **Step 3:** Implement. **Step 4:** Pass. **Step 5:** Commit `feat(web-admin): global map merge and dashboard aggregation`.

### Task 8: Backend integration smoke (real analyzer)

**Files:**
- Test: `web_admin/backend/tests/test_smoke_integration.py`

**Interfaces:** consumes everything; no new code.

- [ ] **Step 1:** Test uploading a REAL synthetic drive (reuse analyzer conftest builder by path-importing `analyzer/tests/conftest.py` helpers is forbidden across packages — instead generate with the same math inline: 40 s, 100 Hz, 15 m/s straight north, sine excitation, v2 preamble; ~90 lines) → `POST /runs` (inline queue) → run `done`, artifacts exist (`road_segments.csv`, `recording_meta.json`, `report.md`, `segments_map.html`, `roughness.geojson`), summary sane (`segments_total >= 4`, `km_total ≈ 0.6`), `/segments` returns rows, global map rebuild includes the run. Mark `@pytest.mark.slow`.
- [ ] **Step 2:** Run it (~30 s) → green. **Step 3:** Commit `test(web-admin): end-to-end smoke through the real analyzer`.

### Task 9: Angular scaffold, API service, app shell

**Files:**
- Create: `web_admin/frontend/` via `npx @angular/cli@22 new frontend --directory web_admin/frontend --standalone --routing --style css --skip-git`, `web_admin/frontend/proxy.conf.json` (`"/api" → http://127.0.0.1:8000`), `src/app/api/api.service.ts`, `src/app/api/dto.ts`, routes for `/files`, `/runs`, `/runs/:id`, `/map`, `/dashboard`, nav shell in `app.component`.

**Interfaces:**
- Produces: `dto.ts` — `FileOut`, `RunOut`, `RunSummary`, `DashboardOut`, `RecordingMeta` interfaces mirroring backend schemas verbatim; `ApiService` (`inject(HttpClient)`): `listFiles()`, `uploadFile(file: File)`, `deleteFile(id)`, `createRun(fileId, params)`, `runAllUnanalyzed()`, `listRuns(fileId?)`, `getRun(id)`, `deleteRun(id)`, `getSegments(runId)`, `getDashboard()`, `getGlobalMap()`, `rebuildGlobalMap()`, `artifactUrl(runId, name): string`, `logUrl(runId): string`. Provide `provideHttpClient()`; zoneless per CLI default; OnPush is the v22 default — don't fight it.

- [ ] **Step 1:** Generate scaffold; `npm install leaflet marked && npm install -D @types/leaflet`. **Step 2:** Implement shell + service + DTOs; nav links in Ukrainian: Файли / Результати / Глобальна мапа / Дашборд. **Step 3:** `ng build` green; default runner unit test for ApiService URL building (`provideHttpClientTesting`). **Step 4:** Commit `feat(web-admin): Angular 22 scaffold, API client, navigation shell`.

### Task 10: Files and Results UI

**Files:**
- Create: `src/app/files/files-page.ts|.html`, `src/app/runs/runs-page.ts|.html`, `src/app/runs/run-detail.ts|.html`, `src/app/shared/vehicle-chip.ts`, `src/app/shared/status-badge.ts` (+ colocated `.spec.ts` for files-page and run-detail)

**Interfaces:**
- Consumes Task 9 `ApiService`/DTOs.
- Produces: Files page — table (name, size, duration, fs, GPS%, vehicle chip `vehicle_type + vehicle_make_model` or «без профілю», badge «чиста зупинка»/«обірваний»/«pre-v2.1» from `recording_meta.clean_stop`/`schema`), upload via `<input type=file>` + drop zone, delete with confirm, «Аналізувати» dialog (select low-speed policy: very-poor/poor/invalid/ignore, default invalid), «Аналізувати всі нові». Runs page — table with status chips, summary chips (`vehicle_type`, `clean_stop`, `incidents_total`), auto-refresh every 2 s while any run `queued|running` (`interval` + `switchMap`). Run detail — status header; while running: log via `EventSource(logUrl)`; when done: `report.md` fetched from artifacts and rendered with `marked` into `[innerHTML]` (sanitized via `DomSanitizer.bypassSecurityTrustHtml` on marked output of our own backend files), 4 plot `<img>` from `artifactUrl(id, 'plots/<name>.png')`, folium `<iframe [src]>` `segments_map.html`, segments table from `getSegments()` — low-speed rows show `low_speed_class` label instead of numeric `iri_multi` (invariant), magenta dot for `needs_class12_survey`.

- [ ] **Step 1:** Failing specs: files-page renders vehicle chip from stubbed `ApiService` (signal of `FileOut[]`); run-detail hides numeric `iri_multi` for a `needs_class12_survey` row (renders `—` + class label).
- [ ] **Step 2:** Implement pages/components. **Step 3:** Specs + `ng build` green. **Step 4:** Commit `feat(web-admin): files and results UI`.

### Task 11: Global map + dashboard UI, rules, docs, final regression

**Files:**
- Create: `src/app/map/global-map-page.ts|.html`, `src/app/dashboard/dashboard-page.ts|.html`, `.claude/rules/web-admin-backend.md`, `.claude/rules/web-admin-frontend.md`
- Modify: `docs/08_user_guide_and_cli_reference.md` (short "Веб-адмінка" section: how to start backend `uvicorn src.main:app --reload` from `web_admin/backend` + `ng serve --proxy-config proxy.conf.json`), `docs/00_index.md` (link), `README.md` (one paragraph)

**Interfaces:** consumes `getGlobalMap`/`rebuildGlobalMap`/`getDashboard`.

- [ ] **Step 1:** Global map page: Leaflet map (OSM tiles), `L.geoJSON` styled by `iri_multi` scale (green <2.5, yellow <4, orange <6, red ≥6, magenta `#FF00FF` when `needs_class12_survey` with legend «Потребує обстеження профілометром (клас 1/2)»), popup → router link to run page, «Оновити глобальну мапу» button. Dashboard page: totals cards, CSS-bar IRI histogram (no chart lib — YAGNI), top-10 worst table with run links.
- [ ] **Step 2:** Path-scoped rules: backend file (FastAPI 2.0-style SQLAlchemy, settings via env, no auth-yet seam, artifacts on disk, NaN→null rule); frontend file (standalone + signals, OnPush default, DTOs mirror backend, no numeric IRI for low-speed).
- [ ] **Step 3:** Docs + README updates (Ukrainian).
- [ ] **Step 4:** Final regression: backend pytest suite green; analyzer suite still 177 green; `ng build` + frontend specs green; hidden-character scan over all new/changed files.
- [ ] **Step 5:** Commit `feat(web-admin): global map and dashboard UI, project rules, docs`.
