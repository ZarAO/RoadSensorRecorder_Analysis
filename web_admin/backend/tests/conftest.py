"""
Shared fixtures: every test app runs against tmp storage dirs and a tmp SQLite
file, injected through the RQA_* env overrides read by get_settings().
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('RQA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('RQA_RESULTS_DIR', str(tmp_path / 'results'))
    monkeypatch.setenv('RQA_DB_URL', f"sqlite:///{tmp_path / 'admin.db'}")
    from src.core.config import get_settings
    get_settings.cache_clear()
    from src.main import create_app
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()
