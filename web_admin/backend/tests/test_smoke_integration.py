"""
End-to-end smoke: upload a real synthetic drive, run the REAL analyze()
through the API, verify artifacts and aggregates. Marked slow (~30 s).
"""

import json

import numpy as np
import pandas as pd
import pytest

G0 = 9.80665
ANCHOR_MS = 1753796576000
# Same Earth radius as the analyzer's compute_gps_distance (R = 6371 km)
METERS_PER_DEG_LAT = 6371000.0 * np.pi / 180.0


def write_real_drive(tmp_path, duration_s=40.0, fs=100.0, speed_mps=15.0):
    """Phone flat in a car driving due north with in-band excitation."""
    t = np.arange(0.0, duration_s, 1.0 / fs)
    excitation = 0.4 * np.sin(2 * np.pi * 2.3 * t) + 0.15 * np.sin(2 * np.pi * 4.7 * t)

    frames = [pd.DataFrame({
        'Time': ANCHOR_MS + np.round(t * 1000.0).astype(np.int64),
        'Type': 'Accelerometer',
        'X': 0.0, 'Y': 0.0, 'Z': G0 + excitation,
        'Latitude': np.nan, 'Longitude': np.nan,
    })]
    gps_t = np.arange(0.0, duration_s + 1e-9, 1.0)
    frames.append(pd.DataFrame({
        'Time': ANCHOR_MS + np.round(gps_t * 1000.0).astype(np.int64),
        'Type': 'Location', 'X': np.nan, 'Y': np.nan, 'Z': np.nan,
        'Latitude': 50.4 + speed_mps * gps_t / METERS_PER_DEG_LAT,
        'Longitude': 30.5,
    }))
    df = pd.concat(frames, ignore_index=True).sort_values('Time', kind='mergesort')

    path = tmp_path / 'real_drive.csv'
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write("# schema=2\n# vehicle_type=sedan\n# vehicle_make_model=Skoda Octavia\n")
        df[['Time', 'Type', 'X', 'Y', 'Z', 'Latitude', 'Longitude']].to_csv(f, index=False)
        f.write("# event: t=1753796581000, type=gps_lost, age_s=12\n")
        f.write("# end: duration_ms=40000, rows_accel=4000, rows_gyro=0, "
                "rows_gps=41, events=1, battery_end_pct=80, reason=user\n")
    return str(path)


@pytest.mark.slow
def test_full_cycle_through_real_analyzer(client, tmp_path):
    path = write_real_drive(tmp_path)
    with open(path, 'rb') as fh:
        up = client.post('/api/files', files={'file': ('real_drive.csv', fh, 'text/csv')})
    assert up.status_code == 201
    assert up.json()['recording_meta']['vehicle']['vehicle_type'] == 'sedan'

    rid = client.post('/api/runs', json={
        'file_id': up.json()['id'], 'params': {'low_speed_policy': 'invalid'}
    }).json()['id']
    run = client.get(f'/api/runs/{rid}').json()
    assert run['status'] == 'done', run.get('error')

    summary = run['summary']
    assert summary['segments_total'] >= 4
    assert summary['km_total'] == pytest.approx(0.6, abs=0.15)
    assert summary['vehicle_type'] == 'sedan'
    assert summary['clean_stop'] is True
    assert summary['incidents_total'] == 1

    for name in ('road_segments.csv', 'recording_meta.json', 'report.md',
                 'segments_map.html', 'roughness.geojson'):
        assert client.get(f'/api/runs/{rid}/artifacts/{name}').status_code == 200, name

    rows = client.get(f'/api/runs/{rid}/segments').json()
    assert len(rows) == summary['segments_total']

    fc = client.post('/api/global-map/rebuild').json()
    assert {f['properties']['run_id'] for f in fc['features']} == {rid}

    report = client.get(f'/api/runs/{rid}/artifacts/report.md').text
    assert '## Vehicle Profile' in report and 'Skoda Octavia' in report
