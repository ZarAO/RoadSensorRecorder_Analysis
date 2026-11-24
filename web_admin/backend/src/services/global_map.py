"""
Global map: merge roughness.geojson of the latest done run of every
non-deleted file into one FeatureCollection cached on disk.
"""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import Settings
from src.db.models import SourceFile

GLOBAL_MAP_NAME = 'global_map.geojson'


def _latest_done_run(file: SourceFile):
    done = [r for r in file.runs if r.status == 'done' and r.result_dir]
    return max(done, key=lambda r: r.id) if done else None


def _map_sources(session: Session) -> list:
    """(file, its latest done run, that run's roughness.geojson) the map is built from."""
    sources = []
    files = session.scalars(
        select(SourceFile).where(SourceFile.source_deleted.is_(False))
    ).all()
    for f in files:
        run = _latest_done_run(f)
        if run is None:
            continue
        geojson_path = Path(run.result_dir) / 'roughness.geojson'
        if geojson_path.is_file():
            sources.append((f, run, geojson_path))
    return sources


def rebuild_global_map(session: Session, settings: Settings) -> dict:
    features = []
    sources = _map_sources(session)
    for f, run, geojson_path in sources:
        fc = json.loads(geojson_path.read_text(encoding='utf-8'))
        for feature in fc.get('features', []):
            feature.setdefault('properties', {}).update(
                run_id=run.id, file_id=f.id, filename=f.filename)
            features.append(feature)

    # run_ids (a GeoJSON foreign member, ignored by map clients) records what the
    # cache was built from, so load_global_map can tell when it is out of date
    merged = {'type': 'FeatureCollection', 'features': features,
              'run_ids': sorted(run.id for _, run, _ in sources)}
    out_path = settings.storage_results_dir / GLOBAL_MAP_NAME
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, ensure_ascii=False), encoding='utf-8')
    return merged


def load_global_map(session: Session, settings: Settings) -> dict:
    """The cached map, rebuilt when the latest done runs changed since it was
    built (a new or re-analysed file, a deleted one) or when it predates the
    run_ids record."""
    out_path = settings.storage_results_dir / GLOBAL_MAP_NAME
    if out_path.is_file():
        cached = json.loads(out_path.read_text(encoding='utf-8'))
        current = sorted(run.id for _, run, _ in _map_sources(session))
        if cached.get('run_ids') == current:
            return cached
    return rebuild_global_map(session, settings)
