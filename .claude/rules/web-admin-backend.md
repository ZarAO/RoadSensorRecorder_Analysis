# Web admin backend rules (path-scoped: web_admin/backend/**)

- FastAPI app factory (`create_app()`), engine + `JobQueue` on `app.state`, wired
  in the lifespan. Settings only via `src/core/config.get_settings()` and the
  `RQA_DATA_DIR` / `RQA_RESULTS_DIR` / `RQA_DB_URL` / `RQA_QUEUE_INLINE` env vars —
  never hardcode storage paths.
- SQLAlchemy 2.0 style only: `Mapped[...]` / `mapped_column`, `select()`; no legacy
  `Query`. DB stores metadata only — artifacts stay under `storage/results/`.
- The analyzer is a library: `from road_quality_analyzer.cli import analyze`,
  in-process, one at a time (`ThreadPoolExecutor(max_workers=1)`). No subprocess,
  no Celery/Redis.
- Recording metadata comes ONLY from `road_quality_analyzer.io.parse_recording_metadata`
  — never re-parse the CSV comment layer here.
- JSON responses: a missing metric is `null`, never `NaN` (pandas `replace({np.nan: None})`).
- No numeric IRI for low-speed segments in any response shape the UI renders directly.
- Artifact serving must stay inside the run dir (`resolve()` + `is_relative_to`).
- Deleting a file keeps runs (`source_deleted=True`); deleting a run removes its
  artifacts dir. Auth deliberately absent for now — add as middleware/Depends seam.
- Tests: httpx TestClient + `RQA_QUEUE_INLINE=1`; stub `src.services.analysis.analyze`
  via monkeypatch; the real analyzer runs only in `@pytest.mark.slow` smoke tests.
- Reference intervals are stored as a derived CSV consumed by
  `profilometer_validation.match.load_form_10m` — never re-derive them from the
  xlsx elsewhere. Comparison artifacts (`matched_pairs.csv`, `stats.json`,
  `chart_data.json`, `figures/`) live under `storage/results/comparisons/`.
- Error-language policy: 404/403 (technical) in English; 409/422 (operator-facing
  business errors) in Ukrainian.
- Coefficient resolution happens ONLY via `src/services/coefficients.resolve_for_meta`
  — no duplicated resolution logic in routers or the analysis service. Book
  constants (the published Eq.3/Eq.6 defaults) never live in the DB; an
  unresolved model means the analyzer keeps them from code. Any client-supplied
  `params['coefficients']` is always stripped before resolution (anti-spoofing).
