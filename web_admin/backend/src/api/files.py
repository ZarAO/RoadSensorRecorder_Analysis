"""
Files API: upload (with immediate contract validation), list, delete.
Deleting a file keeps its runs and their artifacts (spec §4) — the row is
marked source_deleted and the CSV leaves storage/data/.
"""

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import FileCompareOut, FileOut
from src.core.config import get_settings
from src.db.models import AnalysisRun, SourceFile
from src.db.session import get_session
from src.services.coefficients import bias_of
from src.services.preview import probe_csv

router = APIRouter(prefix='/files', tags=['files'])

# Columns pulled from road_segments.csv for a run-vs-run comparison. s_start is
# not suffixed (both runs share the same seg_id grid — spec §Task 7); the rest
# get an _a/_b suffix from the merge.
_COMPARE_COLS = ['seg_id', 'iri_multi', 'iri_psd', 'grms', 'mean_speed_kmh']


def _to_out(f: SourceFile) -> FileOut:
    out = FileOut.model_validate(f)
    out.runs_count = len(f.runs)
    return out


@router.post('', status_code=201, response_model=FileOut)
def upload_file(file: UploadFile, session: Session = Depends(get_session)):
    settings = get_settings()
    filename = Path(file.filename or 'upload.csv').name

    existing = session.scalar(select(SourceFile).where(SourceFile.filename == filename))
    if existing is not None:
        raise HTTPException(409, f"файл '{filename}' вже існує")

    # Stream to a temp file first: a contract violation must leave storage/ clean
    with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        info = probe_csv(str(tmp_path))
    except ValueError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))

    target = settings.storage_data_dir / filename
    settings.storage_data_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_path), target)

    row = SourceFile(
        filename=filename,
        size_bytes=target.stat().st_size,
        duration_s=info['duration_s'],
        fs_hz=info['fs_hz'],
        gps_coverage_ratio=info['gps_coverage_ratio'],
        recording_meta=info['recording_meta'],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_out(row)


@router.get('', response_model=list[FileOut])
def list_files(session: Session = Depends(get_session)):
    files = session.scalars(
        select(SourceFile).order_by(SourceFile.uploaded_at.desc(), SourceFile.id.desc())
    ).all()
    return [_to_out(f) for f in files]


@router.delete('/{file_id}', status_code=204)
def delete_file(file_id: int, session: Session = Depends(get_session)):
    row = session.get(SourceFile, file_id)
    if row is None:
        raise HTTPException(404, 'File not found')
    settings = get_settings()
    (settings.storage_data_dir / row.filename).unlink(missing_ok=True)
    row.source_deleted = True
    session.commit()


def _read_compare_segments(run: AnalysisRun) -> pd.DataFrame:
    path = Path(run.result_dir or '') / 'road_segments.csv'
    if not path.is_file():
        raise HTTPException(404, 'road_segments.csv not found')
    df = pd.read_csv(path)
    return df[['s_start'] + _COMPARE_COLS]


def _apply_eq6_correction(df: pd.DataFrame, run: AnalysisRun) -> pd.DataFrame:
    """Controller ruling: compare must show what the run pages show, not the
    raw analyzer artifact. runs.get_segments applies the run's own eq6_bias
    snapshot (params.coefficients) to iri_multi before it reaches the UI, so
    this endpoint applies the SAME correction per side here, via the SAME
    bias_of() helper -- otherwise two runs differing only by a confirmed
    eq6_bias set would show a zero delta while their run pages differ by the
    bias. Raw values are untouched in the artifacts; NaN (a null iri_multi)
    propagates through the subtraction, so a null side stays null."""
    bias = bias_of((run.params or {}).get('coefficients'))
    if bias is not None:
        df = df.copy()
        df['iri_multi'] = df['iri_multi'] - bias
    return df


@router.get('/{file_id}/compare', response_model=FileCompareOut)
def compare_runs(file_id: int, run_a: int, run_b: int,
                 session: Session = Depends(get_session)):
    if session.get(SourceFile, file_id) is None:
        raise HTTPException(404, 'File not found')
    if run_a == run_b:
        raise HTTPException(409, 'оберіть два різні рани')
    ra = session.get(AnalysisRun, run_a)
    rb = session.get(AnalysisRun, run_b)
    if ra is None or rb is None:
        raise HTTPException(404, 'Run not found')
    if ra.file_id != file_id or rb.file_id != file_id:
        raise HTTPException(409, 'ран не належить цьому файлу')
    if ra.status != 'done' or rb.status != 'done':
        raise HTTPException(409, 'обидва рани мають бути завершені')

    df_a = _apply_eq6_correction(_read_compare_segments(ra), ra)
    df_b = _apply_eq6_correction(_read_compare_segments(rb), rb)

    segments_total = len(set(df_a['seg_id']) | set(df_b['seg_id']))
    # Same file -> identical seg_id grids unless low_speed_policy differs, in
    # which case a policy may drop a segment from the artifacts entirely: the
    # inner join then matches fewer rows than the union above (no error).
    merged = df_a.merge(df_b.drop(columns=['s_start']), on='seg_id',
                        how='inner', suffixes=('_a', '_b')).sort_values('seg_id')
    merged['delta_iri_multi'] = merged['iri_multi_b'] - merged['iri_multi_a']
    merged = merged.rename(columns={'mean_speed_kmh_a': 'mean_speed_a',
                                    'mean_speed_kmh_b': 'mean_speed_b'})

    segments = merged.replace({np.nan: None}).to_dict('records')
    for row in segments:
        row['seg_id'] = int(row['seg_id'])

    deltas = merged['delta_iri_multi'].dropna()
    mean_delta = float(deltas.mean()) if len(deltas) else None
    max_abs_delta = float(deltas.abs().max()) if len(deltas) else None

    return {
        'file_id': file_id,
        'run_a': {'id': ra.id, 'params': ra.params, 'summary': ra.summary},
        'run_b': {'id': rb.id, 'params': rb.params, 'summary': rb.summary},
        'segments': segments,
        'summary': {
            'segments': segments_total,
            'matched': len(merged),
            'mean_delta_iri_multi': mean_delta,
            'max_abs_delta': max_abs_delta,
        },
    }
