import json
from pathlib import Path

import pandas as pd
import pytest

from tests.helpers import upload_probe_csv


@pytest.fixture
def fake_analyze(monkeypatch):
    """Stand-in for the real analyze(): writes the minimal artifact set."""
    def _fake(input_path, output_dir, low_speed_policy='invalid'):
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({
            'seg_id': [0, 1], 'length_m': [100.0, 100.0],
            'iri_multi': [3.2, float('nan')], 'iri_psd': [2.0, 2.5],
            'iri_psd_raw': [2.0, 2.5], 'grms': [.01, .02],
            'partial': [False, False], 'speed_valid': [True, False],
            'needs_class12_survey': [False, True],
            'low_speed_class': ['', 'invalid'],
            'mean_speed_kmh': [45.0, 12.0], 'events_per_km': [0.0, 30.0],
            's_start': [0, 100], 's_end': [100, 200],
        }).to_csv(out / 'road_segments.csv', index=False)
        (out / 'recording_meta.json').write_text(json.dumps(
            {'clean_stop': True, 'vehicle': {'vehicle_type': 'sedan'},
             'events': [{'t_ms': 1, 'type': 'gps_lost', 'attrs': {}},
                        {'t_ms': 2, 'type': 'accuracy_changed', 'attrs': {}}],
             'footer': {'reason': 'user'}, 'warnings': []}), encoding='utf-8')
        (out / 'report.md').write_text('# ok', encoding='utf-8')
        (out / 'roughness.geojson').write_text(json.dumps({
            'type': 'FeatureCollection',
            'features': [
                {'type': 'Feature', 'properties': {'seg_id': 0, 'iri_multi': 3.2,
                                                    'needs_class12_survey': False},
                 'geometry': {'type': 'LineString',
                              'coordinates': [[30.5, 50.40], [30.5, 50.41]]}},
                {'type': 'Feature', 'properties': {'seg_id': 1, 'iri_multi': None,
                                                    'needs_class12_survey': True},
                 'geometry': {'type': 'LineString',
                              'coordinates': [[30.5, 50.41], [30.5, 50.42]]}},
            ]}), encoding='utf-8')
        print('progress line')
    monkeypatch.setattr('src.services.analysis.analyze', _fake)
    return _fake


def make_done_run(client, tmp_path, name='drive.csv', params=None):
    fid = upload_probe_csv(client, tmp_path, name=name)['id']
    r = client.post('/api/runs', json={'file_id': fid,
                                       'params': params or {'low_speed_policy': 'invalid'}})
    assert r.status_code == 201, r.text
    return r.json()['id']


def test_run_lifecycle(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    run = client.get(f'/api/runs/{rid}').json()
    assert run['status'] == 'done'
    assert run['started_at'] and run['finished_at']
    assert run['summary']['segments_total'] == 2
    assert run['summary']['low_speed_count'] == 1
    assert run['summary']['incidents_total'] == 1      # accuracy_changed excluded
    assert run['summary']['events_total'] == 2
    assert run['summary']['clean_stop'] is True
    assert run['summary']['vehicle_type'] == 'sedan'
    assert run['summary']['mean_iri_multi'] == pytest.approx(3.2)
    assert run['summary']['km_total'] == pytest.approx(0.2)
    assert 'drive__run' in run['result_dir']


def test_failed_run_records_error(client, tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise ValueError('boom')
    monkeypatch.setattr('src.services.analysis.analyze', _boom)
    fid = upload_probe_csv(client, tmp_path)['id']
    rid = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()['id']
    run = client.get(f'/api/runs/{rid}').json()
    assert run['status'] == 'failed' and 'boom' in run['error']


def test_run_all_unanalyzed_skips_done(client, tmp_path, fake_analyze):
    fid = upload_probe_csv(client, tmp_path)['id']
    client.post('/api/runs', json={'file_id': fid, 'params': {}})
    assert client.post('/api/runs/run-all-unanalyzed').json() == []
    upload_probe_csv(client, tmp_path, name='second.csv')
    created = client.post('/api/runs/run-all-unanalyzed').json()
    assert len(created) == 1 and created[0]['status'] == 'done'


def test_runs_filter_by_file(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    fid = client.get(f'/api/runs/{rid}').json()['file_id']
    assert [r['id'] for r in client.get(f'/api/runs?file_id={fid}').json()] == [rid]
    assert client.get('/api/runs?file_id=999').json() == []


def test_delete_run_removes_artifacts(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path)
    result_dir = client.get(f'/api/runs/{rid}').json()['result_dir']
    assert Path(result_dir).exists()
    assert client.delete(f'/api/runs/{rid}').status_code == 204
    assert not Path(result_dir).exists()
    assert client.get(f'/api/runs/{rid}').status_code == 404


def test_run_for_unknown_file_404(client, fake_analyze):
    assert client.post('/api/runs', json={'file_id': 42, 'params': {}}).status_code == 404
