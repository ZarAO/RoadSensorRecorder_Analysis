from tests.helpers import make_probe_csv


def _upload(client, path, name='drive.csv'):
    with open(path, 'rb') as fh:
        return client.post('/api/files', files={'file': (name, fh, 'text/csv')})


def test_upload_list_delete_cycle(client, tmp_path):
    r = _upload(client, make_probe_csv(tmp_path))
    assert r.status_code == 201
    body = r.json()
    assert body['filename'] == 'drive.csv' and body['runs_count'] == 0
    assert body['recording_meta']['vehicle']['vehicle_type'] == 'sedan'
    assert body['recording_meta']['clean_stop'] is True
    assert 1.9 < body['duration_s'] <= 2.1

    listed = client.get('/api/files').json()
    assert len(listed) == 1 and listed[0]['id'] == body['id']

    assert client.delete(f"/api/files/{body['id']}").status_code == 204
    after = client.get('/api/files').json()
    assert after[0]['source_deleted'] is True


def test_upload_rejects_bad_contract(client, tmp_path):
    p = tmp_path / 'bad.csv'
    p.write_text('Time,Kind\n1,x\n', encoding='utf-8')
    r = _upload(client, p, 'bad.csv')
    assert r.status_code == 422
    assert client.get('/api/files').json() == []


def test_duplicate_filename_conflict(client, tmp_path):
    p = make_probe_csv(tmp_path)
    assert _upload(client, p).status_code == 201
    assert _upload(client, p).status_code == 409


def test_delete_unknown_file_404(client):
    assert client.delete('/api/files/999').status_code == 404
