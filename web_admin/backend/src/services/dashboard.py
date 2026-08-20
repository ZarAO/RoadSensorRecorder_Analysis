"""
Dashboard aggregation over the latest done run of each non-deleted file.
Totals come from run summaries; the histogram and worst list read the
segment CSVs (few local files — no caching needed).
"""

from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import AnalysisRun, SourceFile
from src.services.global_map import _latest_done_run

IRI_BIN_EDGES = [float(x) for x in range(0, 13)]  # 1 m/km bins, 0..12


def build_dashboard(session: Session) -> dict:
    files = session.scalars(select(SourceFile)).all()
    runs_done = session.scalars(
        select(AnalysisRun).where(AnalysisRun.status == 'done')
    ).all()

    km_total = 0.0
    low_speed_total = 0
    histogram = [{'bin_start': IRI_BIN_EDGES[i], 'bin_end': IRI_BIN_EDGES[i + 1],
                  'count': 0} for i in range(len(IRI_BIN_EDGES) - 1)]
    worst = []

    for f in files:
        run = _latest_done_run(f)
        if run is None:
            continue
        summary = run.summary or {}
        km_total += summary.get('km_total') or 0.0
        low_speed_total += summary.get('low_speed_count') or 0

        csv_path = Path(run.result_dir) / 'road_segments.csv'
        if not csv_path.is_file():
            continue
        segments = pd.read_csv(csv_path)
        valid = segments[(~segments['partial']) & (segments['speed_valid'])
                         & segments['iri_multi'].notna()]
        for iri in valid['iri_multi']:
            idx = min(int(iri), len(histogram) - 1) if iri >= 0 else 0
            histogram[idx]['count'] += 1

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

    worst.sort(key=lambda s: s['iri_psd'], reverse=True)
    return {
        'files_total': len(files),
        'runs_done': len(runs_done),
        'km_total': km_total,
        'low_speed_total': low_speed_total,
        'iri_histogram': histogram,
        'worst_segments': worst[:10],
    }
