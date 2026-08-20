import json
from pathlib import Path
from sqlalchemy.orm import Session

from tests.conftest import _make_reference, _make_run_artifacts


def test_execute_comparison_end_to_end(client, tmp_path):
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


def test_geojson_bbox_handles_point_features(tmp_path):
    """The analyzer emits Point geometry (a flat [lon, lat] pair) for a segment
    with fewer than 2 grid points — the bbox must cover it, not crash."""
    from src.services.comparison import _geojson_bbox

    features = [
        {'type': 'Feature', 'properties': {},
         'geometry': {'type': 'LineString',
                      'coordinates': [[30.5, 50.0], [30.6, 50.1]]}},
        {'type': 'Feature', 'properties': {},
         'geometry': {'type': 'Point', 'coordinates': [30.4, 50.2]}},
        {'type': 'Feature', 'properties': {},
         'geometry': {'type': 'LineString', 'coordinates': []}},
    ]
    p = tmp_path / 'mixed.geojson'
    p.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}),
                 encoding='utf-8')

    assert _geojson_bbox(p) == (50.0, 30.4, 50.2, 30.6)


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
