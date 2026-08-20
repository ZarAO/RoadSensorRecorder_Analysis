import pytest

from tests.test_runs_api import fake_analyze, make_done_run  # noqa: F401 (fixtures)


def test_global_map_merges_latest_runs(client, tmp_path, fake_analyze):
    make_done_run(client, tmp_path, name='a.csv')
    make_done_run(client, tmp_path, name='b.csv')
    fc = client.post('/api/global-map/rebuild').json()
    assert fc['type'] == 'FeatureCollection' and len(fc['features']) == 4
    assert {f['properties']['filename'] for f in fc['features']} == {'a.csv', 'b.csv'}
    assert all('run_id' in f['properties'] for f in fc['features'])
    assert client.get('/api/global-map').json() == fc


def test_global_map_uses_only_latest_done_run_per_file(client, tmp_path, fake_analyze):
    rid = make_done_run(client, tmp_path, name='a.csv')
    fid = client.get(f'/api/runs/{rid}').json()['file_id']
    rid2 = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()['id']
    fc = client.post('/api/global-map/rebuild').json()
    assert len(fc['features']) == 2
    assert {f['properties']['run_id'] for f in fc['features']} == {rid2}


def test_dashboard_aggregates(client, tmp_path, fake_analyze):
    make_done_run(client, tmp_path)
    d = client.get('/api/dashboard').json()
    assert d['files_total'] == 1 and d['runs_done'] == 1
    assert d['km_total'] == pytest.approx(0.2)
    assert d['low_speed_total'] == 1
    assert len(d['worst_segments']) == 2
    assert d['worst_segments'][0]['iri_psd'] >= d['worst_segments'][1]['iri_psd']
    assert sum(b['count'] for b in d['iri_histogram']) == 1  # one full+valid segment


def test_dashboard_empty_state(client):
    d = client.get('/api/dashboard').json()
    assert d['files_total'] == 0 and d['worst_segments'] == []
