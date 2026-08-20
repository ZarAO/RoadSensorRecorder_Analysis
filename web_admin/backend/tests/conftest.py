"""
Shared fixtures: every test app runs against tmp storage dirs and a tmp SQLite
file, injected through the RQA_* env overrides read by get_settings().
"""

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('RQA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('RQA_RESULTS_DIR', str(tmp_path / 'results'))
    monkeypatch.setenv('RQA_REFERENCE_DIR', str(tmp_path / 'reference'))
    monkeypatch.setenv('RQA_DB_URL', f"sqlite:///{tmp_path / 'admin.db'}")
    # Jobs run synchronously inside the request: assertions see final state
    monkeypatch.setenv('RQA_QUEUE_INLINE', '1')
    from src.core.config import get_settings
    get_settings.cache_clear()
    from src.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def build_form_xlsx(path, n_rows=12, step_m=10, road='Т-9999', lane=1, category=2,
                    direction='Прямий', duplicate_ch9_10=True, break_continuity_at=None):
    """Miniature profilometer form with the real sheet layout (header row 22)."""
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.cell(row=2, column=1, value="Об'єкт (ділянка):"); ws.cell(row=2, column=6, value=road)
    ws.cell(row=6, column=1, value='Технічна категорія'); ws.cell(row=6, column=6, value=category)
    ws.cell(row=6, column=10, value='Номер смуги руху:'); ws.cell(row=6, column=14, value=lane)
    ws.cell(row=7, column=1, value='Напрям руху:'); ws.cell(row=7, column=6, value=direction)
    header = ['км', 'м', 'км', 'м'] + [f'канал {i}' for i in range(1, 11)] + \
             ['широта', 'довгота', 'висота', 'широта', 'довгота', 'висота']
    for col, text in enumerate(header, start=1):
        ws.cell(row=22, column=col, value=text)
    for i in range(n_rows):
        start = i * step_m
        end = start + step_m + (5 if break_continuity_at == i else 0)
        iri = [1.0 + 0.1 * i + 0.01 * ch for ch in range(1, 9)]
        ch8 = iri[-1]
        iri += [ch8, ch8] if duplicate_ch9_10 else [ch8 + 0.5, ch8 + 0.6]
        row = [start // 1000, start % 1000, end // 1000, end % 1000, *iri,
               50.0 + i * 1e-4, 30.0 + i * 1e-4, 120.0,
               50.0 + (i + 1) * 1e-4, 30.0 + (i + 1) * 1e-4, 120.0]
        for col, v in enumerate(row, start=1):
            ws.cell(row=23 + i, column=col, value=v)
    wb.save(path)
    return path


def _make_run_artifacts(result_dir: Path, n_seg=10):
    """10 x 100 m segments heading north along lon=30.5; ~0.000899 deg per 100 m."""
    deg = 100.0 / 111_195.0
    rows, features = [], []
    for i in range(n_seg):
        lat0, lat1 = 50.0 + i * deg, 50.0 + (i + 1) * deg
        rows.append({'seg_id': i, 's_start': i * 100.0, 's_end': (i + 1) * 100.0,
                     'length_m': 100.0, 'grms': 0.5 + 0.02 * i,
                     'psd_sqrt_scalar': 0.010 + 0.001 * i,
                     'iri_psd_raw': 3.0, 'iri_psd': 3.0,
                     'iri_multi': 2.0 + 0.2 * i, 'mean_speed_kmh': 60.0,
                     'partial': False, 'speed_valid': True,
                     'low_speed_class': None, 'needs_class12_survey': False})
        coords = [[30.5, lat0], [30.5, (lat0 + lat1) / 2], [30.5, lat1]]
        features.append({'type': 'Feature', 'properties': {'seg_id': i},
                         'geometry': {'type': 'LineString', 'coordinates': coords}})
    result_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(result_dir / 'road_segments.csv', index=False)
    (result_dir / 'roughness.geojson').write_text(json.dumps(
        {'type': 'FeatureCollection', 'features': features}), encoding='utf-8')


def _make_reference(ref_dir: Path, n10=100):
    deg10 = 10.0 / 111_195.0
    rows = []
    for i in range(n10):
        chain = i * 10
        rows.append({'km_start': chain // 1000, 'm_start': chain % 1000,
                     'km_end': (chain + 10) // 1000, 'm_end': (chain + 10) % 1000,
                     **{f'iri_ch{c}': 2.0 + 0.002 * i for c in range(1, 11)},
                     'lat_start': 50.0 + i * deg10, 'lon_start': 30.5, 'alt_start': 120.0,
                     'lat_end': 50.0 + (i + 1) * deg10, 'lon_end': 30.5, 'alt_end': 120.0})
    ref_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(ref_dir / 'intervals_10m.csv', index=False,
                              encoding='utf-8', lineterminator='\n')
