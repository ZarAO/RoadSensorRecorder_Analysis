"""
Reference dataset storage: persists a ReferenceDataset row from an already
-parsed profilometer form, then writes the parsed artifacts to
storage_reference_dir/<id>/ (original.xlsx + intervals_{step_m}m.csv).

Parsing (parse_form_xlsx) is the caller's job: it maps to 422 on ValueError
and must run before store_reference, so that any failure here — after the
row is committed — is a persistence error, not a parse error (see references.py).
"""

import shutil
from pathlib import Path

from src.core.config import Settings
from src.db.models import ReferenceDataset
from src.services.reference_forms import ParsedForm


def reference_dir(settings: Settings, ref: ReferenceDataset) -> Path:
    return settings.storage_reference_dir / str(ref.id)


def store_reference(session, settings: Settings, form: ParsedForm, tmp_xlsx: Path, original_name: str,
                     measured_at: str | None, road_name: str | None) -> ReferenceDataset:
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
    try:
        ref_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(tmp_xlsx), ref_dir / 'original.xlsx')
        form.intervals.to_csv(
            ref_dir / f'intervals_{int(form.step_m)}m.csv',
            index=False, encoding='utf-8', lineterminator='\n',
        )
    except OSError:
        # Row is already committed with the unique filename; an orphaned row
        # would block every re-upload with a false 409 while nothing exists
        # on disk. Undo the row and any partial dir, then let the caller see
        # the original failure.
        session.delete(row)
        session.commit()
        shutil.rmtree(ref_dir, ignore_errors=True)
        raise
    return row


def delete_reference_data(settings: Settings, ref: ReferenceDataset) -> None:
    shutil.rmtree(reference_dir(settings, ref), ignore_errors=True)
