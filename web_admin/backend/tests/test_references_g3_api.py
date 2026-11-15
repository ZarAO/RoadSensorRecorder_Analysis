"""POST /api/references/g3: a road section from Walking Profiler G3 passes,
each pass one channel (spec 2026-11-15-g3-section-reference-design.md)."""

import os
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from tests.conftest import _make_run_artifacts

BOM = chr(0xFEFF)
DX = 0.025
M_PER_DEG = 111_195.0


def _g3_files(prefix, title, date_time, length_m=1000.0, reverse=False, seed=7):
    """Device-format files of one pass along lon=30.5 heading north from lat 50.0
    (the same line as tests.conftest._make_run_artifacts)."""
    rng = np.random.default_rng(seed)
    n = int(round(length_m / DX)) + 1
    elevation = np.cumsum(rng.normal(0, 0.4, n))
    iri = 2.0 + np.linspace(0, 2, int(length_m))
    if reverse:
        elevation, iri = elevation[::-1], iri[::-1]
    profile = 'Distance(m),Profile(mm)\r\n' + '\r\n'.join(
        f'{i * DX:.3f},{v - elevation[0]:.3f}' for i, v in enumerate(elevation))
    iri_text = 'Distance(m),IRI(m/km)\r\n' + '\r\n'.join(
        f'{k + 1:.3f},{v:.3f}' for k, v in enumerate(iri))
    rows = []
    for k in range(int(length_m) + 1):
        x = length_m - k if reverse else k
        rows.append(f'{k:.3f},3,50,{50.0 + x / M_PER_DEG:.8f},30.50000000,150,0')
    gnss = BOM + 'Distance(m),Speed(km/h),Latitude,Longitude,Altitude(m),Bearing\r\n' + '\r\n'.join(rows)
    info = (BOM + f'Title: {title}\r\nDate/Time: {date_time}\r\nQuality Setting: Fast Profiling\r\n'
            f'Surface: Asphalt\r\nField Offset Calibration Date/Time : {date_time}\r\n')
    return {f'{prefix} IRI.csv': iri_text, f'{prefix} GNSS.csv': gnss,
            f'{prefix} Profile.csv': profile, f'{prefix} Information.txt': info}


def _two_passes():
    return {**_g3_files('2026-11-14 14h25m55s Zao_5', 'Zao_5', '2026-11-14 14:25:55'),
            **_g3_files('2026-11-14 14h32m40s Zao_7', 'Zao_7', '2026-11-14 14:32:40', reverse=True)}


def _post(client, files: dict, road_name='Тестова ділянка', **data):
    payload = [('files', (name, text.encode('utf-8'))) for name, text in files.items()]
    return client.post('/api/references/g3', files=payload, data={'road_name': road_name, **data})


def test_upload_g3_section_reference(client):
    r = _post(client, _two_passes())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body['kind'] == 'walking_profiler_g3'
    assert body['filename'] == 'G3 2026-11-14 Zao_5+Zao_7'
    assert body['measured_at'] == '2026-11-14' and body['step_m'] == 10
    assert body['intervals_count'] == 100 and body['chainage_span_m'] == 1000.0
    assert [c['survey'] for c in body['channels']] == ['Zao_5', 'Zao_7']
    assert body['channels'][1]['direction'] == 'reverse'
    assert body['channels'][1]['alignment'] == 'profile'

    ref_dir = Path(os.environ['RQA_REFERENCE_DIR']) / str(body['id'])
    assert (ref_dir / 'intervals_10m.csv').is_file()
    assert len(list((ref_dir / 'source').iterdir())) == 8

    rows = client.get(f"/api/references/{body['id']}/intervals").json()
    first = rows[5]
    assert first['iri_ch3'] is None
    assert first['iri_ref'] == np.mean([first['iri_ch1'], first['iri_ch2']])


def test_old_rows_report_profilometer_kind(client, tmp_path):
    from tests.conftest import build_form_xlsx
    p = build_form_xlsx(tmp_path / 'form.xlsx')
    with open(p, 'rb') as f:
        body = client.post('/api/references', files={'file': ('form.xlsx', f)}).json()
    assert body['kind'] == 'profilometer_form' and body['channels'] is None


def test_upload_g3_validation_errors(client):
    files = _two_passes()
    no_profile = {k: v for k, v in files.items() if not k.endswith('Zao_7 Profile.csv')}
    r = _post(client, no_profile)
    assert r.status_code == 422
    assert 'Zao_7' in r.json()['detail'] and 'profile' in r.json()['detail']

    r = _post(client, {**files, 'notes.docx': 'x'})
    assert r.status_code == 422 and 'notes.docx' in r.json()['detail']

    assert _post(client, files, road_name='  ').status_code == 422

    assert _post(client, files).status_code == 201
    assert _post(client, files).status_code == 409


def test_comparison_accepts_g3_reference(client, tmp_path):
    from src.db.models import AnalysisRun, SourceFile

    ref_id = _post(client, _two_passes()).json()['id']
    with Session(client.app.state.engine) as s:
        f = SourceFile(filename='syn.csv', size_bytes=1)
        s.add(f)
        s.commit()
        run = AnalysisRun(file_id=f.id, status='done', result_dir=str(tmp_path / 'run_art'))
        s.add(run)
        s.commit()
        _make_run_artifacts(Path(run.result_dir))
        run_id = run.id

    r = client.post('/api/comparisons', json={'run_id': run_id, 'reference_id': ref_id})
    assert r.status_code == 201, r.text
    done = client.get(f"/api/comparisons/{r.json()['id']}").json()
    assert done['status'] == 'done', done.get('error')
    assert done['summary']['n_pairs'] >= 5

    pairs = pd.read_csv(Path(done['result_dir']) / 'matched_pairs.csv')
    assert pairs['iri_ref'].between(2.0, 4.0).all()
