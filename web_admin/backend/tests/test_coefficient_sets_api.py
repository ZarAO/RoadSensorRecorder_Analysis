"""
CoefficientSet API: draft from a done comparison, confirm (archives the
previous confirmed set of the same key), archive, and reanalyze.
"""

import json
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from tests.test_comparisons_api import _make_done_run_and_reference


def _make_done_comparison(client, tmp_path) -> int:
    """A fully executed (status='done') comparison, so its stats.json exists
    on disk for the draft endpoint to read (RQA_QUEUE_INLINE=1 runs it inline)."""
    run_id, ref_id = _make_done_run_and_reference(client, tmp_path)
    r = client.post('/api/comparisons', json={'run_id': run_id, 'reference_id': ref_id})
    assert r.status_code == 201, r.text
    cmp = client.get(f"/api/comparisons/{r.json()['id']}").json()
    assert cmp['status'] == 'done'
    return cmp['id']


def test_draft_from_comparison_and_invariant(client, tmp_path):
    cmp_id = _make_done_comparison(client, tmp_path)

    r = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': 'van_v1',
        'vehicle_type': 'van'})
    assert r.status_code == 201, r.text
    assert r.json()['status'] == 'draft'
    assert 'bias' in r.json()['params']
    assert set(r.json()['stats_snapshot']) == {
        'r2', 'mae', 'spearman_rho', 'n_pairs', 'mae_bias_corrected'}

    r2 = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': 'van_v2',
        'vehicle_type': 'van'})
    assert r2.status_code == 201, r2.text

    c1 = client.post(f"/api/coefficient-sets/{r.json()['id']}/confirm", json={'note': 'перший'})
    assert c1.status_code == 200, c1.text
    assert c1.json()['archived_set_id'] is None
    assert c1.json()['set']['status'] == 'confirmed'
    assert c1.json()['reanalyze_candidates'] == 0  # no file carries vehicle_type='van'

    c2 = client.post(f"/api/coefficient-sets/{r2.json()['id']}/confirm", json={})
    assert c2.status_code == 200, c2.text
    assert c2.json()['archived_set_id'] == r.json()['id']

    listing = client.get('/api/coefficient-sets').json()
    sets = {s['name']: s['status'] for s in listing}
    assert sets == {'van_v1': 'archived', 'van_v2': 'confirmed'}
    # newest first
    assert [s['name'] for s in listing] == ['van_v2', 'van_v1']


def test_draft_validations(client, tmp_path):
    cmp_id = _make_done_comparison(client, tmp_path)

    assert client.post('/api/coefficient-sets', json={
        'comparison_id': 9999, 'model': 'eq3', 'name': 'x', 'vehicle_type': 'van',
    }).status_code == 404

    r = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'bogus', 'name': 'x', 'vehicle_type': 'van'})
    assert r.status_code == 422

    ok = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'dup', 'vehicle_type': 'van'})
    assert ok.status_code == 201, ok.text
    dup = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'dup', 'vehicle_type': 'van'})
    assert dup.status_code == 409


def test_draft_degenerate_fit_409(client, tmp_path):
    """A NaN fit is json-nulled to None in stats.json (services.comparison._json_safe);
    the draft endpoint must refuse rather than silently fall back to book constants."""
    cmp_id = _make_done_comparison(client, tmp_path)
    result_dir = Path(client.get(f'/api/comparisons/{cmp_id}').json()['result_dir'])
    stats_path = result_dir / 'stats.json'
    stats = json.loads(stats_path.read_text(encoding='utf-8'))
    stats['eq6_bias']['bias'] = None
    stats['eq3_fit']['A'] = None
    stats_path.write_text(json.dumps(stats), encoding='utf-8')

    bias_r = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': 'degenerate_bias',
        'vehicle_type': 'van'})
    assert bias_r.status_code == 409, bias_r.text

    eq3_r = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'degenerate_eq3',
        'vehicle_type': 'van'})
    assert eq3_r.status_code == 409, eq3_r.text


def test_draft_missing_stats_file_404(client, tmp_path):
    cmp_id = _make_done_comparison(client, tmp_path)
    result_dir = Path(client.get(f'/api/comparisons/{cmp_id}').json()['result_dir'])
    (result_dir / 'stats.json').unlink()

    r = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'no_stats',
        'vehicle_type': 'van'})
    assert r.status_code == 404, r.text


def test_draft_from_not_done_comparison_409(client, tmp_path):
    run_id, ref_id = _make_done_run_and_reference(client, tmp_path)
    engine = client.app.state.engine
    from src.db.models import Comparison
    with Session(engine) as s:
        pending = Comparison(run_id=run_id, reference_id=ref_id, status='running')
        s.add(pending)
        s.commit()
        pending_id = pending.id

    r = client.post('/api/coefficient-sets', json={
        'comparison_id': pending_id, 'model': 'eq3', 'name': 'x', 'vehicle_type': 'van'})
    assert r.status_code == 409


def test_confirm_only_from_draft_and_archive_twice(client, tmp_path):
    cmp_id = _make_done_comparison(client, tmp_path)

    r = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'archived_early',
        'vehicle_type': 'sedan'})
    set_id = r.json()['id']

    archived = client.post(f'/api/coefficient-sets/{set_id}/archive')
    assert archived.status_code == 200, archived.text
    assert archived.json()['status'] == 'archived'

    # confirming an already-archived set is 409
    r2 = client.post(f'/api/coefficient-sets/{set_id}/confirm', json={})
    assert r2.status_code == 409

    # archiving an already-archived set is 409
    r3 = client.post(f'/api/coefficient-sets/{set_id}/archive')
    assert r3.status_code == 409


def test_reanalyze_creates_new_runs_with_new_set(client, tmp_path, monkeypatch):
    # -- a van file, uploaded through the real endpoint so recording_meta is parsed
    csv = (b'# schema=2\n# device: samsung SM-S948B, android=16\n# vehicle_type=van\n'
           b'Time,Type,X,Y,Z,Latitude,Longitude\n'
           b'1753796576000,Accelerometer,0.0,0.0,9.81,,\n'
           b'1753796577000,Accelerometer,0.0,0.0,9.81,,\n'
           b'1753796576000,Location,,,,50.40,30.5\n'
           b'1753796577000,Location,,,,50.41,30.5\n')
    up = client.post('/api/files', files={'file': ('van.csv', csv)})
    assert up.status_code == 201, up.text
    file_id = up.json()['id']

    # -- an old done run for that file, built directly (mirrors
    # _make_done_run_and_reference) so a comparison can be run against it
    engine = client.app.state.engine
    from src.core.config import get_settings
    from src.db.models import AnalysisRun, ReferenceDataset
    from tests.conftest import _make_reference, _make_run_artifacts

    settings = get_settings()
    with Session(engine) as s:
        old_run = AnalysisRun(file_id=file_id, status='done',
                              result_dir=str(tmp_path / 'old_run_art'))
        ref = ReferenceDataset(filename='van.xlsx', road_name='Т-9999', step_m=10.0,
                               intervals_count=100, chainage_span_m=1000.0,
                               bbox=[50.0, 30.4, 50.01, 30.6], parse_warnings=[])
        s.add_all([old_run, ref])
        s.commit()
        _make_run_artifacts(Path(old_run.result_dir))
        _make_reference(settings.storage_reference_dir / str(ref.id))
        old_run_id, ref_id = old_run.id, ref.id

    cmp_r = client.post('/api/comparisons', json={'run_id': old_run_id, 'reference_id': ref_id})
    assert cmp_r.status_code == 201, cmp_r.text
    cmp_id = cmp_r.json()['id']
    assert client.get(f'/api/comparisons/{cmp_id}').json()['status'] == 'done'

    draft = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': 'van_bias',
        'vehicle_type': 'van'})
    assert draft.status_code == 201, draft.text
    set_id = draft.json()['id']
    confirm = client.post(f'/api/coefficient-sets/{set_id}/confirm', json={})
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()['reanalyze_candidates'] == 1

    # -- stub the analyzer for the new run the reanalyze endpoint triggers
    def fake_analyze(input_path, output_dir, low_speed_policy='invalid',
                     iri_psd_A=None, iri_psd_B=None):
        pd.DataFrame({'seg_id': [0], 'length_m': [100.0], 'iri_multi': [4.0],
                      'partial': [False], 'speed_valid': [True],
                      'needs_class12_survey': [False]}).to_csv(
            Path(output_dir) / 'road_segments.csv', index=False)
    monkeypatch.setattr('src.services.analysis.analyze', fake_analyze)

    runs = client.post(f'/api/coefficient-sets/{set_id}/reanalyze').json()
    assert len(runs) == 1
    assert runs[0]['params']['coefficients']['eq6_bias']['set_id'] == set_id
    assert runs[0]['file_id'] == file_id

    all_runs = client.get(f'/api/runs?file_id={file_id}').json()
    assert len(all_runs) == 2  # the old run is untouched, the new run was added
    assert {r['id'] for r in all_runs} == {old_run_id, runs[0]['id']}
    old_after = next(r for r in all_runs if r['id'] == old_run_id)
    assert old_after['status'] == 'done' and 'coefficients' not in old_after['params']


def test_reanalyze_only_from_confirmed(client, tmp_path):
    cmp_id = _make_done_comparison(client, tmp_path)
    draft = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'still_draft',
        'vehicle_type': 'van'})
    set_id = draft.json()['id']
    r = client.post(f'/api/coefficient-sets/{set_id}/reanalyze')
    assert r.status_code == 409


def test_delete_comparison_nulls_coefficient_set_fk(client, tmp_path):
    cmp_id = _make_done_comparison(client, tmp_path)
    draft = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'survivor',
        'vehicle_type': 'van'})
    assert draft.status_code == 201, draft.text
    set_id = draft.json()['id']
    snapshot = draft.json()['stats_snapshot']

    assert client.delete(f'/api/comparisons/{cmp_id}').status_code == 204

    surviving = next(s for s in client.get('/api/coefficient-sets').json()
                     if s['id'] == set_id)
    assert surviving['comparison_id'] is None
    assert surviving['stats_snapshot'] == snapshot


def test_delete_run_cascades_comparison_and_nulls_coefficient_set_fk(client, tmp_path):
    """DELETE /api/runs/{run_id} cascades its comparisons (test_run_deletion_
    cascades_to_comparisons); a CoefficientSet drafted from one of them must
    survive with comparison_id nulled, same as a direct comparison delete."""
    run_id, ref_id = _make_done_run_and_reference(client, tmp_path)
    cmp_id = client.post('/api/comparisons',
                         json={'run_id': run_id, 'reference_id': ref_id}).json()['id']
    assert client.get(f'/api/comparisons/{cmp_id}').json()['status'] == 'done'

    draft = client.post('/api/coefficient-sets', json={
        'comparison_id': cmp_id, 'model': 'eq3', 'name': 'run_delete_survivor',
        'vehicle_type': 'van'})
    assert draft.status_code == 201, draft.text
    set_id = draft.json()['id']
    snapshot = draft.json()['stats_snapshot']

    assert client.delete(f'/api/runs/{run_id}').status_code == 204
    assert client.get(f'/api/comparisons/{cmp_id}').status_code == 404

    surviving = next(s for s in client.get('/api/coefficient-sets').json()
                     if s['id'] == set_id)
    assert surviving['comparison_id'] is None
    assert surviving['stats_snapshot'] == snapshot
