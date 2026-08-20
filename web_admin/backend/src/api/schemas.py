"""
Pydantic response/request schemas mirrored by the frontend DTOs.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


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
