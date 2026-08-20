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


def test_preview_resolution_counts_files_per_phone_tier(client):
    """The confirm dialog's «Застосується до N файлів»: the count is phone-aware,
    so a mistyped phone_model surfaces as 0 before the operator confirms."""
    from tests.test_coefficients import _upload_with_device
    _upload_with_device(client, 'van.csv', 'samsung SM-S948B, android=16', 'van')
    _upload_with_device(client, 'van_pixel.csv', 'google Pixel 9, android=15', 'van')

    exact = client.post('/api/coefficient-sets/preview-resolution', json={
        'model': 'eq6_bias', 'vehicle_type': 'van', 'phone_model': 'samsung SM-S948B'})
    assert exact.status_code == 200, exact.text
    assert exact.json() == {'files_matched': 1, 'filenames': ['van.csv']}

    any_phone = client.post('/api/coefficient-sets/preview-resolution', json={
        'model': 'eq6_bias', 'vehicle_type': 'van', 'phone_model': None})
    assert any_phone.json()['files_matched'] == 2
    assert sorted(any_phone.json()['filenames']) == ['van.csv', 'van_pixel.csv']

    typo = client.post('/api/coefficient-sets/preview-resolution', json={
        'model': 'eq6_bias', 'vehicle_type': 'van',
        'phone_model': 'zarichnyi-samsung-s26u'})
    assert typo.json() == {'files_matched': 0, 'filenames': []}

    other_vehicle = client.post('/api/coefficient-sets/preview-resolution', json={
        'model': 'eq3', 'vehicle_type': 'sedan', 'phone_model': None})
    assert other_vehicle.json()['files_matched'] == 0

    bogus = client.post('/api/coefficient-sets/preview-resolution', json={
        'model': 'bogus', 'vehicle_type': 'van', 'phone_model': None})
    assert bogus.status_code == 422


def test_preview_resolution_is_the_true_inverse_of_resolution(client):
    """A file already won by a MORE specific confirmed set must not be counted
    for a less specific previewed key — the count promises only what the new set
    would actually be applied to."""
    from tests.test_coefficients import _add_set, _upload_with_device
    _upload_with_device(client, 'van_s948.csv', 'samsung SM-S948B, android=16', 'van')
    _upload_with_device(client, 'van_pixel.csv', 'google Pixel 9, android=15', 'van')

    def preview(**key):
        r = client.post('/api/coefficient-sets/preview-resolution',
                        json={'model': 'eq6_bias', 'vehicle_type': 'van', **key})
        assert r.status_code == 200, r.text
        return r.json()

    # Nothing confirmed yet: the NULL tier would win both files
    assert preview(phone_model=None)['files_matched'] == 2

    _add_set(client.app.state.engine, name='van_s948_confirmed',
             phone_model='samsung SM-S948B')
    stolen = preview(phone_model=None)
    assert stolen == {'files_matched': 1, 'filenames': ['van_pixel.csv']}
    # The same key as the confirmed set still counts its own file (re-confirm),
    # and a more specific key is never stolen from.
    assert preview(phone_model='samsung SM-S948B')['files_matched'] == 1


def test_preview_resolution_counts_the_identity_tier(client):
    from tests.test_coefficients import (DEVICE_ID, VEHICLE_ID, _add_set,
                                         _upload_with_device)
    _upload_with_device(client, 'v31.csv', 'samsung SM-S948B, android=16', 'van',
                        device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    _upload_with_device(client, 'legacy.csv', 'samsung SM-S948B, android=16', 'van')

    def preview(**key):
        r = client.post('/api/coefficient-sets/preview-resolution',
                        json={'model': 'eq6_bias', 'vehicle_type': 'van', **key})
        assert r.status_code == 200, r.text
        return r.json()

    assert preview(phone_model='samsung SM-S948B', device_id=DEVICE_ID,
                   vehicle_id=VEHICLE_ID) == {'files_matched': 1,
                                              'filenames': ['v31.csv']}
    # Half an identity resolves for nothing — visible as 0 before the confirm
    assert preview(device_id=DEVICE_ID)['files_matched'] == 0
    # A confirmed identity set steals its file from the phone tier, not the other way
    _add_set(client.app.state.engine, name='identity_confirmed',
             phone_model='samsung SM-S948B', device_id=DEVICE_ID,
             vehicle_id=VEHICLE_ID)
    assert preview(phone_model='samsung SM-S948B') == {'files_matched': 1,
                                                       'filenames': ['legacy.csv']}
    assert preview(phone_model='samsung SM-S948B', device_id=DEVICE_ID,
                   vehicle_id=VEHICLE_ID)['files_matched'] == 1


def test_confirm_archives_only_the_same_full_key(client, tmp_path):
    """The «one confirmed per key» invariant runs on the FULL key: an identity
    set and the legacy phone set of the same vehicle coexist."""
    from tests.test_coefficients import DEVICE_ID, VEHICLE_ID
    cmp_id = _make_done_comparison(client, tmp_path)

    def draft(name, **key):
        r = client.post('/api/coefficient-sets', json={
            'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': name,
            'vehicle_type': 'van', **key})
        assert r.status_code == 201, r.text
        return r.json()

    identity_v1 = draft('identity_v1', phone_model='samsung SM-S948B',
                        device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    assert identity_v1['device_id'] == DEVICE_ID
    assert identity_v1['vehicle_id'] == VEHICLE_ID

    c1 = client.post(f"/api/coefficient-sets/{identity_v1['id']}/confirm", json={})
    assert c1.status_code == 200, c1.text
    assert c1.json()['archived_set_id'] is None

    legacy = draft('legacy_phone', phone_model='samsung SM-S948B')
    assert legacy['device_id'] is None and legacy['vehicle_id'] is None
    c2 = client.post(f"/api/coefficient-sets/{legacy['id']}/confirm", json={})
    assert c2.json()['archived_set_id'] is None      # different full key

    identity_v2 = draft('identity_v2', phone_model='samsung SM-S948B',
                        device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    c3 = client.post(f"/api/coefficient-sets/{identity_v2['id']}/confirm", json={})
    assert c3.json()['archived_set_id'] == identity_v1['id']

    statuses = {s['name']: s['status'] for s in client.get('/api/coefficient-sets').json()}
    assert statuses['identity_v1'] == 'archived'
    assert statuses['legacy_phone'] == 'confirmed'
    assert statuses['identity_v2'] == 'confirmed'


def test_confirm_identity_set_archives_on_the_identity_key_only(client, tmp_path):
    """Tier 1 resolves on (model, device_id, vehicle_id) and ignores
    vehicle_type/phone_model, so the confirm invariant must archive on exactly
    that key. Otherwise two confirmed sets own the same phone+car, and archiving
    the newer one by hand silently resurrects the older calibration."""
    from tests.test_coefficients import DEVICE_ID, VEHICLE_ID
    cmp_id = _make_done_comparison(client, tmp_path)

    def draft(name, **key):
        r = client.post('/api/coefficient-sets', json={
            'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': name, **key})
        assert r.status_code == 201, r.text
        return r.json()

    first = draft('identity_van', vehicle_type='van',
                  phone_model='samsung SM-S948B',
                  device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    c1 = client.post(f"/api/coefficient-sets/{first['id']}/confirm", json={})
    assert c1.status_code == 200, c1.text
    assert c1.json()['archived_set_id'] is None

    # Same phone and same car profile, but a different vehicle_type and a
    # different phone string: still the SAME tier-1 key, so the old one goes
    second = draft('identity_sedan', vehicle_type='sedan',
                   phone_model='google Pixel 9',
                   device_id=DEVICE_ID, vehicle_id=VEHICLE_ID)
    c2 = client.post(f"/api/coefficient-sets/{second['id']}/confirm", json={})
    assert c2.json()['archived_set_id'] == first['id']

    # Another car of the same phone is a different tier-1 key and coexists
    other_car = draft('identity_other_car', vehicle_type='sedan',
                      phone_model='google Pixel 9',
                      device_id=DEVICE_ID, vehicle_id='veh-other-uuid')
    c3 = client.post(f"/api/coefficient-sets/{other_car['id']}/confirm", json={})
    assert c3.json()['archived_set_id'] is None

    statuses = {s['name']: s['status'] for s in client.get('/api/coefficient-sets').json()}
    assert statuses == {'identity_van': 'archived', 'identity_sedan': 'confirmed',
                        'identity_other_car': 'confirmed'}


def test_confirm_legacy_set_keeps_the_full_key(client, tmp_path):
    """Without BOTH identity keys the set resolves at tier 2/3, which compares
    vehicle_type and phone_model — so the invariant stays on the full NULL-safe
    key there, and a half identity does not collapse into the tier-1 branch."""
    from tests.test_coefficients import DEVICE_ID
    cmp_id = _make_done_comparison(client, tmp_path)

    def draft(name, **key):
        r = client.post('/api/coefficient-sets', json={
            'comparison_id': cmp_id, 'model': 'eq6_bias', 'name': name,
            'vehicle_type': 'van', **key})
        assert r.status_code == 201, r.text
        return r.json()

    s948_v1 = draft('legacy_s948_v1', phone_model='samsung SM-S948B')
    assert client.post(f"/api/coefficient-sets/{s948_v1['id']}/confirm",
                       json={}).json()['archived_set_id'] is None

    # A different phone of the same vehicle type is a different key
    pixel = draft('legacy_pixel', phone_model='google Pixel 9')
    assert client.post(f"/api/coefficient-sets/{pixel['id']}/confirm",
                       json={}).json()['archived_set_id'] is None

    # A half identity keeps the full key too (device_id is part of it), so it
    # never archives the legacy set it otherwise shares vehicle+phone with
    half = draft('half_identity', phone_model='samsung SM-S948B',
                 device_id=DEVICE_ID)
    assert client.post(f"/api/coefficient-sets/{half['id']}/confirm",
                       json={}).json()['archived_set_id'] is None

    # Same full key as the first set: that one, and only that one, is archived
    s948_v2 = draft('legacy_s948_v2', phone_model='samsung SM-S948B')
    assert client.post(f"/api/coefficient-sets/{s948_v2['id']}/confirm",
                       json={}).json()['archived_set_id'] == s948_v1['id']

    statuses = {s['name']: s['status'] for s in client.get('/api/coefficient-sets').json()}
    assert statuses == {'legacy_s948_v1': 'archived', 'legacy_pixel': 'confirmed',
                        'half_identity': 'confirmed', 'legacy_s948_v2': 'confirmed'}


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
