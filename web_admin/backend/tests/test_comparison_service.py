import json
import numpy as np
import pandas as pd
from pathlib import Path
from sqlalchemy.orm import Session


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


def test_execute_comparison_end_to_end(client, tmp_path):
    import os
    from src.core.config import get_settings
    from src.db.models import AnalysisRun, Comparison, ReferenceDataset, SourceFile
    from src.services.comparison import execute_comparison
    engine = client.app.state.engine
    settings = get_settings()
    with Session(engine) as s:
        f = SourceFile(filename='syn.csv', size_bytes=1); s.add(f); s.commit()
        run = AnalysisRun(file_id=f.id, status='done',
                          result_dir=str(tmp_path / 'run_art'))
        ref = ReferenceDataset(filename='syn.xlsx', road_name='Т-9999', step_m=10.0,
                               intervals_count=100, chainage_span_m=1000.0,
                               bbox=[50.0, 30.4, 50.01, 30.6], parse_warnings=[])
        s.add_all([run, ref]); s.commit()
        _make_run_artifacts(Path(run.result_dir))
        _make_reference(settings.storage_reference_dir / str(ref.id))
        cmp_ = Comparison(run_id=run.id, reference_id=ref.id, params={})
        s.add(cmp_); s.commit(); cmp_id = cmp_.id

    execute_comparison(cmp_id, engine, settings)

    with Session(engine) as s:
        done = s.get(Comparison, cmp_id)
        assert done.status == 'done', done.error
        assert done.summary['n_pairs'] >= 5
        rd = Path(done.result_dir)
        for name in ('matched_pairs.csv', 'stats.json', 'chart_data.json'):
            assert (rd / name).is_file()
        assert list((rd / 'figures').glob('*.png'))
        chart = json.loads((rd / 'chart_data.json').read_text(encoding='utf-8'))
        assert {'scatter', 'profile', 'bland_altman', 'eq3_fit', 'bias'} <= set(chart)


def test_comparison_bbox_mismatch_fails_with_explanation(client, tmp_path):
    from src.core.config import get_settings
    from src.db.models import AnalysisRun, Comparison, ReferenceDataset, SourceFile
    from src.services.comparison import execute_comparison
    engine = client.app.state.engine
    with Session(engine) as s:
        f = SourceFile(filename='syn2.csv', size_bytes=1); s.add(f); s.commit()
        run = AnalysisRun(file_id=f.id, status='done',
                          result_dir=str(tmp_path / 'run2'))
        ref = ReferenceDataset(filename='far.xlsx', road_name='X', step_m=10.0,
                               intervals_count=100, chainage_span_m=1000.0,
                               bbox=[48.0, 20.0, 48.1, 20.1], parse_warnings=[])
        s.add_all([run, ref]); s.commit()
        _make_run_artifacts(Path(run.result_dir))
        _make_reference(get_settings().storage_reference_dir / str(ref.id))
        cmp_ = Comparison(run_id=run.id, reference_id=ref.id, params={})
        s.add(cmp_); s.commit(); cmp_id = cmp_.id
    execute_comparison(cmp_id, engine, get_settings())
    with Session(engine) as s:
        failed = s.get(Comparison, cmp_id)
        assert failed.status == 'failed' and 'перетинаються' in failed.error
