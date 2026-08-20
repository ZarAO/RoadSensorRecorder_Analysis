"""
Metadata-only persistence: files and analysis runs. Artifacts live on disk in
storage/results/; the DB never stores them (spec §2).
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SourceFile(Base):
    __tablename__ = 'source_files'

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)
    size_bytes: Mapped[int]
    uploaded_at: Mapped[datetime] = mapped_column(default=_utcnow)
    source_deleted: Mapped[bool] = mapped_column(default=False)

    # Upload-time preview (one light pass over the CSV)
    duration_s: Mapped[Optional[float]] = mapped_column(default=None)
    fs_hz: Mapped[Optional[float]] = mapped_column(default=None)
    gps_coverage_ratio: Mapped[Optional[float]] = mapped_column(default=None)
    # Stage D: parse_recording_metadata() output (schema, vehicle, events,
    # footer, clean_stop, warnings); empty fields for pre-v2.1 files
    recording_meta: Mapped[Optional[dict]] = mapped_column(JSON, default=None)

    runs: Mapped[list['AnalysisRun']] = relationship(back_populates='file')


class AnalysisRun(Base):
    __tablename__ = 'analysis_runs'

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey('source_files.id'))
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    finished_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String, default='queued')  # queued|running|done|failed
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result_dir: Mapped[Optional[str]] = mapped_column(default=None)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    error: Mapped[Optional[str]] = mapped_column(default=None)
    log_path: Mapped[Optional[str]] = mapped_column(default=None)

    file: Mapped[SourceFile] = relationship(back_populates='runs')

    # Phase 3: coefficient sets resolved per model (eq3, eq6_bias) for this run
    eq3_set_id: Mapped[Optional[int]] = mapped_column(ForeignKey('coefficient_sets.id'), default=None)
    eq6_bias_set_id: Mapped[Optional[int]] = mapped_column(ForeignKey('coefficient_sets.id'), default=None)


class ReferenceDataset(Base):
    """Profilometer/reference road-quality dataset parsed from an uploaded xlsx (Phase 3)."""

    __tablename__ = 'reference_datasets'

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String, unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(default=_utcnow)
    road_name: Mapped[str]
    direction: Mapped[Optional[str]] = mapped_column(default=None)
    lane: Mapped[Optional[int]] = mapped_column(default=None)
    category: Mapped[Optional[int]] = mapped_column(default=None)
    step_m: Mapped[float]
    # Manual ISO date entered at upload time: the form's own date cell is stale by policy
    measured_at: Mapped[Optional[str]] = mapped_column(default=None)
    intervals_count: Mapped[int]
    chainage_span_m: Mapped[float]
    bbox: Mapped[Optional[list]] = mapped_column(JSON, default=None)  # [min_lat, min_lon, max_lat, max_lon]
    parse_warnings: Mapped[list] = mapped_column(JSON, default=list)
    source_deleted: Mapped[bool] = mapped_column(default=False)

    comparisons: Mapped[list['Comparison']] = relationship(back_populates='reference')


class Comparison(Base):
    """A single run-vs-reference comparison job (Phase 3)."""

    __tablename__ = 'comparisons'

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('analysis_runs.id'))
    reference_id: Mapped[int] = mapped_column(ForeignKey('reference_datasets.id'))
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    status: Mapped[str] = mapped_column(String, default='queued')  # queued|running|done|failed
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result_dir: Mapped[Optional[str]] = mapped_column(default=None)
    summary: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    error: Mapped[Optional[str]] = mapped_column(default=None)

    run: Mapped[AnalysisRun] = relationship()
    reference: Mapped[ReferenceDataset] = relationship(back_populates='comparisons')


class CoefficientSet(Base):
    """A confirmable set of IRI-equation coefficients (Phase 3)."""

    __tablename__ = 'coefficient_sets'

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    model: Mapped[str] = mapped_column(String)  # eq3|eq6_bias
    params: Mapped[dict] = mapped_column(JSON)  # {A, B} for eq3, {bias} for eq6_bias
    vehicle_type: Mapped[Optional[str]] = mapped_column(default=None)
    phone_model: Mapped[Optional[str]] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String, default='draft')  # draft|confirmed|archived
    comparison_id: Mapped[Optional[int]] = mapped_column(ForeignKey('comparisons.id'), default=None)
    stats_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(default=None)
    confirmed_note: Mapped[Optional[str]] = mapped_column(default=None)
