"""
Phase 3: resolution of confirmed coefficient sets at run creation and their
application in the pipeline (analyze kwargs, summary, segment responses).
"""

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
        # No metadata at all must never raise and never resolve
        assert resolve_for_meta(s, None) == {'eq3': None, 'eq6_bias': None}


def test_draft_and_archived_sets_are_ignored(client):
    from src.services.coefficients import resolve_for_meta
    engine = client.app.state.engine
    _add_set(engine, name='van_draft', status='draft')
    _add_set(engine, name='van_archived', status='archived')
    with Session(engine) as s:
        assert resolve_for_meta(s, META_VAN)['eq6_bias'] is None


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

    csv = (b'# schema=2\n# device: samsung SM-S948B, android=16\n# vehicle_type=van\n'
           b'Time,Type,X,Y,Z,Latitude,Longitude\n'
           b'1753796576000,Accelerometer,0.0,0.0,9.81,,\n'
           b'1753796577000,Accelerometer,0.0,0.0,9.81,,\n'
           b'1753796576000,Location,,,,50.40,30.5\n'
           b'1753796577000,Location,,,,50.41,30.5\n')
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

    # calibration.json records the applied snapshot next to the artifacts
    import json
    from pathlib import Path
    saved = json.loads((Path(detail['result_dir']) / 'calibration.json')
                       .read_text(encoding='utf-8'))
    assert saved['eq6_bias']['name'] == 'van_bias' and saved['eq3'] is None


def _stub_analyze(monkeypatch, calls):
    def fake_analyze(input_path, output_dir, low_speed_policy='invalid',
                     iri_psd_A=None, iri_psd_B=None):
        calls.update(iri_psd_A=iri_psd_A, iri_psd_B=iri_psd_B)
        import pandas as pd
        from pathlib import Path
        pd.DataFrame({'seg_id': [0], 'length_m': [100.0], 'iri_multi': [4.0],
                      'partial': [False], 'speed_valid': [True],
                      'needs_class12_survey': [False]}).to_csv(
            Path(output_dir) / 'road_segments.csv', index=False)
    monkeypatch.setattr('src.services.analysis.analyze', fake_analyze)


def test_eq3_set_is_passed_into_analyze(client, tmp_path, monkeypatch):
    engine = client.app.state.engine
    # helpers' CSV declares vehicle_type=sedan and carries no device line
    _add_set(engine, name='sedan_eq3', model='eq3', params={'A': 120.0, 'B': -0.4},
             vehicle_type='sedan')
    calls = {}
    _stub_analyze(monkeypatch, calls)

    from tests.helpers import upload_probe_csv
    fid = upload_probe_csv(client, tmp_path, name='sedan_eq3.csv')['id']
    run = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()
    assert run['params']['coefficients']['eq3']['params'] == {'A': 120.0, 'B': -0.4}
    assert run['params']['coefficients']['eq6_bias'] is None
    assert calls == {'iri_psd_A': 120.0, 'iri_psd_B': -0.4}

    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail['summary']['coefficients']['eq3']['name'] == 'sedan_eq3'
    # No eq6_bias set -> no corrected values anywhere
    assert 'mean_iri_multi_corrected' not in detail['summary']
    assert 'iri_multi_corrected' not in client.get(
        f"/api/runs/{run['id']}/segments").json()[0]


def test_non_matching_vehicle_leaves_run_untouched(client, tmp_path, monkeypatch):
    engine = client.app.state.engine
    _add_set(engine, name='van_only')             # vehicle_type='van'
    calls = {}
    _stub_analyze(monkeypatch, calls)

    from tests.helpers import upload_probe_csv
    fid = upload_probe_csv(client, tmp_path, name='sedan.csv')['id']
    run = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()
    assert 'coefficients' not in run['params']
    assert calls == {'iri_psd_A': None, 'iri_psd_B': None}

    rows = client.get(f"/api/runs/{run['id']}/segments").json()
    assert 'iri_multi_corrected' not in rows[0]
    from pathlib import Path
    assert not (Path(run['result_dir']) / 'calibration.json').exists()
    assert 'coefficients' not in client.get(f"/api/runs/{run['id']}").json()['summary']
