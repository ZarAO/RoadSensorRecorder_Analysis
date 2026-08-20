"""
Phase 3: resolution of confirmed coefficient sets at run creation and their
application in the pipeline (analyze kwargs, summary, segment responses).
"""

from sqlalchemy.orm import Session

META_VAN = {'preamble': {'device': 'samsung SM-S948B, android=16'},
            'vehicle': {'vehicle_type': 'van'}}
# Contract v3.1: the phone writes its own identity into the file
DEVICE_ID = 'a1b2c3d4e5f60718'
VEHICLE_ID = '7f3c9e10-0000-4000-8000-abcdefabcdef'
META_VAN_V31 = {'preamble': {'device': 'samsung SM-S948B, android=16',
                             'device_id': DEVICE_ID},
                'vehicle': {'vehicle_type': 'van', 'vehicle_id': VEHICLE_ID}}


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


def _upload_with_device(client, name, device, vehicle_type,
                        device_id=None, vehicle_id=None):
    """A file whose recording_meta is parsed by the real upload endpoint, so the
    device string is exactly what phone_model_from_meta will later read.
    device_id/vehicle_id are the contract v3.1 identity keys (absent = legacy)."""
    lines = [f'# device: {device}', f'# vehicle_type={vehicle_type}']
    if device_id is not None:
        lines.insert(0, f'# device_id={device_id}')
    if vehicle_id is not None:
        lines.append(f'# vehicle_id={vehicle_id}')
    csv = ('# schema=2\n' + '\n'.join(lines) + '\n'
           'Time,Type,X,Y,Z,Latitude,Longitude\n'
           '1753796576000,Accelerometer,0.0,0.0,9.81,,\n'
           '1753796577000,Accelerometer,0.0,0.0,9.81,,\n').encode('utf-8')
    r = client.post('/api/files', files={'file': (name, csv)})
    assert r.status_code == 201, r.text
    return r.json()['id']


def test_identity_keys_are_read_from_the_parsed_v31_preamble(client):
    """Contract pin: `# device_id=` lands in the preamble and `# vehicle_id=` in
    the vehicle block (the parser keeps the `vehicle_` prefix), which is exactly
    where the resolution helpers look."""
    from src.db.models import SourceFile
    from src.services.coefficients import device_id_from_meta, vehicle_id_from_meta
    fid = _upload_with_device(client, 'v31.csv', 'samsung SM-S948B, android=16',
                              'van', device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    with Session(client.app.state.engine) as s:
        meta = s.get(SourceFile, fid).recording_meta
    assert meta['preamble']['device_id'] == DEVICE_ID
    assert meta['vehicle']['vehicle_id'] == VEHICLE_ID
    assert device_id_from_meta(meta) == DEVICE_ID
    assert vehicle_id_from_meta(meta) == VEHICLE_ID
    # A legacy file has neither key and must never raise
    assert device_id_from_meta(META_VAN) is None
    assert vehicle_id_from_meta(META_VAN) is None
    assert device_id_from_meta(None) is None and vehicle_id_from_meta(None) is None


def test_identity_tier_wins_over_phone_and_generic(client):
    """Tier 1: a set keyed on (device_id, vehicle_id) beats the phone and the
    NULL tier for the recording that carries exactly that identity."""
    from src.services.coefficients import resolve_for_meta
    engine = client.app.state.engine
    _add_set(engine, name='van_any')
    phone = _add_set(engine, name='van_s948', phone_model='samsung SM-S948B')
    identity = _add_set(engine, name='van_this_phone_and_car',
                        phone_model='samsung SM-S948B',
                        device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    with Session(engine) as s:
        assert resolve_for_meta(s, META_VAN_V31)['eq6_bias']['set_id'] == identity
        # The same phone in ANOTHER car must not inherit that car's calibration
        other_car = {'preamble': dict(META_VAN_V31['preamble']),
                     'vehicle': {'vehicle_type': 'van', 'vehicle_id': 'other-uuid'}}
        assert resolve_for_meta(s, other_car)['eq6_bias']['set_id'] == phone


def test_legacy_file_never_resolves_an_identity_set(client):
    """A recording made before contract v3.1 carries no device_id: an identity
    set is invisible to it and the phone/NULL tiers keep working as before."""
    from src.services.coefficients import resolve_for_meta
    engine = client.app.state.engine
    generic = _add_set(engine, name='van_any')
    _add_set(engine, name='van_identity', phone_model='samsung SM-S948B',
             device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    with Session(engine) as s:
        assert resolve_for_meta(s, META_VAN)['eq6_bias']['set_id'] == generic


def test_partial_identity_resolves_nothing_and_falls_back(client):
    """Half an identity is never tier 1: a set with only a device_id resolves for
    nothing, and a file with only a device_id resolves via the legacy tiers."""
    from src.services.coefficients import resolve_for_meta
    engine = client.app.state.engine
    _add_set(engine, name='half_set', phone_model='samsung SM-S948B',
             device_id=DEVICE_ID)                     # no vehicle_id
    _add_set(engine, name='half_set_2', device_id=None, vehicle_id=VEHICLE_ID,
             phone_model=None)                        # no device_id
    with Session(engine) as s:
        assert resolve_for_meta(s, META_VAN_V31)['eq6_bias'] is None
        assert resolve_for_meta(s, META_VAN)['eq6_bias'] is None

    legacy = _add_set(engine, name='van_s948', phone_model='samsung SM-S948B')
    half_file = {'preamble': {'device': 'samsung SM-S948B, android=16',
                              'device_id': DEVICE_ID},
                 'vehicle': {'vehicle_type': 'van'}}   # no vehicle_id in the file
    with Session(engine) as s:
        assert resolve_for_meta(s, half_file)['eq6_bias']['set_id'] == legacy


def test_files_resolving_to_identity_key(client):
    """The inverse of tier 1: the identity pair selects its own recordings and
    ignores the vehicle type (the identity already names the car)."""
    from src.services.coefficients import files_resolving_to
    mine = _upload_with_device(client, 'mine.csv', 'samsung SM-S948B, android=16',
                              'van', device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    _upload_with_device(client, 'other_car.csv', 'samsung SM-S948B, android=16',
                        'van', device_id=DEVICE_ID, vehicle_id='other-uuid')
    _upload_with_device(client, 'legacy.csv', 'samsung SM-S948B, android=16', 'van')
    with Session(client.app.state.engine) as s:
        assert [f.id for f in files_resolving_to(
            s, 'van', 'samsung SM-S948B', DEVICE_ID, VEHICLE_ID)] == [mine]
        # A half identity never resolves, so it applies to nothing
        assert files_resolving_to(s, 'van', None, DEVICE_ID, None) == []
        assert files_resolving_to(s, 'van', None, None, VEHICLE_ID) == []
        # The legacy tiers stay vehicle-type based and see all three files
        assert len(files_resolving_to(s, 'van', None)) == 3


def test_files_resolving_to_is_phone_aware(client):
    """The preview of «which files would this set apply to»: the exact-phone tier
    matches one device, the NULL-phone tier every file of the vehicle type."""
    from src.services.coefficients import files_resolving_to
    s948 = _upload_with_device(client, 'van_s948.csv',
                               'samsung SM-S948B, android=16', 'van')
    pixel = _upload_with_device(client, 'van_pixel.csv',
                                'google Pixel 9, android=15', 'van')
    sedan = _upload_with_device(client, 'sedan_s948.csv',
                                'samsung SM-S948B, android=16', 'sedan')
    engine = client.app.state.engine

    with Session(engine) as s:
        assert {f.id for f in files_resolving_to(s, 'van', None)} == {s948, pixel}
        assert [f.id for f in files_resolving_to(s, 'van', 'samsung SM-S948B')] == [s948]
        assert [f.id for f in files_resolving_to(s, 'sedan', 'samsung SM-S948B')] == [sedan]
        # A hand-typed device string can never match a parsed preamble device
        assert files_resolving_to(s, 'van', 'zarichnyi-samsung-s26u') == []
        # No vehicle type resolves nothing (mirrors resolve(): a pre-v3 file
        # without a vehicle block must not inherit another vehicle's set)
        assert files_resolving_to(s, None, None) == []

    assert client.delete(f'/api/files/{s948}').status_code == 204
    with Session(engine) as s:
        assert [f.id for f in files_resolving_to(s, 'van', None)] == [pixel]
        assert files_resolving_to(s, 'van', 'samsung SM-S948B') == []


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


def test_client_supplied_coefficients_are_stripped(client, tmp_path, monkeypatch):
    """A forged params.coefficients must never pass as an applied confirmed set."""
    calls = {}
    _stub_analyze(monkeypatch, calls)

    from tests.helpers import upload_probe_csv
    fid = upload_probe_csv(client, tmp_path, name='spoofed.csv')['id']
    spoofed = {'eq3': {'set_id': 999, 'name': 'forged', 'params': {'A': 1.0, 'B': 2.0}},
               'eq6_bias': {'set_id': 998, 'name': 'forged', 'params': {'bias': -9.0}}}
    run = client.post('/api/runs', json={'file_id': fid,
                                        'params': {'coefficients': spoofed}}).json()
    # no confirmed sets exist -> the key must be gone, not echoed back
    assert 'coefficients' not in run['params']
    assert calls == {'iri_psd_A': None, 'iri_psd_B': None}

    detail = client.get(f"/api/runs/{run['id']}").json()
    assert 'coefficients' not in detail['summary']
    assert 'mean_iri_multi_corrected' not in detail['summary']
    assert 'iri_multi_corrected' not in client.get(
        f"/api/runs/{run['id']}/segments").json()[0]
    from pathlib import Path
    assert not (Path(run['result_dir']) / 'calibration.json').exists()


def test_bias_of_rejects_bool_and_non_finite():
    from src.services.coefficients import bias_of
    def wrap(bias):
        return {'eq6_bias': {'params': {'bias': bias}}}
    assert bias_of(wrap(-1.55)) == -1.55
    assert bias_of(wrap(0)) == 0.0
    assert bias_of(wrap(True)) is None          # bool is an int subclass
    assert bias_of(wrap(float('nan'))) is None  # a metric is null, never NaN
    assert bias_of(wrap(float('inf'))) is None
    assert bias_of(wrap('-1.55')) is None
    assert bias_of(wrap(None)) is None
    assert bias_of(None) is None


def test_all_nan_mean_iri_stays_null(client, tmp_path, monkeypatch):
    """An all-NaN iri_multi column must give null, not NaN, in the summary."""
    engine = client.app.state.engine
    _add_set(engine, name='sedan_bias', vehicle_type='sedan')

    def fake_analyze(input_path, output_dir, low_speed_policy='invalid',
                     iri_psd_A=None, iri_psd_B=None):
        import pandas as pd
        from pathlib import Path
        pd.DataFrame({'seg_id': [0], 'length_m': [100.0], 'iri_multi': [None],
                      'partial': [False], 'speed_valid': [True],
                      'needs_class12_survey': [True]}).to_csv(
            Path(output_dir) / 'road_segments.csv', index=False)
    monkeypatch.setattr('src.services.analysis.analyze', fake_analyze)

    from tests.helpers import upload_probe_csv
    fid = upload_probe_csv(client, tmp_path, name='all_nan.csv')['id']
    run = client.post('/api/runs', json={'file_id': fid, 'params': {}}).json()
    summary = client.get(f"/api/runs/{run['id']}").json()['summary']
    assert summary['mean_iri_multi'] is None
    assert 'mean_iri_multi_corrected' not in summary


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
