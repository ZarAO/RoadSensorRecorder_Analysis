"""
Aggregate comparisons API: create/queue a multi-pass aggregation job, list,
detail, delete, and artifact serving. DB stores metadata only — artifacts stay
on disk under storage/results/aggregates/ (mirrors comparisons.py).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import AggregateCreate, AggregateOut
from src.core.config import get_settings
from src.db.models import AggregateComparison, AnalysisRun, ReferenceDataset
from src.db.session import get_session
from src.services.aggregate import (
    MIN_RUNS,
    MSG_TOO_FEW_RUNS,
    delete_aggregate_artifacts,
    detach_coefficient_sets,
    execute_aggregate,
    unique_run_ids,
)
from src.services.comparison import MSG_REFERENCE_DELETED, MSG_REFERENCE_NOT_10M

router = APIRouter(prefix='/aggregate-comparisons', tags=['aggregate-comparisons'])


def _to_out(aggregate: AggregateComparison, session: Session) -> AggregateOut:
    out = AggregateOut.model_validate(aggregate)
    out.reference_road = (aggregate.reference.road_name
                          if aggregate.reference else None)
    run_ids = unique_run_ids(aggregate.run_ids)
    runs = {}
    if run_ids:
        runs = {r.id: r for r in session.scalars(
            select(AnalysisRun).where(AnalysisRun.id.in_(run_ids))).all()}
    # A deleted pass simply drops out of the enrichment (summary.stale marks it)
    out.run_filenames = [runs[i].file.filename for i in run_ids
                         if i in runs and runs[i].file is not None]
    return out


@router.post('', status_code=201, response_model=AggregateOut)
def create_aggregate(payload: AggregateCreate, request: Request,
                     session: Session = Depends(get_session)):
    run_ids = unique_run_ids(payload.run_ids)
    if len(run_ids) < MIN_RUNS:
        raise HTTPException(422, MSG_TOO_FEW_RUNS)

    for run_id in run_ids:
        run = session.get(AnalysisRun, run_id)
        if run is None:
            raise HTTPException(404, f'Run {run_id} not found')
        if run.status != 'done':
            raise HTTPException(409, f'ран #{run_id} ще не завершено')

    reference = session.get(ReferenceDataset, payload.reference_id)
    if reference is None:
        raise HTTPException(404, 'Reference not found')
    if reference.source_deleted:
        raise HTTPException(409, MSG_REFERENCE_DELETED)
    if reference.step_m != 10:
        raise HTTPException(409, MSG_REFERENCE_NOT_10M.format(step_m=reference.step_m))

    aggregate = AggregateComparison(reference_id=payload.reference_id,
                                    run_ids=run_ids, params=payload.params or {})
    session.add(aggregate)
    session.commit()
    session.refresh(aggregate)
    request.app.state.queue.submit(
        execute_aggregate, aggregate.id, request.app.state.engine, get_settings())
    session.refresh(aggregate)
    return _to_out(aggregate, session)


@router.get('', response_model=list[AggregateOut])
def list_aggregates(session: Session = Depends(get_session)):
    query = select(AggregateComparison).order_by(
        AggregateComparison.created_at.desc(), AggregateComparison.id.desc())
    return [_to_out(a, session) for a in session.scalars(query).all()]


@router.get('/{aggregate_id}', response_model=AggregateOut)
def get_aggregate(aggregate_id: int, session: Session = Depends(get_session)):
    aggregate = session.get(AggregateComparison, aggregate_id)
    if aggregate is None:
        raise HTTPException(404, 'Aggregate comparison not found')
    return _to_out(aggregate, session)


@router.delete('/{aggregate_id}', status_code=204)
def delete_aggregate(aggregate_id: int, session: Session = Depends(get_session)):
    aggregate = session.get(AggregateComparison, aggregate_id)
    if aggregate is None:
        raise HTTPException(404, 'Aggregate comparison not found')
    detach_coefficient_sets(session, [aggregate_id])
    delete_aggregate_artifacts(aggregate)
    session.delete(aggregate)
    session.commit()


@router.get('/{aggregate_id}/artifacts/{name:path}')
def get_aggregate_artifact(aggregate_id: int, name: str,
                           session: Session = Depends(get_session)):
    aggregate = session.get(AggregateComparison, aggregate_id)
    if aggregate is None:
        raise HTTPException(404, 'Aggregate comparison not found')
    if not aggregate.result_dir:
        raise HTTPException(404, 'Aggregate comparison has no artifacts yet')
    base = Path(aggregate.result_dir).resolve()
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(403, 'Path escapes the aggregate directory')
    if not target.is_file():
        raise HTTPException(404, f"No artifact '{name}'")
    return FileResponse(target)
