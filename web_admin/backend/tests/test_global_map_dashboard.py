import pytest

from tests.helpers import make_probe_csv
from tests.test_coefficients import _upload_with_device
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
    assert d['by_vehicle_type'] == {}


def test_dashboard_breaks_down_by_vehicle_type(client, fake_analyze):
    van_id = _upload_with_device(client, 'van.csv', 'pixel 9, android=15', 'van')
    client.post('/api/runs', json={'file_id': van_id,
                                   'params': {'low_speed_policy': 'invalid'}})
    sedan_id = _upload_with_device(client, 'sedan.csv', 'pixel 9, android=15', 'sedan')
    client.post('/api/runs', json={'file_id': sedan_id,
                                   'params': {'low_speed_policy': 'invalid'}})

    d = client.get('/api/dashboard').json()
    by_type = d['by_vehicle_type']
    assert set(by_type) == {'van', 'sedan'}
    for key in ('van', 'sedan'):
        assert by_type[key]['files_total'] == 1
        assert by_type[key]['runs_done'] == 1
        assert by_type[key]['km_total'] == pytest.approx(0.2)
        assert by_type[key]['low_speed_total'] == 1
        assert by_type[key]['mean_iri_multi'] == pytest.approx(3.2)
        assert sum(b['count'] for b in by_type[key]['iri_histogram']) == 1
    # Global totals stay the sum across types (unchanged shape/behaviour)
    assert d['files_total'] == 2 and d['km_total'] == pytest.approx(0.4)


def test_dashboard_vehicle_type_defaults_to_unknown(client, tmp_path, fake_analyze):
    """A file with no vehicle preamble buckets under the 'невідомо' key."""
    no_meta_path = make_probe_csv(tmp_path, name='no_meta.csv', preamble=False)
    with open(no_meta_path, 'rb') as fh:
        r = client.post('/api/files', files={'file': ('no_meta.csv', fh, 'text/csv')})
    assert r.status_code == 201, r.text
    client.post('/api/runs', json={'file_id': r.json()['id'],
                                   'params': {'low_speed_policy': 'invalid'}})

    d = client.get('/api/dashboard').json()
    assert set(d['by_vehicle_type']) == {'невідомо'}
    assert d['by_vehicle_type']['невідомо']['files_total'] == 1
    assert d['by_vehicle_type']['невідомо']['runs_done'] == 1
