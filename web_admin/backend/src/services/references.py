"""
Reference dataset storage: parses an uploaded profilometer xlsx form, persists
the ReferenceDataset row, then writes the parsed artifacts to
storage_reference_dir/<id>/ (original.xlsx + intervals_{step_m}m.csv).
"""

import shutil
from pathlib import Path

from src.core.config import Settings
from src.db.models import ReferenceDataset
from src.services.reference_forms import parse_form_xlsx


def reference_dir(settings: Settings, ref: ReferenceDataset) -> Path:
    return settings.storage_reference_dir / str(ref.id)


def store_reference(session, settings: Settings, tmp_xlsx: Path, original_name: str,
                     measured_at: str | None, road_name: str | None) -> ReferenceDataset:
    form = parse_form_xlsx(str(tmp_xlsx))  # ValueError propagates to the caller

    row = ReferenceDataset(
        filename=original_name,
        road_name=road_name or form.road_name,
        direction=form.direction,
        lane=form.lane,
        category=form.category,
        step_m=form.step_m,
        measured_at=measured_at,
        intervals_count=len(form.intervals),
        chainage_span_m=form.chainage_span_m,
        bbox=form.bbox,
        parse_warnings=form.warnings,
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    ref_dir = reference_dir(settings, row)
    ref_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(tmp_xlsx), ref_dir / 'original.xlsx')
    form.intervals.to_csv(
        ref_dir / f'intervals_{int(form.step_m)}m.csv',
        index=False, encoding='utf-8', lineterminator='\n',
    )
    return row


def delete_reference_data(settings: Settings, ref: ReferenceDataset) -> None:
    shutil.rmtree(reference_dir(settings, ref), ignore_errors=True)
