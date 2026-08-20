import os
from pathlib import Path

from tests.conftest import build_form_xlsx


def _upload(client, tmp_path, name='form.xlsx', **kwargs):
    p = build_form_xlsx(tmp_path / name, **kwargs)
    with open(p, 'rb') as f:
        return client.post('/api/references', files={'file': (name, f)},
                           data={'measured_at': '2026-08-20'})


def test_upload_list_detail(client, tmp_path):
    r = _upload(client, tmp_path)
    assert r.status_code == 201
    body = r.json()
    assert body['road_name'] == 'Т-9999' and body['step_m'] == 10
    assert body['measured_at'] == '2026-08-20'
    assert body['intervals_count'] == 12 and len(body['parse_warnings']) >= 1
    assert client.get('/api/references').json()[0]['id'] == body['id']
    assert client.get(f"/api/references/{body['id']}").status_code == 200
    assert (Path(os.environ['RQA_REFERENCE_DIR']) / str(body['id']) / 'intervals_10m.csv').is_file()


def test_upload_duplicate_409_and_bad_422(client, tmp_path):
    assert _upload(client, tmp_path).status_code == 201
    assert _upload(client, tmp_path).status_code == 409
    import openpyxl
    bad = tmp_path / 'bad.xlsx'
    wb = openpyxl.Workbook(); wb.active.cell(row=1, column=1, value='x'); wb.save(bad)
    with open(bad, 'rb') as f:
        assert client.post('/api/references', files={'file': ('bad.xlsx', f)}).status_code == 422


def test_delete_keeps_row_marks_deleted(client, tmp_path):
    ref_id = _upload(client, tmp_path).json()['id']
    assert client.delete(f'/api/references/{ref_id}').status_code == 204
    body = client.get(f'/api/references/{ref_id}').json()
    assert body['source_deleted'] is True


def test_disk_write_failure_leaves_no_orphaned_row(client, tmp_path, monkeypatch):
    """A disk failure after the row is committed must not leave a dangling
    ReferenceDataset row (which would 409-block every re-upload forever while
    nothing exists on disk)."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from src.db.models import ReferenceDataset
    from src.services import references as references_service

    original_copy = references_service.shutil.copy

    def failing_copy(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(references_service.shutil, 'copy', failing_copy)

    # The default client raises unhandled server exceptions into the test;
    # this one needs the actual 500 response instead.
    lenient = TestClient(client.app, raise_server_exceptions=False)
    p = build_form_xlsx(tmp_path / 'form.xlsx')
    with open(p, 'rb') as f:
        r = lenient.post('/api/references', files={'file': ('form.xlsx', f)})
    assert r.status_code == 500

    with Session(client.app.state.engine) as s:
        assert s.query(ReferenceDataset).count() == 0
    ref_root = Path(os.environ['RQA_REFERENCE_DIR'])
    assert not ref_root.exists() or not any(ref_root.iterdir())

    monkeypatch.setattr(references_service.shutil, 'copy', original_copy)
    assert _upload(client, tmp_path, name='form.xlsx').status_code == 201
