"""
References API: upload (parses + validates the profilometer xlsx), list,
detail, delete. Deleting a reference keeps its comparisons (Comparison.
reference_id is NOT NULL) — the row is marked source_deleted and the data
dir leaves storage/reference/ (mirrors the files.py delete contract).
"""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import ReferenceOut
from src.core.config import get_settings
from src.db.models import ReferenceDataset
from src.db.session import get_session
from src.services.reference_forms import parse_form_xlsx
from src.services.references import delete_reference_data, store_reference

router = APIRouter(prefix='/references', tags=['references'])


def _to_out(ref: ReferenceDataset) -> ReferenceOut:
    out = ReferenceOut.model_validate(ref)
    out.comparisons_count = len(ref.comparisons)
    return out


@router.post('', status_code=201, response_model=ReferenceOut)
def upload_reference(
    file: UploadFile,
    measured_at: str | None = Form(None),
    road_name: str | None = Form(None),
    session: Session = Depends(get_session),
):
    settings = get_settings()
    filename = Path(file.filename or 'reference.xlsx').name

    existing = session.scalar(select(ReferenceDataset).where(ReferenceDataset.filename == filename))
    if existing is not None:
        raise HTTPException(409, f"Reference '{filename}' already exists")

    # Stream to a temp file first: a parse failure must leave storage/ clean
    with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        # Only a parse failure is a client error (422) with storage left clean;
        # once parsing succeeds, store_reference's own row/dir are on the hook
        # for cleaning up after themselves on a persistence failure.
        try:
            form = parse_form_xlsx(str(tmp_path))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        row = store_reference(session, settings, form, tmp_path, filename, measured_at, road_name)
    finally:
        tmp_path.unlink(missing_ok=True)

    return _to_out(row)


@router.get('', response_model=list[ReferenceOut])
def list_references(session: Session = Depends(get_session)):
    refs = session.scalars(
        select(ReferenceDataset).order_by(ReferenceDataset.uploaded_at.desc(), ReferenceDataset.id.desc())
    ).all()
    return [_to_out(r) for r in refs]


@router.get('/{ref_id}', response_model=ReferenceOut)
def get_reference(ref_id: int, session: Session = Depends(get_session)):
    row = session.get(ReferenceDataset, ref_id)
    if row is None:
        raise HTTPException(404, 'Reference not found')
    return _to_out(row)


@router.delete('/{ref_id}', status_code=204)
def delete_reference(ref_id: int, session: Session = Depends(get_session)):
    row = session.get(ReferenceDataset, ref_id)
    if row is None:
        raise HTTPException(404, 'Reference not found')
    settings = get_settings()
    delete_reference_data(settings, row)
    row.source_deleted = True
    session.commit()
