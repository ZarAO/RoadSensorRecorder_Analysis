from pathlib import Path

from sqlalchemy.orm import Session

from tests.conftest import _make_reference, _make_run_artifacts


def _make_done_run_and_reference(client, tmp_path, run_result_name='run_art'):
    """Arranges a done run with usable artifacts and a matching 10 m reference
    (mirrors test_comparison_service.py's arrange code)."""
    from src.core.config import get_settings
    from src.db.models import AnalysisRun, ReferenceDataset, SourceFile

    engine = client.app.state.engine
    settings = get_settings()
    with Session(engine) as s:
        f = SourceFile(filename='syn.csv', size_bytes=1)
        s.add(f)
        s.commit()
        run = AnalysisRun(file_id=f.id, status='done',
                          result_dir=str(tmp_path / run_result_name))
        ref = ReferenceDataset(filename='syn.xlsx', road_name='Т-9999', step_m=10.0,
                               intervals_count=100, chainage_span_m=1000.0,
                               bbox=[50.0, 30.4, 50.01, 30.6], parse_warnings=[])
        s.add_all([run, ref])
        s.commit()
        _make_run_artifacts(Path(run.result_dir))
        _make_reference(settings.storage_reference_dir / str(ref.id))
        run_id, ref_id = run.id, ref.id
    return run_id, ref_id


def test_comparison_flow_and_artifacts(client, tmp_path):
    run_id, ref_id = _make_done_run_and_reference(client, tmp_path)

    r = client.post('/api/comparisons', json={'run_id': run_id, 'reference_id': ref_id})
    assert r.status_code == 201, r.text
    cmp_id = r.json()['id']

    done = client.get(f'/api/comparisons/{cmp_id}').json()   # RQA_QUEUE_INLINE=1 -> already done
    assert done['status'] == 'done' and done['summary']['n_pairs'] >= 5
    assert done['reference_road'] == 'Т-9999'
    assert done['run_filename'] == 'syn.csv'

    listing = client.get(f'/api/comparisons?run_id={run_id}').json()
    assert [c['id'] for c in listing] == [cmp_id]

    stats = client.get(f'/api/comparisons/{cmp_id}/artifacts/stats.json')
    assert stats.status_code == 200
    assert client.get(f'/api/comparisons/{cmp_id}/artifacts/../secret').status_code in (403, 404)


def test_comparison_create_validations(client, tmp_path):
    run_id, ref_id = _make_done_run_and_reference(client, tmp_path)

    assert client.post('/api/comparisons',
                       json={'run_id': 9999, 'reference_id': ref_id}).status_code == 404
    assert client.post('/api/comparisons',
                       json={'run_id': run_id, 'reference_id': 9999}).status_code == 404

    from src.core.config import get_settings
    from src.db.models import AnalysisRun, ReferenceDataset, SourceFile

    engine = client.app.state.engine
    with Session(engine) as s:
        f = SourceFile(filename='queued.csv', size_bytes=1)
        s.add(f)
        s.commit()
        queued_run = AnalysisRun(file_id=f.id, status='queued')
        s.add(queued_run)
        s.commit()
        queued_run_id = queued_run.id
    r = client.post('/api/comparisons',
                    json={'run_id': queued_run_id, 'reference_id': ref_id})
    assert r.status_code == 409

    with Session(engine) as s:
        bad_ref = ReferenceDataset(filename='bad.xlsx', road_name='X', step_m=100.0,
                                   intervals_count=10, chainage_span_m=1000.0,
                                   parse_warnings=[])
        s.add(bad_ref)
        s.commit()
        bad_ref_id = bad_ref.id
    r = client.post('/api/comparisons', json={'run_id': run_id, 'reference_id': bad_ref_id})
    assert r.status_code == 409

    with Session(engine) as s:
        deleted_ref = ReferenceDataset(filename='deleted.xlsx', road_name='Y', step_m=10.0,
                                       intervals_count=100, chainage_span_m=1000.0,
                                       parse_warnings=[], source_deleted=True)
        s.add(deleted_ref)
        s.commit()
        deleted_ref_id = deleted_ref.id
    r = client.post('/api/comparisons', json={'run_id': run_id, 'reference_id': deleted_ref_id})
    assert r.status_code == 409


def test_comparison_delete_removes_artifacts(client, tmp_path):
    run_id, ref_id = _make_done_run_and_reference(client, tmp_path)
    cmp_id = client.post('/api/comparisons',
                         json={'run_id': run_id, 'reference_id': ref_id}).json()['id']
    result_dir = client.get(f'/api/comparisons/{cmp_id}').json()['result_dir']
    assert Path(result_dir).exists()

    assert client.delete(f'/api/comparisons/{cmp_id}').status_code == 204
    assert not Path(result_dir).exists()
    assert client.get(f'/api/comparisons/{cmp_id}').status_code == 404


def test_run_deletion_cascades_to_comparisons(client, tmp_path):
    run_id, ref_id = _make_done_run_and_reference(client, tmp_path)
    cmp_id = client.post('/api/comparisons',
                         json={'run_id': run_id, 'reference_id': ref_id}).json()['id']
    result_dir = client.get(f'/api/comparisons/{cmp_id}').json()['result_dir']
    assert Path(result_dir).exists()

    assert client.delete(f'/api/runs/{run_id}').status_code == 204
    assert client.get(f'/api/comparisons/{cmp_id}').status_code == 404
    assert not Path(result_dir).exists()


def test_run_artifact_list(client, tmp_path):
    run_id, _ref_id = _make_done_run_and_reference(client, tmp_path)
    rows = client.get(f'/api/runs/{run_id}/artifact-list').json()
    names = {r['name'] for r in rows}
    assert 'road_segments.csv' in names and 'roughness.geojson' in names
    assert all(r['size_bytes'] > 0 for r in rows)
    assert [r['name'] for r in rows] == sorted(r['name'] for r in rows)


def test_run_artifact_list_404_without_result_dir(client, tmp_path):
    from src.db.models import AnalysisRun, SourceFile

    engine = client.app.state.engine
    with Session(engine) as s:
        f = SourceFile(filename='none.csv', size_bytes=1)
        s.add(f)
        s.commit()
        run = AnalysisRun(file_id=f.id, status='queued')
        s.add(run)
        s.commit()
        run_id = run.id
    assert client.get(f'/api/runs/{run_id}/artifact-list').status_code == 404
