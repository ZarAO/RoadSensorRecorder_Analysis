"""
Phase 3: which confirmed coefficient set applies to a recording.

Resolution is per model ('eq3' for the PSD->IRI equation, 'eq6_bias' for the
additive multi-metric bias) and deliberately conservative: only *confirmed*
sets apply, and an unresolved model means the analyzer keeps its published book
constants. The resolved sets are snapshotted onto the run so a later edit of a
set never rewrites the history of an already executed run.
"""

import math
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import CoefficientSet, SourceFile

MODELS = ('eq3', 'eq6_bias')

# Resolution tiers, most specific first (spec §5b). The number is the
# specificity used to compare two keys that both match the same recording.
TIER_IDENTITY = 3   # (device_id, vehicle_id) — contract v3.1, the phone's own key
TIER_PHONE = 2      # (vehicle_type, phone_model) — legacy, pre-v3.1 recordings
TIER_GENERIC = 1    # (vehicle_type) — any phone of that vehicle type


def phone_model_from_meta(recording_meta: dict | None) -> str | None:
    """'samsung SM-S948B, android=16' -> 'samsung SM-S948B'; None when absent."""
    device = ((recording_meta or {}).get('preamble') or {}).get('device')
    if not device:
        return None
    return device.split(',')[0].strip() or None


def vehicle_type_from_meta(recording_meta: dict | None) -> str | None:
    """Pre-v3 recordings carry no vehicle block -> None (book constants)."""
    return ((recording_meta or {}).get('vehicle') or {}).get('vehicle_type') or None


def device_id_from_meta(recording_meta: dict | None) -> str | None:
    """Contract v3.1 `# device_id=<ANDROID_ID>`; None for every older recording."""
    return ((recording_meta or {}).get('preamble') or {}).get('device_id') or None


def vehicle_id_from_meta(recording_meta: dict | None) -> str | None:
    """Contract v3.1 `# vehicle_id=<profile UUID>`. The metadata parser routes
    every `vehicle_`-prefixed key into the vehicle block WITHOUT stripping the
    prefix, so the key here is 'vehicle_id', not 'id'."""
    return ((recording_meta or {}).get('vehicle') or {}).get('vehicle_id') or None


class MetaKeys(NamedTuple):
    """Everything resolution matches a recording on."""

    vehicle_type: str | None
    phone_model: str | None
    device_id: str | None = None
    vehicle_id: str | None = None


def keys_from_meta(recording_meta: dict | None) -> MetaKeys:
    return MetaKeys(vehicle_type_from_meta(recording_meta),
                    phone_model_from_meta(recording_meta),
                    device_id_from_meta(recording_meta),
                    vehicle_id_from_meta(recording_meta))


def key_tier(phone_model: str | None, device_id: str | None,
             vehicle_id: str | None) -> int:
    """The tier a set with this key resolves at. A half identity (only one of the
    two ids) is never TIER_IDENTITY — see resolve()."""
    if device_id and vehicle_id:
        return TIER_IDENTITY
    return TIER_PHONE if phone_model else TIER_GENERIC


def resolve(session: Session, model: str, keys: MetaKeys) -> CoefficientSet | None:
    """
    Confirmed sets only, most specific first (spec §5b):
      1) (model, device_id, vehicle_id) — only when the recording AND the set
         carry both identity keys; the vehicle type is implied by the profile
      2) (model, vehicle_type, phone_model) — legacy key, identity columns NULL
      3) (model, vehicle_type, phone_model IS NULL) — any phone of that vehicle
      4) None -> the caller falls back to the book constants
    Tiers 2 and 3 require the set's identity columns to be NULL: a set keyed on
    one car must never leak onto another car of the same type, and half an
    identity (one id without the other) resolves for nothing at all.
    Without a vehicle type nothing is applied below tier 1: the coefficients are
    calibrated per vehicle, so an unknown vehicle must not inherit another's set.
    """
    confirmed = (
        select(CoefficientSet)
        .where(CoefficientSet.model == model,
               CoefficientSet.status == 'confirmed')
        .order_by(CoefficientSet.id.desc())  # newest confirmed set wins a tie
    )
    if keys.device_id and keys.vehicle_id:
        exact = session.scalars(confirmed.where(
            CoefficientSet.device_id == keys.device_id,
            CoefficientSet.vehicle_id == keys.vehicle_id)).first()
        if exact is not None:
            return exact
    if not keys.vehicle_type:
        return None
    legacy = confirmed.where(CoefficientSet.vehicle_type == keys.vehicle_type,
                             CoefficientSet.device_id.is_(None),
                             CoefficientSet.vehicle_id.is_(None))
    if keys.phone_model:
        by_phone = session.scalars(
            legacy.where(CoefficientSet.phone_model == keys.phone_model)).first()
        if by_phone is not None:
            return by_phone
    return session.scalars(legacy.where(CoefficientSet.phone_model.is_(None))).first()


def files_resolving_to(session: Session, vehicle_type: str | None,
                       phone_model: str | None, device_id: str | None = None,
                       vehicle_id: str | None = None) -> list[SourceFile]:
    """
    The non-deleted files whose metadata MATCHES this key — the inverse of one
    resolution tier, used for the reanalyze candidates and as the candidate pool
    of the pre-confirm preview.

    Filtered in Python: the keys live inside the recording_meta JSON and N is
    small (spec §Phase 3). With both identity keys this is the tier-1 inverse and
    the vehicle type is ignored, exactly as resolve() ignores it there. A half
    identity resolves for nothing, so it matches nothing. Otherwise a falsy
    vehicle_type matches nothing, mirroring resolve(): None == None would
    otherwise pull in every pre-v3 file that carries no vehicle block at all,
    and phone_model=None is the NULL tier — every file of the vehicle type,
    whatever phone recorded it.
    """
    if device_id or vehicle_id:
        if not (device_id and vehicle_id):
            return []
        return [f for f in _live_files(session)
                if device_id_from_meta(f.recording_meta) == device_id
                and vehicle_id_from_meta(f.recording_meta) == vehicle_id]
    if not vehicle_type:
        return []
    return [f for f in _live_files(session)
            if vehicle_type_from_meta(f.recording_meta) == vehicle_type
            and (phone_model is None
                 or phone_model_from_meta(f.recording_meta) == phone_model)]


def files_applying_to(session: Session, model: str, vehicle_type: str | None,
                      phone_model: str | None, device_id: str | None = None,
                      vehicle_id: str | None = None) -> list[SourceFile]:
    """
    The TRUE inverse of resolve(): the files a confirmed set with this key would
    actually be applied to. A file matching the key but already won by a MORE
    specific confirmed set is excluded — resolve() would keep picking that set,
    so promising the file here would be a lie.

    An equally specific winner is the same key by construction (the file matched
    both), so a re-confirm of an existing key still counts its own files.
    """
    tier = key_tier(phone_model, device_id, vehicle_id)
    applying = []
    for f in files_resolving_to(session, vehicle_type, phone_model,
                                device_id, vehicle_id):
        winner = resolve(session, model, keys_from_meta(f.recording_meta))
        if winner is None or key_tier(winner.phone_model, winner.device_id,
                                      winner.vehicle_id) <= tier:
            applying.append(f)
    return applying


def _live_files(session: Session) -> list[SourceFile]:
    return list(session.scalars(
        select(SourceFile).where(SourceFile.source_deleted.is_(False))).all())


def _snapshot(cs: CoefficientSet | None) -> dict | None:
    if cs is None:
        return None
    # Copy: the snapshot must not alias the live ORM dict of the set
    return {'set_id': cs.id, 'name': cs.name, 'params': dict(cs.params or {})}


def resolve_for_meta(session: Session, recording_meta: dict | None) -> dict:
    """{'eq3': snapshot|None, 'eq6_bias': snapshot|None} for one recording."""
    keys = keys_from_meta(recording_meta)
    return {model: _snapshot(resolve(session, model, keys)) for model in MODELS}


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
