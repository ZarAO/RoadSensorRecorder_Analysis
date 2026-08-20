"""
Runs API: create/queue, run-all-unanalyzed, list, detail, delete.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import RunCreate, RunOut
from src.core.config import get_settings
from src.db.models import AnalysisRun, SourceFile
from src.db.session import get_session
from src.services.analysis import delete_run_artifacts, execute_run

router = APIRouter(prefix='/runs', tags=['runs'])


def _to_out(run: AnalysisRun) -> RunOut:
    out = RunOut.model_validate(run)
    out.filename = run.file.filename if run.file else None
    return out


def _create_and_submit(request: Request, session: Session, file_id: int,
                       params: dict) -> AnalysisRun:
    run = AnalysisRun(file_id=file_id, params=params or {})
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


@router.delete('/{run_id}', status_code=204)
def delete_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, 'Run not found')
    delete_run_artifacts(run)
    session.delete(run)
    session.commit()
