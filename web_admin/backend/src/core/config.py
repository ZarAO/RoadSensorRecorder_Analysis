"""
Backend settings. Paths default to the monorepo storage/ layout; the RQA_*
environment variables override them (tests point at tmp dirs, a future host
points at its own volume).
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# .../RoadSensorRecorder_Analysis (this file: web_admin/backend/src/core/config.py)
REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class Settings:
    storage_data_dir: Path
    storage_results_dir: Path
    storage_reference_dir: Path
    db_url: str

    def ensure_dirs(self) -> None:
        self.storage_data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_results_dir.mkdir(parents=True, exist_ok=True)
        self.storage_reference_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    data_dir = Path(os.environ.get('RQA_DATA_DIR', REPO_ROOT / 'storage' / 'data'))
    results_dir = Path(os.environ.get('RQA_RESULTS_DIR', REPO_ROOT / 'storage' / 'results'))
    reference_dir = Path(os.environ.get('RQA_REFERENCE_DIR', REPO_ROOT / 'storage' / 'reference'))
    default_db = f"sqlite:///{Path(__file__).resolve().parents[2] / 'admin.db'}"
    return Settings(
        storage_data_dir=data_dir,
        storage_results_dir=results_dir,
        storage_reference_dir=reference_dir,
        db_url=os.environ.get('RQA_DB_URL', default_db),
    )
