"""
Dashboard aggregation, over two deliberately distinct populations (same at the
top level and per vehicle_type -- the per-type buckets must sum back to the
top-level totals, so the UI's chips partition «Всі»):

  - files_total / runs_done count ALL SourceFile rows and ALL 'done'
    AnalysisRun rows respectively -- every file (source_deleted or not, run or
    not) and every done run (re-runs included), with no dedup.
  - km_total / low_speed_total / mean_iri_multi / iri_histogram / the worst
    list are computed over only the LATEST done run of each file; the
    histogram and worst list additionally read the segment CSVs (few local
    files — no caching needed).

vehicle_type is read from SourceFile.recording_meta via
coefficients.vehicle_type_from_meta — the same per-file source
files-page.html already reads to show a file's vehicle type (not the run's
own recording_meta.json, which is a different, run-scoped artifact). Missing
vehicle_type maps to UNKNOWN_VEHICLE_TYPE.
"""

from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import AnalysisRun, SourceFile
from src.services.coefficients import vehicle_type_from_meta
from src.services.global_map import _latest_done_run

IRI_BIN_EDGES = [float(x) for x in range(0, 13)]  # 1 m/km bins, 0..12
UNKNOWN_VEHICLE_TYPE = 'невідомо'


def _empty_histogram() -> list[dict]:
    return [{'bin_start': IRI_BIN_EDGES[i], 'bin_end': IRI_BIN_EDGES[i + 1],
             'count': 0} for i in range(len(IRI_BIN_EDGES) - 1)]


def _new_type_bucket() -> dict:
    return {'files_total': 0, 'runs_done': 0, 'km_total': 0.0, 'low_speed_total': 0,
            'iri_histogram': _empty_histogram(), '_iri_sum': 0.0, '_iri_count': 0}


def build_dashboard(session: Session) -> dict:
    files = session.scalars(select(SourceFile)).all()
    runs_done = session.scalars(
        select(AnalysisRun).where(AnalysisRun.status == 'done')
    ).all()

    km_total = 0.0
    low_speed_total = 0
    histogram = _empty_histogram()
    worst = []
    by_type: dict[str, dict] = {}

    def _bucket(vehicle_type: str) -> dict:
        return by_type.setdefault(vehicle_type, _new_type_bucket())

    for f in files:
        vehicle_type = vehicle_type_from_meta(f.recording_meta) or UNKNOWN_VEHICLE_TYPE
        # files_total mirrors the global population exactly: every file, run
        # or not (same as len(files) below) -- counted regardless of whether
        # the stats loop below finds a done run for it.
        _bucket(vehicle_type)['files_total'] += 1

        run = _latest_done_run(f)
        if run is None:
            continue
        summary = run.summary or {}
        run_km = summary.get('km_total') or 0.0
        run_low_speed = summary.get('low_speed_count') or 0
        km_total += run_km
        low_speed_total += run_low_speed

        bucket = _bucket(vehicle_type)
        bucket['km_total'] += run_km
        bucket['low_speed_total'] += run_low_speed

        csv_path = Path(run.result_dir) / 'road_segments.csv'
        if not csv_path.is_file():
            continue
        segments = pd.read_csv(csv_path)
        valid = segments[(~segments['partial']) & (segments['speed_valid'])
                         & segments['iri_multi'].notna()]
        for iri in valid['iri_multi']:
            idx = min(int(iri), len(histogram) - 1) if iri >= 0 else 0
            histogram[idx]['count'] += 1
            bucket['iri_histogram'][idx]['count'] += 1
        bucket['_iri_sum'] += float(valid['iri_multi'].sum())
        bucket['_iri_count'] += len(valid)

        by_psd = segments[segments['iri_psd'].notna()]
        for _, row in by_psd.iterrows():
            worst.append({
                'run_id': run.id,
                'filename': f.filename,
                'seg_id': int(row['seg_id']),
                'iri_psd': float(row['iri_psd']),
                'iri_multi': None if pd.isna(row['iri_multi']) else float(row['iri_multi']),
                'needs_class12_survey': bool(row['needs_class12_survey']),
            })

    # runs_done per type mirrors the global population exactly: every 'done'
    # AnalysisRun row, including re-runs of the same file -- NOT deduped to
    # the latest one (that dedup only applies to the stats loop above).
    for r in runs_done:
        vehicle_type = vehicle_type_from_meta(
            r.file.recording_meta if r.file else None) or UNKNOWN_VEHICLE_TYPE
        _bucket(vehicle_type)['runs_done'] += 1

    worst.sort(key=lambda s: s['iri_psd'], reverse=True)

    by_vehicle_type = {
        vt: {
            'files_total': b['files_total'],
            'runs_done': b['runs_done'],
            'km_total': b['km_total'],
            'low_speed_total': b['low_speed_total'],
            'mean_iri_multi': (b['_iri_sum'] / b['_iri_count']) if b['_iri_count'] else None,
            'iri_histogram': b['iri_histogram'],
        }
        for vt, b in by_type.items()
    }

    return {
        'files_total': len(files),
        'runs_done': len(runs_done),
        'km_total': km_total,
        'low_speed_total': low_speed_total,
        'iri_histogram': histogram,
        'worst_segments': worst[:10],
        'by_vehicle_type': by_vehicle_type,
    }
