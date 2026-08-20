"""
Phase 3: which confirmed coefficient set applies to a recording.

Resolution is per model ('eq3' for the PSD->IRI equation, 'eq6_bias' for the
additive multi-metric bias) and deliberately conservative: only *confirmed*
sets apply, and an unresolved model means the analyzer keeps its published book
constants. The resolved sets are snapshotted onto the run so a later edit of a
set never rewrites the history of an already executed run.
"""

import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import CoefficientSet

MODELS = ('eq3', 'eq6_bias')


def phone_model_from_meta(recording_meta: dict | None) -> str | None:
    """'samsung SM-S948B, android=16' -> 'samsung SM-S948B'; None when absent."""
    device = ((recording_meta or {}).get('preamble') or {}).get('device')
    if not device:
        return None
    return device.split(',')[0].strip() or None


def vehicle_type_from_meta(recording_meta: dict | None) -> str | None:
    """Pre-v3 recordings carry no vehicle block -> None (book constants)."""
    return ((recording_meta or {}).get('vehicle') or {}).get('vehicle_type') or None


def resolve(session: Session, model: str, vehicle_type: str | None,
            phone_model: str | None) -> CoefficientSet | None:
    """
    Confirmed sets only, most specific first:
      1) (model, vehicle_type, phone_model)
      2) (model, vehicle_type, phone_model IS NULL)
      3) None -> the caller falls back to the book constants
    Without a vehicle type nothing is applied: the coefficients are calibrated
    per vehicle, so an unknown vehicle must not inherit another one's set.
    """
    if not vehicle_type:
        return None
    base = (
        select(CoefficientSet)
        .where(CoefficientSet.model == model,
               CoefficientSet.status == 'confirmed',
               CoefficientSet.vehicle_type == vehicle_type)
        .order_by(CoefficientSet.id.desc())  # newest confirmed set wins a tie
    )
    if phone_model:
        exact = session.scalars(
            base.where(CoefficientSet.phone_model == phone_model)).first()
        if exact is not None:
            return exact
    return session.scalars(base.where(CoefficientSet.phone_model.is_(None))).first()


def _snapshot(cs: CoefficientSet | None) -> dict | None:
    if cs is None:
        return None
    # Copy: the snapshot must not alias the live ORM dict of the set
    return {'set_id': cs.id, 'name': cs.name, 'params': dict(cs.params or {})}


def resolve_for_meta(session: Session, recording_meta: dict | None) -> dict:
    """{'eq3': snapshot|None, 'eq6_bias': snapshot|None} for one recording."""
    vehicle_type = vehicle_type_from_meta(recording_meta)
    phone_model = phone_model_from_meta(recording_meta)
    return {model: _snapshot(resolve(session, model, vehicle_type, phone_model))
            for model in MODELS}


def eq3_kwargs(coefficients: dict | None) -> dict:
    """analyze() kwargs for a resolved Eq.3 set; {} means the book constants."""
    params = ((coefficients or {}).get('eq3') or {}).get('params') or {}
    if not params:
        return {}
    return {'iri_psd_A': params.get('A'), 'iri_psd_B': params.get('B')}


def bias_of(coefficients: dict | None) -> float | None:
    """The Eq.6 additive bias to subtract from iri_multi, or None."""
    bias = (((coefficients or {}).get('eq6_bias') or {}).get('params') or {}).get('bias')
    # bool is an int subclass, and NaN/inf must never reach a JSON response
    if isinstance(bias, bool) or not isinstance(bias, (int, float)):
        return None
    return float(bias) if math.isfinite(bias) else None
