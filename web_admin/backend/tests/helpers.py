"""
Shared test data builders for backend tests.
"""


def make_probe_csv(tmp_path, name='drive.csv', preamble=True):
    """
    Tiny contract-v2 CSV: 200 accel rows @ 100 Hz + 3 GPS rows over 2 s,
    with a v3 vehicle line and a clean-stop footer when preamble=True.
    """
    rows = ["Time,Type,X,Y,Z,Latitude,Longitude"]
    for i in range(200):
        rows.append(f"{1753796576000 + i * 10},Accelerometer,0.0,0.0,9.81,,")
    for i in range(3):
        rows.append(f"{1753796576000 + i * 1000},Location,,,,50.4{i},30.5")
    text = ""
    if preamble:
        text += "# schema=2\n# vehicle_type=sedan\n"
    text += "\n".join(rows) + "\n"
    if preamble:
        text += ("# end: duration_ms=2000, rows_accel=200, rows_gyro=0, "
                 "rows_gps=3, events=0, battery_end_pct=90, reason=user\n")
    p = tmp_path / name
    p.write_text(text, encoding='utf-8')
    return str(p)


def upload_probe_csv(client, tmp_path, name='drive.csv'):
    path = make_probe_csv(tmp_path, name=name)
    with open(path, 'rb') as fh:
        r = client.post('/api/files', files={'file': (name, fh, 'text/csv')})
    assert r.status_code == 201, r.text
    return r.json()
