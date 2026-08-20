def test_health(client):
    r = client.get('/api/health')
    assert r.status_code == 200 and r.json() == {'status': 'ok'}


def test_settings_env_override(tmp_path, monkeypatch):
    from src.core.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv('RQA_DATA_DIR', str(tmp_path / 'd'))
    s = get_settings()
    assert s.storage_data_dir == tmp_path / 'd'
    get_settings.cache_clear()
