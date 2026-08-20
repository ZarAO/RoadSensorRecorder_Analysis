"""
Runs API: create/queue, run-all-unanalyzed, list, detail, delete.
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import RunCreate, RunOut
from src.core.config import get_settings
from src.db.models import AnalysisRun, SourceFile
from src.db.session import get_session
from src.services.analysis import delete_run_artifacts, execute_run
from src.services.coefficients import bias_of, resolve_for_meta

router = APIRouter(prefix='/runs', tags=['runs'])


def _to_out(run: AnalysisRun) -> RunOut:
    out = RunOut.model_validate(run)
    out.filename = run.file.filename if run.file else None
    return out


def _create_and_submit(request: Request, session: Session, file_id: int,
                       params: dict) -> AnalysisRun:
    source = session.get(SourceFile, file_id)
    coefficients = resolve_for_meta(session, source.recording_meta if source else None)
    eq3, eq6_bias = coefficients['eq3'], coefficients['eq6_bias']

    params = dict(params or {})
    # Snapshotted at creation time so a later edit of a set cannot rewrite an
    # executed run; omitted entirely when nothing applies (book constants)
    if eq3 or eq6_bias:
        params['coefficients'] = coefficients

    run = AnalysisRun(file_id=file_id, params=params,
                      eq3_set_id=eq3['set_id'] if eq3 else None,
                      eq6_bias_set_id=eq6_bias['set_id'] if eq6_bias else None)
    session.add(run)
    session.commit()
    session.refresh(run)
    request.app.state.queue.submit(
        execute_run, run.id, request.app.state.engine, get_settings())
    session.refresh(run)
    return run


@router.post('', status_code=201, response_model=RunOut)
def create_run(payload: RunCreate, request: Request,
               session: Session = Depends(get_session)):
    if session.get(SourceFile, payload.file_id) is None:
        raise HTTPException(404, 'File not found')
    return _to_out(_create_and_submit(request, session, payload.file_id, payload.params))


@router.post('/run-all-unanalyzed', response_model=list[RunOut])
def run_all_unanalyzed(request: Request, session: Session = Depends(get_session)):
    files = session.scalars(
        select(SourceFile).where(SourceFile.source_deleted.is_(False))
    ).all()
    created = []
    for f in files:
        if any(r.status == 'done' for r in f.runs):
            continue
        created.append(_create_and_submit(request, session, f.id, {}))
    return [_to_out(r) for r in created]


@router.get('', response_model=list[RunOut])
def list_runs(file_id: int | None = None, session: Session = Depends(get_session)):
    query = select(AnalysisRun).order_by(AnalysisRun.created_at.desc(),
                                         AnalysisRun.id.desc())
    if file_id is not None:
        query = query.where(AnalysisRun.file_id == file_id)
    return [_to_out(r) for r in session.scalars(query).all()]


@router.get('/{run_id}', response_model=RunOut)
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, 'Run not found')
    return _to_out(run)


def _run_or_404(run_id: int, session: Session) -> AnalysisRun:
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, 'Run not found')
    return run


@router.get('/{run_id}/artifacts/{name:path}')
def get_artifact(run_id: int, name: str, session: Session = Depends(get_session)):
    run = _run_or_404(run_id, session)
    if not run.result_dir:
        raise HTTPException(404, 'Run has no artifacts yet')
    base = Path(run.result_dir).resolve()
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(403, 'Path escapes the run directory')
    if not target.is_file():
        raise HTTPException(404, f"No artifact '{name}'")
    return FileResponse(target)


@router.get('/{run_id}/segments')
def get_segments(run_id: int, session: Session = Depends(get_session)):
    run = _run_or_404(run_id, session)
    csv_path = Path(run.result_dir or '') / 'road_segments.csv'
    if not csv_path.is_file():
        raise HTTPException(404, 'road_segments.csv not found')
    df = pd.read_csv(csv_path)
    bias = bias_of((run.params or {}).get('coefficients'))
    if bias is not None and 'iri_multi' in df.columns:
        # Correction lives in the response only — analyzer artifacts stay as
        # written. NaN propagates, so a low-speed segment stays null below.
        df['iri_multi_corrected'] = df['iri_multi'] - bias
    # NaN -> null: strict JSON parsers reject NaN, and a missing metric must
    # never surface as a number (analyzer invariant)
    return df.replace({np.nan: None}).to_dict('records')


@router.get('/{run_id}/log')
def get_log(run_id: int, follow: bool = True,
            session: Session = Depends(get_session)):
    run = _run_or_404(run_id, session)
    log_path = Path(run.log_path) if run.log_path else None
    if log_path is None or not log_path.is_file():
        raise HTTPException(404, 'No log for this run')

    if not follow:
        return PlainTextResponse(log_path.read_text(encoding='utf-8', errors='replace'))

    engine = session.get_bind().engine

    def _stream():
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line.rstrip()}\n\n"
                    continue
                # No new content: stop when the run has left 'running'
                with Session(engine) as poll_session:
                    current = poll_session.get(AnalysisRun, run_id)
                    if current is None or current.status not in ('queued', 'running'):
                        yield "event: done\ndata: \n\n"
                        return
                time.sleep(0.5)

    return StreamingResponse(_stream(), media_type='text/event-stream')


@router.delete('/{run_id}', status_code=204)
def delete_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, 'Run not found')
    delete_run_artifacts(run)
    session.delete(run)
    session.commit()
