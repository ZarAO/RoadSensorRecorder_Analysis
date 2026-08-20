"""
CoefficientSet API (Phase 3): draft a set from a comparison's fitted
stats.json, confirm it (archiving the previous confirmed set for the same
(model, vehicle_type, phone_model) key), archive, and reanalyze the files of
the matching vehicle under the freshly confirmed set.

Resolution itself lives in src.services.coefficients; this router only manages
the CoefficientSet lifecycle and reuses runs._create_and_submit so a
reanalyzed run resolves the newly confirmed set the same way any other new
run would (no duplicated resolution logic here).
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.runs import _create_and_submit
from src.api.runs import _to_out as _run_to_out
from src.api.schemas import (
    CoefficientSetCreate,
    CoefficientSetOut,
    ConfirmIn,
    ConfirmOut,
    RunOut,
)
from src.db.models import Comparison, CoefficientSet, SourceFile
from src.db.session import get_session

router = APIRouter(prefix='/coefficient-sets', tags=['coefficient-sets'])


def _to_out(cs: CoefficientSet) -> CoefficientSetOut:
    return CoefficientSetOut.model_validate(cs)


def _draft_params(model: str, stats: dict) -> dict:
    if model == 'eq3':
        fit = stats['eq3_fit']
        return {'A': fit['A'], 'B': fit['B']}
    return {'bias': stats['eq6_bias']['bias']}


def _is_degenerate_number(value) -> bool:
    """True unless value is a finite, non-bool number (NaN is json-nulled to
    None upstream in stats.json, so None is the common degenerate case)."""
    return (value is None or isinstance(value, bool)
            or not isinstance(value, (int, float)) or not math.isfinite(value))


def _has_degenerate_fit(model: str, params: dict) -> bool:
    if model == 'eq3':
        return _is_degenerate_number(params.get('A')) or _is_degenerate_number(params.get('B'))
    return _is_degenerate_number(params.get('bias'))


def _stats_snapshot(stats: dict) -> dict:
    return {
        'r2': stats['eq3_fit']['r2'],
        'mae': stats['validation']['iri_multi']['mae'],
        'spearman_rho': stats['validation']['iri_multi']['spearman_rho'],
        'n_pairs': stats['n_pairs'],
        'mae_bias_corrected': stats['eq6_bias']['mae_corrected'],
    }


def _candidate_files(session: Session, vehicle_type: str | None) -> list[SourceFile]:
    """Non-deleted files whose recording_meta.vehicle.vehicle_type matches
    (filtered in Python: small N — spec §Phase 3). A falsy vehicle_type never
    matches: None == None would otherwise pull in every pre-v3 file that
    carries no vehicle block at all."""
    if not vehicle_type:
        return []
    files = session.scalars(
        select(SourceFile).where(SourceFile.source_deleted.is_(False))).all()
    return [f for f in files
            if ((f.recording_meta or {}).get('vehicle') or {}).get('vehicle_type') == vehicle_type]


def _set_or_404(set_id: int, session: Session) -> CoefficientSet:
    cs = session.get(CoefficientSet, set_id)
    if cs is None:
        raise HTTPException(404, 'Coefficient set not found')
    return cs


@router.post('', status_code=201, response_model=CoefficientSetOut)
def create_draft(payload: CoefficientSetCreate, session: Session = Depends(get_session)):
    comparison = session.get(Comparison, payload.comparison_id)
    if comparison is None:
        raise HTTPException(404, 'Comparison not found')
    if comparison.status != 'done':
        raise HTTPException(
            409, 'порівняння ще не завершено — набір коефіцієнтів можна '
            'створити лише із завершеного порівняння')
    if session.scalar(
            select(CoefficientSet).where(CoefficientSet.name == payload.name)) is not None:
        raise HTTPException(409, f"набір з назвою '{payload.name}' вже існує")

    if not comparison.result_dir:
        raise HTTPException(404, 'Comparison has no artifacts yet')
    stats_path = Path(comparison.result_dir) / 'stats.json'
    if not stats_path.is_file():
        raise HTTPException(404, "No artifact 'stats.json'")
    stats = json.loads(stats_path.read_text(encoding='utf-8'))

    params = _draft_params(payload.model, stats)
    if _has_degenerate_fit(payload.model, params):
        raise HTTPException(
            409, 'порівняння має вироджений фіт — набір не може бути створений')

    cs = CoefficientSet(
        name=payload.name,
        model=payload.model,
        params=params,
        vehicle_type=payload.vehicle_type,
        phone_model=payload.phone_model,
        status='draft',
        comparison_id=payload.comparison_id,
        stats_snapshot=_stats_snapshot(stats),
    )
    session.add(cs)
    session.commit()
    session.refresh(cs)
    return _to_out(cs)


@router.get('', response_model=list[CoefficientSetOut])
def list_sets(session: Session = Depends(get_session)):
    sets = session.scalars(
        select(CoefficientSet).order_by(CoefficientSet.created_at.desc(),
                                        CoefficientSet.id.desc())
    ).all()
    return [_to_out(s) for s in sets]


@router.post('/{set_id}/confirm', response_model=ConfirmOut)
def confirm_set(set_id: int, payload: ConfirmIn, session: Session = Depends(get_session)):
    cs = _set_or_404(set_id, session)
    if cs.status != 'draft':
        raise HTTPException(
            409, f'підтвердити можна лише чернетку (поточний статус: {cs.status})')

    query = select(CoefficientSet).where(
        CoefficientSet.id != cs.id,
        CoefficientSet.model == cs.model,
        CoefficientSet.vehicle_type == cs.vehicle_type,
        CoefficientSet.status == 'confirmed')
    query = query.where(CoefficientSet.phone_model.is_(None)
                        if cs.phone_model is None
                        else CoefficientSet.phone_model == cs.phone_model)
    previous = session.scalars(query).first()
    archived_set_id = None
    if previous is not None:
        previous.status = 'archived'
        archived_set_id = previous.id

    cs.status = 'confirmed'
    cs.confirmed_at = datetime.now(timezone.utc)
    cs.confirmed_note = payload.note
    session.commit()
    session.refresh(cs)

    reanalyze_candidates = len(_candidate_files(session, cs.vehicle_type))
    return ConfirmOut(set=_to_out(cs), archived_set_id=archived_set_id,
                      reanalyze_candidates=reanalyze_candidates)


@router.post('/{set_id}/archive', response_model=CoefficientSetOut)
def archive_set(set_id: int, session: Session = Depends(get_session)):
    cs = _set_or_404(set_id, session)
    if cs.status == 'archived':
        raise HTTPException(409, 'набір вже архівовано')
    cs.status = 'archived'
    session.commit()
    session.refresh(cs)
    return _to_out(cs)


@router.post('/{set_id}/reanalyze', response_model=list[RunOut])
def reanalyze_set(set_id: int, request: Request, session: Session = Depends(get_session)):
    cs = _set_or_404(set_id, session)
    if cs.status != 'confirmed':
        raise HTTPException(
            409, f'переаналіз можливий лише для підтвердженого набору '
            f'(поточний статус: {cs.status})')
    candidates = _candidate_files(session, cs.vehicle_type)
    runs = [_create_and_submit(request, session, f.id, {}) for f in candidates]
    return [_run_to_out(r) for r in runs]
