"""
CoefficientSet API (Phase 3): draft a set from a comparison's fitted
stats.json, confirm it (archiving the previous confirmed set for the same FULL
key — model, vehicle_type, phone_model, device_id, vehicle_id), archive, and
reanalyze the files of the matching vehicle under the freshly confirmed set.

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
    PreviewResolutionIn,
    PreviewResolutionOut,
    RunOut,
)
from src.db.models import AggregateComparison, Comparison, CoefficientSet, SourceFile
from src.db.session import get_session
from src.services.coefficients import files_applying_to, files_resolving_to

router = APIRouter(prefix='/coefficient-sets', tags=['coefficient-sets'])

MSG_ONE_PROVENANCE = ('вкажіть рівно одне джерело: comparison_id (одне '
                      'порівняння) або aggregate_comparison_id (агрегація проїздів)')
MSG_AGGREGATE_NO_EQ3 = ('агрегація не містить фіту Eq.3 — з неї можна створити '
                        'лише набір eq6_bias (зсув)')


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


def _aggregate_snapshot(stats: dict) -> dict:
    return {
        'bias_ci_low': stats['bias']['ci_low'],
        'bias_ci_high': stats['bias']['ci_high'],
        'n_passes': stats['n_runs'],
        'n_bins': stats['n_bins'],
        'repeatability_sd': stats['repeatability']['sd'],
        'rho': stats['validation']['spearman_rho'],
        'mae_aggregated': stats['validation']['mae'],
    }


def _reject_duplicate_name(session: Session, name: str) -> None:
    if session.scalar(
            select(CoefficientSet).where(CoefficientSet.name == name)) is not None:
        raise HTTPException(409, f"набір з назвою '{name}' вже існує")


def _load_artifact_json(result_dir: str | None, name: str, subject: str) -> dict:
    if not result_dir:
        raise HTTPException(404, f'{subject} has no artifacts yet')
    path = Path(result_dir) / name
    if not path.is_file():
        raise HTTPException(404, f"No artifact '{name}'")
    return json.loads(path.read_text(encoding='utf-8'))


def _candidate_files(session: Session, vehicle_type: str | None) -> list[SourceFile]:
    """Reanalyze candidates: every file of the vehicle type, whatever phone
    recorded it. A phone-specific set still changes which set resolves for the
    other phones of the same vehicle (the NULL tier may sit underneath), so the
    reanalyze offer stays deliberately vehicle-wide."""
    return files_resolving_to(session, vehicle_type, None)


def _same_key(column, value):
    """NULL-safe equality: SQL `= NULL` is never true, so a null key part has to
    be compared with IS NULL for the «one confirmed per key» invariant to hold."""
    return column.is_(None) if value is None else column == value


def _set_or_404(set_id: int, session: Session) -> CoefficientSet:
    cs = session.get(CoefficientSet, set_id)
    if cs is None:
        raise HTTPException(404, 'Coefficient set not found')
    return cs


def _draft_from_comparison(payload: CoefficientSetCreate, session: Session) -> CoefficientSet:
    comparison = session.get(Comparison, payload.comparison_id)
    if comparison is None:
        raise HTTPException(404, 'Comparison not found')
    if comparison.status != 'done':
        raise HTTPException(
            409, 'порівняння ще не завершено — набір коефіцієнтів можна '
            'створити лише із завершеного порівняння')
    _reject_duplicate_name(session, payload.name)

    stats = _load_artifact_json(comparison.result_dir, 'stats.json', 'Comparison')
    params = _draft_params(payload.model, stats)
    if _has_degenerate_fit(payload.model, params):
        raise HTTPException(
            409, 'порівняння має вироджений фіт — набір не може бути створений')

    return CoefficientSet(
        name=payload.name,
        model=payload.model,
        params=params,
        vehicle_type=payload.vehicle_type,
        phone_model=payload.phone_model,
        device_id=payload.device_id,
        vehicle_id=payload.vehicle_id,
        status='draft',
        comparison_id=payload.comparison_id,
        stats_snapshot=_stats_snapshot(stats),
    )


def _draft_from_aggregate(payload: CoefficientSetCreate, session: Session) -> CoefficientSet:
    aggregate = session.get(AggregateComparison, payload.aggregate_comparison_id)
    if aggregate is None:
        raise HTTPException(404, 'Aggregate comparison not found')
    if aggregate.status != 'done':
        raise HTTPException(
            409, 'агрегацію ще не завершено — набір коефіцієнтів можна '
            'створити лише із завершеної агрегації')
    # Eq.3 is fitted per comparison (sqrtPSD -> IRI); an aggregate only pools
    # already-computed IRI, so only the Eq.6 bias can come out of it.
    if payload.model != 'eq6_bias':
        raise HTTPException(409, MSG_AGGREGATE_NO_EQ3)
    _reject_duplicate_name(session, payload.name)

    stats = _load_artifact_json(aggregate.result_dir, 'aggregate_stats.json',
                                'Aggregate comparison')
    params = {'bias': stats['bias']['bias']}
    if _has_degenerate_fit(payload.model, params):
        raise HTTPException(
            409, 'агрегація має вироджений зсув — набір не може бути створений')

    return CoefficientSet(
        name=payload.name,
        model=payload.model,
        params=params,
        vehicle_type=payload.vehicle_type,
        phone_model=payload.phone_model,
        device_id=payload.device_id,
        vehicle_id=payload.vehicle_id,
        status='draft',
        aggregate_comparison_id=payload.aggregate_comparison_id,
        stats_snapshot=_aggregate_snapshot(stats),
    )


@router.post('', status_code=201, response_model=CoefficientSetOut)
def create_draft(payload: CoefficientSetCreate, session: Session = Depends(get_session)):
    # Provenance is either one comparison or one aggregate, never both/neither
    if (payload.comparison_id is None) == (payload.aggregate_comparison_id is None):
        raise HTTPException(422, MSG_ONE_PROVENANCE)

    cs = (_draft_from_aggregate(payload, session)
          if payload.aggregate_comparison_id is not None
          else _draft_from_comparison(payload, session))
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


@router.post('/preview-resolution', response_model=PreviewResolutionOut)
def preview_resolution(payload: PreviewResolutionIn,
                       session: Session = Depends(get_session)):
    """Which uploaded files a set with this key would actually be applied to —
    answered before the operator confirms, so a key that matches nothing is
    visible as 0 instead of silently producing a set that never resolves. The
    count is the true inverse of resolution: a file already won by a more
    specific confirmed set is not promised here."""
    files = files_applying_to(session, payload.model, payload.vehicle_type,
                              payload.phone_model, payload.device_id,
                              payload.vehicle_id)
    return PreviewResolutionOut(files_matched=len(files),
                                filenames=[f.filename for f in files])


@router.post('/{set_id}/confirm', response_model=ConfirmOut)
def confirm_set(set_id: int, payload: ConfirmIn, session: Session = Depends(get_session)):
    cs = _set_or_404(set_id, session)
    if cs.status != 'draft':
        raise HTTPException(
            409, f'підтвердити можна лише чернетку (поточний статус: {cs.status})')

    # One confirmed set per FULL key: an identity-keyed set and the legacy phone
    # set of the same vehicle are different keys and coexist.
    query = select(CoefficientSet).where(
        CoefficientSet.id != cs.id,
        CoefficientSet.model == cs.model,
        CoefficientSet.status == 'confirmed',
        *[_same_key(column, value) for column, value in (
            (CoefficientSet.vehicle_type, cs.vehicle_type),
            (CoefficientSet.phone_model, cs.phone_model),
            (CoefficientSet.device_id, cs.device_id),
            (CoefficientSet.vehicle_id, cs.vehicle_id))])
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
