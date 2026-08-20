"""
Comparisons API: create/queue a run-vs-reference comparison job, list, detail,
delete, and artifact serving. DB stores metadata only — artifacts stay on disk
under storage/results/comparisons/ (spec §2, mirrors runs.py).
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import ComparisonCreate, ComparisonOut
from src.core.config import get_settings
from src.db.models import AnalysisRun, Comparison, ReferenceDataset
from src.db.session import get_session
from src.services.comparison import delete_comparison_artifacts, execute_comparison

router = APIRouter(prefix='/comparisons', tags=['comparisons'])


def _to_out(comparison: Comparison) -> ComparisonOut:
    out = ComparisonOut.model_validate(comparison)
    out.run_filename = (comparison.run.file.filename
                        if comparison.run and comparison.run.file else None)
    out.reference_road = comparison.reference.road_name if comparison.reference else None
    return out


def _create_and_submit(request: Request, session: Session, run_id: int,
                       reference_id: int, params: dict) -> Comparison:
    comparison = Comparison(run_id=run_id, reference_id=reference_id, params=params or {})
    session.add(comparison)
    session.commit()
    session.refresh(comparison)
    request.app.state.queue.submit(
        execute_comparison, comparison.id, request.app.state.engine, get_settings())
    session.refresh(comparison)
    return comparison


@router.post('', status_code=201, response_model=ComparisonOut)
def create_comparison(payload: ComparisonCreate, request: Request,
                      session: Session = Depends(get_session)):
    run = session.get(AnalysisRun, payload.run_id)
    if run is None:
        raise HTTPException(404, 'Run not found')
    if run.status != 'done':
        raise HTTPException(409, 'ран ще не завершено')

    reference = session.get(ReferenceDataset, payload.reference_id)
    if reference is None:
        raise HTTPException(404, 'Reference not found')
    if reference.source_deleted:
        raise HTTPException(409, 'еталон видалено — файл еталонних інтервалів більше не доступний')
    if reference.step_m != 10:
        raise HTTPException(
            409, f'еталон має бути 10 м формою (крок цього еталона: {reference.step_m:g} м)')

    comparison = _create_and_submit(request, session, payload.run_id,
                                    payload.reference_id, payload.params)
    return _to_out(comparison)


@router.get('', response_model=list[ComparisonOut])
def list_comparisons(run_id: int | None = None, session: Session = Depends(get_session)):
    query = select(Comparison).order_by(Comparison.created_at.desc(), Comparison.id.desc())
    if run_id is not None:
        query = query.where(Comparison.run_id == run_id)
    return [_to_out(c) for c in session.scalars(query).all()]


@router.get('/{comparison_id}', response_model=ComparisonOut)
def get_comparison(comparison_id: int, session: Session = Depends(get_session)):
    comparison = session.get(Comparison, comparison_id)
    if comparison is None:
        raise HTTPException(404, 'Comparison not found')
    return _to_out(comparison)


@router.delete('/{comparison_id}', status_code=204)
def delete_comparison(comparison_id: int, session: Session = Depends(get_session)):
    comparison = session.get(Comparison, comparison_id)
    if comparison is None:
        raise HTTPException(404, 'Comparison not found')
    delete_comparison_artifacts(comparison)
    session.delete(comparison)
    session.commit()


@router.get('/{comparison_id}/artifacts/{name:path}')
def get_comparison_artifact(comparison_id: int, name: str,
                            session: Session = Depends(get_session)):
    comparison = session.get(Comparison, comparison_id)
    if comparison is None:
        raise HTTPException(404, 'Comparison not found')
    if not comparison.result_dir:
        raise HTTPException(404, 'Comparison has no artifacts yet')
    base = Path(comparison.result_dir).resolve()
    target = (base / name).resolve()
    if not target.is_relative_to(base):
        raise HTTPException(403, 'Path escapes the comparison directory')
    if not target.is_file():
        raise HTTPException(404, f"No artifact '{name}'")
    return FileResponse(target)
