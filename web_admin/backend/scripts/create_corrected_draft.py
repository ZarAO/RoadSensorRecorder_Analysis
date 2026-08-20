"""
One-off data fix: draft the corrected van coefficient set.

The confirmed set 'eq6_bias_van_2026-08-20' carries a hand-typed phone_model
('zarichnyi-samsung-s26u') while the recorded device is 'samsung SM-S948B', so
it matches neither the exact-phone tier (string mismatch) nor the vehicle tier
(which requires phone_model IS NULL) — it can never resolve for any file.

This script creates the corrected DRAFT through the API against the real
admin.db, so every invariant of POST /api/coefficient-sets applies, and prints
which files the new key would apply to. The draft is deliberately left
UNCONFIRMED: activating a coefficient set is a human decision.

    cd web_admin/backend
    ../../.venv/Scripts/python.exe scripts/create_corrected_draft.py

Idempotent: a second run hits the duplicate-name 409 and exits 0.
"""

import sys
import time
from pathlib import Path

# Run as a script: the backend root (which holds src/) is not on sys.path yet
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from src.core.config import get_settings  # noqa: E402
from src.main import create_app  # noqa: E402

DRAFT = {
    'comparison_id': 2,
    'model': 'eq6_bias',
    'name': 'eq6_bias_van_SM-S948B_2026-08-20',
    'vehicle_type': 'van',
    'phone_model': 'samsung SM-S948B',
}

LOCKED = 'database is locked'


def _post(client: TestClient, path: str, payload: dict):
    """SQLite is single-writer: a uvicorn dev server holding the file can make
    the first write fail, and one short retry is enough."""
    try:
        response = client.post(path, json=payload)
    except OperationalError as exc:
        if LOCKED not in str(exc).lower():
            raise
        print(f'{LOCKED} — retrying in 2 s')
        time.sleep(2)
        return client.post(path, json=payload)
    if response.status_code >= 500 and LOCKED in response.text.lower():
        print(f'{LOCKED} — retrying in 2 s')
        time.sleep(2)
        return client.post(path, json=payload)
    return response


def main() -> int:
    print(f"db: {get_settings().db_url}")
    with TestClient(create_app()) as client:
        created = _post(client, '/api/coefficient-sets', DRAFT)
        if created.status_code == 409:
            # The 409 detail is the operator-facing Ukrainian message; this log
            # stays ASCII so a cp1252 console can print it
            print(f"draft '{DRAFT['name']}' already present (409 duplicate name)")
        elif created.status_code == 201:
            cs = created.json()
            print(f"created draft #{cs['id']} '{cs['name']}': status={cs['status']}, "
                  f"params={cs['params']}, vehicle_type={cs['vehicle_type']}, "
                  f"phone_model={cs['phone_model']}")
        else:
            print(f'FAILED {created.status_code}: {created.text}')
            return 1

        preview = _post(client, '/api/coefficient-sets/preview-resolution',
                        {'model': DRAFT['model'],
                         'vehicle_type': DRAFT['vehicle_type'],
                         'phone_model': DRAFT['phone_model']})
        print(f'preview-resolution {preview.status_code}: {preview.text}')

        print('coefficient sets on record (nothing was confirmed by this script):')
        for cs in client.get('/api/coefficient-sets').json():
            print(f"  #{cs['id']} {cs['name']}: status={cs['status']}, "
                  f"vehicle_type={cs['vehicle_type']}, phone_model={cs['phone_model']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
