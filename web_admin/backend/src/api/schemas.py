"""
Pydantic response/request schemas mirrored by the frontend DTOs.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    size_bytes: int
    uploaded_at: datetime
    source_deleted: bool
    duration_s: Optional[float] = None
    fs_hz: Optional[float] = None
    gps_coverage_ratio: Optional[float] = None
    recording_meta: Optional[dict] = None
    runs_count: int = 0


class ReferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    uploaded_at: datetime
    road_name: str
    direction: Optional[str] = None
    lane: Optional[int] = None
    category: Optional[int] = None
    step_m: float
    measured_at: Optional[str] = None
    intervals_count: int
    chainage_span_m: float
    bbox: Optional[list] = None
    parse_warnings: list = []
    source_deleted: bool
    comparisons_count: int = 0


class RunCreate(BaseModel):
    file_id: int
    params: dict = {}


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: int
    filename: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    status: str
    params: dict
    result_dir: Optional[str] = None
    summary: Optional[dict] = None
    error: Optional[str] = None
    # Enrichment (runs._to_out): the recording's device string exactly as
    # coefficient resolution matches on it; null for a pre-v3 recording
    phone_model: Optional[str] = None
    # Contract v3.1 identity keys of the recording — the calibration key the
    # set-creation dialog auto-fills; null for every older recording
    device_id: Optional[str] = None
    vehicle_id: Optional[str] = None


class ComparisonCreate(BaseModel):
    run_id: int
    reference_id: int
    params: dict = {}


class ComparisonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    reference_id: int
    created_at: datetime
    status: str
    params: dict
    result_dir: Optional[str] = None
    summary: Optional[dict] = None
    error: Optional[str] = None
    run_filename: Optional[str] = None
    reference_road: Optional[str] = None


class AggregateCreate(BaseModel):
    reference_id: int
    run_ids: list[int]
    params: dict = {}


class AggregateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference_id: int
    run_ids: list
    created_at: datetime
    status: str
    params: dict
    result_dir: Optional[str] = None
    summary: Optional[dict] = None
    error: Optional[str] = None
    reference_road: Optional[str] = None
    run_filenames: list[str] = []


def _known_model(v: str) -> str:
    if v not in ('eq3', 'eq6_bias'):
        raise ValueError("model must be one of 'eq3', 'eq6_bias'")
    return v


class CoefficientSetCreate(BaseModel):
    # Provenance: exactly one of the two (enforced in the router, which answers
    # with the Ukrainian operator-facing message)
    comparison_id: Optional[int] = None
    aggregate_comparison_id: Optional[int] = None
    model: str
    name: str
    vehicle_type: str
    phone_model: Optional[str] = None
    # Auto-filled by the dialog from the run (contract v3.1); both set = the
    # exact identity tier, both null = a legacy phone/vehicle-type key
    device_id: Optional[str] = None
    vehicle_id: Optional[str] = None

    @field_validator('model')
    @classmethod
    def _model_must_be_known(cls, v: str) -> str:
        return _known_model(v)


class PreviewResolutionIn(BaseModel):
    """The FULL resolution key of a set the operator is about to create or
    confirm. `model` narrows the count only through the true inverse: a file
    already won by a more specific confirmed set of the same model is excluded."""

    model: str
    # A set may carry no vehicle type (nothing resolves then) — 0 matches, not 422
    vehicle_type: Optional[str] = None
    phone_model: Optional[str] = None
    device_id: Optional[str] = None
    vehicle_id: Optional[str] = None

    @field_validator('model')
    @classmethod
    def _model_must_be_known(cls, v: str) -> str:
        return _known_model(v)


class PreviewResolutionOut(BaseModel):
    files_matched: int
    filenames: list[str] = []


class CoefficientSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model: str
    params: dict
    vehicle_type: Optional[str] = None
    phone_model: Optional[str] = None
    device_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    status: str
    comparison_id: Optional[int] = None
    aggregate_comparison_id: Optional[int] = None
    stats_snapshot: Optional[dict] = None
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    confirmed_note: Optional[str] = None


class ConfirmIn(BaseModel):
    note: Optional[str] = None


class ConfirmOut(BaseModel):
    set: CoefficientSetOut
    archived_set_id: Optional[int] = None
    reanalyze_candidates: int
