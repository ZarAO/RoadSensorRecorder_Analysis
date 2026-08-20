"""
Reference dataset storage: persists a ReferenceDataset row from an already
-parsed profilometer form, then writes the parsed artifacts to
storage_reference_dir/<id>/ (original.xlsx + intervals_{step_m}m.csv).

Parsing (parse_form_xlsx) is the caller's job: it maps to 422 on ValueError
and must run before store_reference, so that any failure here — after the
row is committed — is a persistence error, not a parse error (see references.py).
"""

import json
import shutil
from pathlib import Path

import pandas as pd
from fastapi import HTTPException
from profilometer_validation.match import REFERENCE_CHANNELS

from src.core.config import Settings
from src.db.models import ReferenceDataset
from src.services.reference_forms import ParsedForm

INTERVALS_GEOJSON_NAME = 'intervals.geojson'


def reference_dir(settings: Settings, ref: ReferenceDataset) -> Path:
    return settings.storage_reference_dir / str(ref.id)


def intervals_csv_path(settings: Settings, ref: ReferenceDataset) -> Path:
    """The single source of truth for the stored intervals CSV's path — used
    when writing it (store_reference), reading it (load_reference_intervals)
    and by comparison.py's own pre-flight check, so the filename convention
    lives in exactly one place."""
    return reference_dir(settings, ref) / f'intervals_{int(ref.step_m)}m.csv'


def store_reference(session, settings: Settings, form: ParsedForm, tmp_xlsx: Path, original_name: str,
                     measured_at: str | None, road_name: str | None) -> ReferenceDataset:
    row = ReferenceDataset(
        filename=original_name,
        road_name=road_name or form.road_name,
        direction=form.direction,
        lane=form.lane,
        category=form.category,
        step_m=form.step_m,
        measured_at=measured_at,
        intervals_count=len(form.intervals),
        chainage_span_m=form.chainage_span_m,
        bbox=form.bbox,
        parse_warnings=form.warnings,
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    ref_dir = reference_dir(settings, row)
    try:
        ref_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(tmp_xlsx), ref_dir / 'original.xlsx')
        form.intervals.to_csv(
            intervals_csv_path(settings, row),
            index=False, encoding='utf-8', lineterminator='\n',
        )
    except OSError:
        # Row is already committed with the unique filename; an orphaned row
        # would block every re-upload with a false 409 while nothing exists
        # on disk. Undo the row and any partial dir, then let the caller see
        # the original failure.
        session.delete(row)
        session.commit()
        shutil.rmtree(ref_dir, ignore_errors=True)
        raise
    return row


def delete_reference_data(settings: Settings, ref: ReferenceDataset) -> None:
    shutil.rmtree(reference_dir(settings, ref), ignore_errors=True)


def load_reference_intervals(settings: Settings, ref: ReferenceDataset) -> pd.DataFrame:
    """The stored intervals_{step_m}m.csv plus iri_ref = mean(ch1..ch8) — never
    ch9/10, which duplicate ch8 (profilometer_validation.match.REFERENCE_CHANNELS)."""
    csv_path = intervals_csv_path(settings, ref)
    if not csv_path.is_file():
        raise HTTPException(404, 'intervals file not found')
    df = pd.read_csv(csv_path, encoding='utf-8')
    df['iri_ref'] = df[REFERENCE_CHANNELS].mean(axis=1)
    return df


def build_reference_geojson(settings: Settings, ref: ReferenceDataset) -> dict:
    """FeatureCollection of interval LineStrings, cached at
    reference_dir/intervals.geojson — intervals are immutable after upload,
    so the cache never needs invalidation."""
    cache_path = reference_dir(settings, ref) / INTERVALS_GEOJSON_NAME
    if cache_path.is_file():
        return json.loads(cache_path.read_text(encoding='utf-8'))

    df = load_reference_intervals(settings, ref)
    chain_start = df['km_start'] * 1000.0 + df['m_start']
    chain_end = df['km_end'] * 1000.0 + df['m_end']
    features = [
        {
            'type': 'Feature',
            'properties': {
                'interval_id': int(idx),
                'chainage_m': float((chain_start[idx] + chain_end[idx]) / 2.0),
                'iri_ref': float(row['iri_ref']) if pd.notna(row['iri_ref']) else None,
            },
            'geometry': {
                'type': 'LineString',
                'coordinates': [
                    [float(row['lon_start']), float(row['lat_start'])],
                    [float(row['lon_end']), float(row['lat_end'])],
                ],
            },
        }
        for idx, row in df.iterrows()
    ]
    fc = {'type': 'FeatureCollection', 'features': features}
    # allow_nan=False: a hypothetical NaN slipping through must fail loudly at
    # build time, not get serialized as invalid JSON and poison the cache file.
    cache_path.write_text(json.dumps(fc, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return fc
