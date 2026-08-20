"""
Aggregate (multi-pass) comparisons: the job over three synthetic passes, the
pre-queue guards, drafting an Eq.6 set from an aggregate, and the two delete
paths (run deletion -> stale flag, aggregate deletion -> detached sets).

The three passes share one geometry and differ only in an IRI shift and a mean
speed, which makes every aggregate statistic analytically known:
  * shifts (0, -0.1, +0.1) average to 0  -> the aggregate bias equals the bias
    of the unshifted pass (asserted against the per-bin profile itself);
  * their within-bin sd is exactly sd([0, -0.1, +0.1]) = 0.1 -> repeatability;
  * speeds 40/60/80 km/h demean to (-20, 0, +20) against shifts (0, -0.1, +0.1)
    demeaned to themselves -> slope = 2/800 = 0.0025 IRI per km/h.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from tests.conftest import _make_reference

# (iri_shift, mean_speed_kmh) per synthetic pass
PASSES = ((0.0, 40.0), (-0.1, 60.0), (0.1, 80.0))
EXPECTED_REPEATABILITY_SD = 0.1
EXPECTED_SPEED_SLOPE = 0.0025


def _make_pass(result_dir: Path, iri_shift: float, speed: float, n_seg=10):
    """conftest._make_run_artifacts with a per-pass IRI shift and mean speed:
    10 x 100 m segments heading north along lon=30.5 (same geometry for every
    pass, so all passes land on the same reference bins)."""
    deg = 100.0 / 111_195.0
    rows, features = [], []
    for i in range(n_seg):
        lat0, lat1 = 50.0 + i * deg, 50.0 + (i + 1) * deg
        rows.append({'seg_id': i, 's_start': i * 100.0, 's_end': (i + 1) * 100.0,
                     'length_m': 100.0, 'grms': 0.5 + 0.02 * i,
                     'psd_sqrt_scalar': 0.010 + 0.001 * i,
                     'iri_psd_raw': 3.0, 'iri_psd': 3.0,
                     'iri_multi': 2.0 + 0.2 * i + iri_shift, 'mean_speed_kmh': speed,
                     'partial': False, 'speed_valid': True,
                     'low_speed_class': None, 'needs_class12_survey': False})
        coords = [[30.5, lat0], [30.5, (lat0 + lat1) / 2], [30.5, lat1]]
        features.append({'type': 'Feature', 'properties': {'seg_id': i},
                         'geometry': {'type': 'LineString', 'coordinates': coords}})
    result_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(result_dir / 'road_segments.csv', index=False)
    (result_dir / 'roughness.geojson').write_text(json.dumps(
        {'type': 'FeatureCollection', 'features': features}), encoding='utf-8')


def _make_passes_and_reference(client, tmp_path):
    """Three done runs (one per pass) plus the matching 10 m reference."""
    from src.core.config import get_settings
    from src.db.models import AnalysisRun, ReferenceDataset, SourceFile

    engine = client.app.state.engine
    settings = get_settings()
    run_ids = []
    with Session(engine) as s:
        ref = ReferenceDataset(filename='agg.xlsx', road_name='Т-9999', step_m=10.0,
                               intervals_count=100, chainage_span_m=1000.0,
                               bbox=[50.0, 30.4, 50.01, 30.6], parse_warnings=[])
        s.add(ref)
        s.commit()
        _make_reference(settings.storage_reference_dir / str(ref.id))
        for idx, (shift, speed) in enumerate(PASSES):
            f = SourceFile(filename=f'pass{idx}.csv', size_bytes=1)
            s.add(f)
            s.commit()
            run = AnalysisRun(file_id=f.id, status='done',
                              result_dir=str(tmp_path / f'pass{idx}'))
            s.add(run)
            s.commit()
            _make_pass(Path(run.result_dir), shift, speed)
            run_ids.append(run.id)
        ref_id = ref.id
    return run_ids, ref_id


def _create_aggregate(client, run_ids, ref_id):
    r = client.post('/api/aggregate-comparisons',
                    json={'reference_id': ref_id, 'run_ids': run_ids})
    assert r.status_code == 201, r.text
    return r.json()['id']


def test_aggregate_flow_and_artifacts(client, tmp_path):
    run_ids, ref_id = _make_passes_and_reference(client, tmp_path)
    agg_id = _create_aggregate(client, run_ids, ref_id)

    agg = client.get(f'/api/aggregate-comparisons/{agg_id}').json()
    assert agg['status'] == 'done', agg['error']
    assert agg['reference_road'] == 'Т-9999'
    assert agg['run_filenames'] == ['pass0.csv', 'pass1.csv', 'pass2.csv']

    summary = agg['summary']
    assert summary['n_runs'] == 3
    assert summary['n_bins'] >= 5
    assert summary['repeatability_sd'] == pytest.approx(EXPECTED_REPEATABILITY_SD, abs=1e-4)
    assert summary['speed_slope'] == pytest.approx(EXPECTED_SPEED_SLOPE, abs=1e-4)
    assert summary['rho'] == pytest.approx(1.0, abs=1e-4)
    assert summary['bias_ci_low'] < summary['bias'] < summary['bias_ci_high']
    assert summary['stale'] is False

    for name in ('per_pass_pairs.csv', 'per_bin.csv', 'aggregate_stats.json',
                 'chart_data.json', 'figures/fig_agg_profile.png',
                 'figures/fig_agg_profile.pdf', 'figures/fig_agg_speed.png'):
        r = client.get(f'/api/aggregate-comparisons/{agg_id}/artifacts/{name}')
        assert r.status_code == 200, name

    chart = client.get(
        f'/api/aggregate-comparisons/{agg_id}/artifacts/chart_data.json').json()
    assert len(chart['profile']) == summary['n_bins']
    for row in chart['profile']:
        assert row['lo'] <= row['mean_iri'] <= row['hi']
        assert row['n_passes'] == 3
        assert row['std_iri'] is not None
    assert chart['speed_effect']['slope_iri_per_kmh'] == pytest.approx(
        EXPECTED_SPEED_SLOPE, abs=1e-6)
    assert chart['validation']['rho'] == pytest.approx(1.0, abs=1e-6)
    # The reported bias IS the mean per-bin diff of the rendered profile
    mean_diff = (sum(r['mean_iri'] - r['iri_ref'] for r in chart['profile'])
                 / len(chart['profile']))
    assert summary['bias'] == pytest.approx(mean_diff, abs=1e-4)

    listing = client.get('/api/aggregate-comparisons').json()
    assert listing[0]['id'] == agg_id
    assert client.get(
        f'/api/aggregate-comparisons/{agg_id}/artifacts/..%2F..%2Fsecret'
    ).status_code == 403


def test_aggregate_create_guards(client, tmp_path):
    from src.db.models import AnalysisRun, ReferenceDataset, SourceFile
    from src.services.aggregate import MSG_TOO_FEW_RUNS
    from src.services.comparison import MSG_REFERENCE_DELETED

    run_ids, ref_id = _make_passes_and_reference(client, tmp_path)

    r = client.post('/api/aggregate-comparisons',
                    json={'reference_id': ref_id, 'run_ids': run_ids[:1]})
    assert r.status_code == 422
    assert r.json()['detail'] == MSG_TOO_FEW_RUNS
    # The same run twice is one pass, not two
    r = client.post('/api/aggregate-comparisons',
                    json={'reference_id': ref_id, 'run_ids': [run_ids[0], run_ids[0]]})
    assert r.status_code == 422

    assert client.post('/api/aggregate-comparisons',
                       json={'reference_id': ref_id,
                             'run_ids': [run_ids[0], 9999]}).status_code == 404
    assert client.post('/api/aggregate-comparisons',
                       json={'reference_id': 9999,
                             'run_ids': run_ids}).status_code == 404

    engine = client.app.state.engine
    with Session(engine) as s:
        f = SourceFile(filename='queued.csv', size_bytes=1)
        s.add(f)
        s.commit()
        queued = AnalysisRun(file_id=f.id, status='queued')
        s.add(queued)
        s.commit()
        queued_id = queued.id
    r = client.post('/api/aggregate-comparisons',
                    json={'reference_id': ref_id, 'run_ids': [run_ids[0], queued_id]})
    assert r.status_code == 409

    with Session(engine) as s:
        deleted_ref = ReferenceDataset(filename='gone.xlsx', road_name='Y', step_m=10.0,
                                       intervals_count=100, chainage_span_m=1000.0,
                                       parse_warnings=[], source_deleted=True)
        s.add(deleted_ref)
        s.commit()
        deleted_ref_id = deleted_ref.id
    r = client.post('/api/aggregate-comparisons',
                    json={'reference_id': deleted_ref_id, 'run_ids': run_ids})
    assert r.status_code == 409
    assert r.json()['detail'] == MSG_REFERENCE_DELETED


def test_coefficient_set_draft_from_aggregate(client, tmp_path):
    run_ids, ref_id = _make_passes_and_reference(client, tmp_path)
    agg_id = _create_aggregate(client, run_ids, ref_id)
    summary = client.get(f'/api/aggregate-comparisons/{agg_id}').json()['summary']

    r = client.post('/api/coefficient-sets',
                    json={'aggregate_comparison_id': agg_id, 'model': 'eq6_bias',
                          'name': 'AGG_van', 'vehicle_type': 'van'})
    assert r.status_code == 201, r.text
    cs = r.json()
    assert cs['aggregate_comparison_id'] == agg_id
    assert cs['comparison_id'] is None
    assert cs['params']['bias'] == pytest.approx(summary['bias'], abs=1e-4)
    assert set(cs['stats_snapshot']) == {
        'bias_ci_low', 'bias_ci_high', 'n_passes', 'n_bins',
        'repeatability_sd', 'rho', 'mae_aggregated'}
    assert cs['stats_snapshot']['n_passes'] == 3
    assert cs['stats_snapshot']['repeatability_sd'] == pytest.approx(
        EXPECTED_REPEATABILITY_SD, abs=1e-4)

    # No Eq.3 fit exists in an aggregate
    r = client.post('/api/coefficient-sets',
                    json={'aggregate_comparison_id': agg_id, 'model': 'eq3',
                          'name': 'AGG_eq3', 'vehicle_type': 'van'})
    assert r.status_code == 409

    # Exactly one provenance id is required
    r = client.post('/api/coefficient-sets',
                    json={'aggregate_comparison_id': agg_id, 'comparison_id': 1,
                          'model': 'eq6_bias', 'name': 'AGG_both', 'vehicle_type': 'van'})
    assert r.status_code == 422
    r = client.post('/api/coefficient-sets',
                    json={'model': 'eq6_bias', 'name': 'AGG_none', 'vehicle_type': 'van'})
    assert r.status_code == 422

    assert client.post('/api/coefficient-sets',
                       json={'aggregate_comparison_id': 9999, 'model': 'eq6_bias',
                             'name': 'AGG_missing',
                             'vehicle_type': 'van'}).status_code == 404


def test_run_delete_marks_aggregate_stale(client, tmp_path):
    run_ids, ref_id = _make_passes_and_reference(client, tmp_path)
    agg_id = _create_aggregate(client, run_ids, ref_id)
    assert client.get(
        f'/api/aggregate-comparisons/{agg_id}').json()['summary']['stale'] is False

    assert client.delete(f'/api/runs/{run_ids[0]}').status_code == 204
    agg = client.get(f'/api/aggregate-comparisons/{agg_id}').json()
    assert agg['summary']['stale'] is True
    # Enrichment stays empty-safe with a deleted run in run_ids
    assert agg['run_filenames'] == ['pass1.csv', 'pass2.csv']


def test_aggregate_delete_detaches_coefficient_sets(client, tmp_path):
    run_ids, ref_id = _make_passes_and_reference(client, tmp_path)
    agg_id = _create_aggregate(client, run_ids, ref_id)
    result_dir = client.get(f'/api/aggregate-comparisons/{agg_id}').json()['result_dir']
    set_id = client.post('/api/coefficient-sets',
                         json={'aggregate_comparison_id': agg_id, 'model': 'eq6_bias',
                               'name': 'AGG_van', 'vehicle_type': 'van'}).json()['id']
    assert Path(result_dir).exists()

    assert client.delete(f'/api/aggregate-comparisons/{agg_id}').status_code == 204
    assert not Path(result_dir).exists()
    assert client.get(f'/api/aggregate-comparisons/{agg_id}').status_code == 404
    kept = [s for s in client.get('/api/coefficient-sets').json() if s['id'] == set_id]
    assert len(kept) == 1
    assert kept[0]['aggregate_comparison_id'] is None
    assert kept[0]['stats_snapshot']['n_passes'] == 3


def test_init_db_migrates_existing_coefficient_sets_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.begin() as c:
        c.execute(text('CREATE TABLE coefficient_sets (id INTEGER PRIMARY KEY, name TEXT)'))
    from src.db.session import init_db
    init_db(engine)
    cols = {col['name'] for col in inspect(engine).get_columns('coefficient_sets')}
    assert 'aggregate_comparison_id' in cols
    init_db(engine)  # idempotent
    assert 'aggregate_comparisons' in inspect(engine).get_table_names()
