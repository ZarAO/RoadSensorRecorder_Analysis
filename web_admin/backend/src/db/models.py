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
