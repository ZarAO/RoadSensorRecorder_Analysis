"""
Phase 2 Task 7: run-vs-run comparison of one file
(GET /api/files/{file_id}/compare?run_a=<id>&run_b=<id>).
"""

from pathlib import Path
from sqlalchemy.orm import Session

from tests.helpers import upload_probe_csv


def _seg_data(seg_ids, iri_multi, iri_psd=None, grms=None, mean_speed_kmh=None):
    n = len(seg_ids)
    return {
        'seg_id': seg_ids,
        's_start': [i * 100.0 for i in seg_ids],
        'length_m': [100.0] * n,
        'partial': [False] * n,
        'speed_valid': [True] * n,
        'needs_class12_survey': [False] * n,
        'iri_multi': iri_multi,
        'iri_psd': iri_psd or [2.0 + 0.1 * i for i in seg_ids],
        'grms': grms or [0.5 + 0.01 * i for i in seg_ids],
        'mean_speed_kmh': mean_speed_kmh or [50.0] * n,
    }


def _stub_analyze_sequence(monkeypatch, specs):
    """Consumes one `specs[i]` per analyze() call, in call order — so two runs of
    the SAME file (whose analyze() call is patched to the same function) can
    write different road_segments.csv content."""
    calls = {'i': 0}

    def fake_analyze(input_path, output_dir, low_speed_policy='invalid',
                     iri_psd_A=None, iri_psd_B=None):
        import pandas as pd
        data = specs[calls['i']]
        calls['i'] += 1
        pd.DataFrame(data).to_csv(Path(output_dir) / 'road_segments.csv', index=False)

    monkeypatch.setattr('src.services.analysis.analyze', fake_analyze)
    return calls


def test_deltas_are_exact_for_two_runs_of_one_file_with_shifted_iri_multi(client, tmp_path, monkeypatch):
    _stub_analyze_sequence(monkeypatch, [
        _seg_data([0, 1, 2], [3.0, 4.0, 5.0]),
        _seg_data([0, 1, 2], [4.0, 5.0, 6.0]),   # +1.0 shift
    ])
    fid = upload_probe_csv(client, tmp_path, name='drive.csv')['id']
    run_a = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()
    run_b = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()
    assert run_a['status'] == 'done' and run_b['status'] == 'done'

    r = client.get(f"/api/files/{fid}/compare",
                   params={'run_a': run_a['id'], 'run_b': run_b['id']})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body['file_id'] == fid
    assert body['run_a']['id'] == run_a['id']
    assert body['run_b']['id'] == run_b['id']
    assert body['run_a']['params'] == run_a['params']
    assert body['run_a']['summary'] == run_a['summary']

    rows = {row['seg_id']: row for row in body['segments']}
    assert set(rows) == {0, 1, 2}
    for seg_id, row in rows.items():
        assert row['iri_multi_a'] == 3.0 + seg_id
        assert row['iri_multi_b'] == 4.0 + seg_id
        assert row['delta_iri_multi'] == 1.0
        assert row['s_start'] == seg_id * 100.0

    assert body['summary'] == {
        'segments': 3, 'matched': 3,
        'mean_delta_iri_multi': 1.0, 'max_abs_delta': 1.0,
    }


def test_run_of_another_file_is_rejected(client, tmp_path, monkeypatch):
    _stub_analyze_sequence(monkeypatch, [
        _seg_data([0], [3.0]),
        _seg_data([0], [3.5]),
    ])
    fid_1 = upload_probe_csv(client, tmp_path, name='one.csv')['id']
    fid_2 = upload_probe_csv(client, tmp_path, name='two.csv')['id']
    run_a = client.post('/api/runs', json={'file_id': fid_1, 'params': {}}).json()
    run_c = client.post('/api/runs', json={'file_id': fid_2, 'params': {}}).json()

    r = client.get(f"/api/files/{fid_1}/compare",
                   params={'run_a': run_a['id'], 'run_b': run_c['id']})
    assert r.status_code == 409
    assert r.json()['detail'] == 'ран не належить цьому файлу'


def test_queued_run_is_rejected(client, tmp_path, monkeypatch):
    _stub_analyze_sequence(monkeypatch, [_seg_data([0], [3.0])])
    fid = upload_probe_csv(client, tmp_path, name='drive.csv')['id']
    run_a = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()

    # A run stuck at 'queued' (never executed) — built directly, bypassing the
    # inline queue that the client fixture forces every real run through.
    from src.db.models import AnalysisRun
    engine = client.app.state.engine
    with Session(engine) as s:
        queued = AnalysisRun(file_id=fid, params={}, status='queued')
        s.add(queued)
        s.commit()
        queued_id = queued.id

    r = client.get(f"/api/files/{fid}/compare",
                   params={'run_a': run_a['id'], 'run_b': queued_id})
    assert r.status_code == 409
    assert r.json()['detail'] == 'обидва рани мають бути завершені'


def test_null_iri_multi_on_one_side_gives_a_null_delta(client, tmp_path, monkeypatch):
    _stub_analyze_sequence(monkeypatch, [
        _seg_data([0], [5.0]),
        _seg_data([0], [None]),   # low-speed segment on the B side
    ])
    fid = upload_probe_csv(client, tmp_path, name='drive.csv')['id']
    run_a = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()
    run_b = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()

    r = client.get(f"/api/files/{fid}/compare",
                   params={'run_a': run_a['id'], 'run_b': run_b['id']})
    assert r.status_code == 200, r.text
    body = r.json()
    row = body['segments'][0]
    assert row['iri_multi_a'] == 5.0
    assert row['iri_multi_b'] is None
    assert row['delta_iri_multi'] is None
    assert body['summary']['mean_delta_iri_multi'] is None
    assert body['summary']['max_abs_delta'] is None
    # The row is still matched (present on both sides) — only the delta is null
    assert body['summary'] == {
        'segments': 1, 'matched': 1,
        'mean_delta_iri_multi': None, 'max_abs_delta': None,
    }


def test_unknown_file_is_404(client):
    r = client.get('/api/files/999/compare', params={'run_a': 1, 'run_b': 2})
    assert r.status_code == 404


def test_matched_is_less_than_segments_when_a_policy_drops_a_segment(client, tmp_path, monkeypatch):
    """A low_speed_policy difference can exclude a segment from one run's
    artifacts entirely (not just null its iri_multi) — the union ('segments')
    then exceeds the inner join ('matched'), and that is not an error."""
    _stub_analyze_sequence(monkeypatch, [
        _seg_data([0, 1, 2], [3.0, 4.0, 5.0]),
        _seg_data([0, 1], [3.5, 4.5]),   # seg 2 dropped entirely on this side
    ])
    fid = upload_probe_csv(client, tmp_path, name='drive.csv')['id']
    run_a = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()
    run_b = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()

    r = client.get(f"/api/files/{fid}/compare",
                   params={'run_a': run_a['id'], 'run_b': run_b['id']})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['summary']['segments'] == 3
    assert body['summary']['matched'] == 2
    assert {row['seg_id'] for row in body['segments']} == {0, 1}
