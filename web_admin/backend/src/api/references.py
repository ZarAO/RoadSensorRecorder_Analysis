"""
References API: upload (parses + validates the profilometer xlsx), list,
detail, delete. Deleting a reference keeps its comparisons (Comparison.
reference_id is NOT NULL) — the row is marked source_deleted and the data
dir leaves storage/reference/ (mirrors the files.py delete contract).
"""

import shutil
import tempfile
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from profilometer_validation.g3 import G3Pass, build_section_reference
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import ReferenceOut
from src.core.config import get_settings
from src.db.models import ReferenceDataset
from src.db.session import get_session
from src.services.comparison import MSG_REFERENCE_DELETED
from src.services.reference_forms import parse_form_xlsx
from src.services.references import (
    build_reference_geojson,
    delete_reference_data,
    load_reference_intervals,
    store_g3_reference,
    store_reference,
)

router = APIRouter(prefix='/references', tags=['references'])


def _to_out(ref: ReferenceDataset) -> ReferenceOut:
    out = ReferenceOut.model_validate(ref)
    out.comparisons_count = len(ref.comparisons)
    return out


def _ref_or_404(ref_id: int, session: Session) -> ReferenceDataset:
    row = session.get(ReferenceDataset, ref_id)
    if row is None:
        raise HTTPException(404, 'Reference not found')
    return row


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
        raise HTTPException(409, f"еталон '{filename}' вже існує")

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


G3_PARTS = {' IRI.csv': 'iri', ' GNSS.csv': 'gnss', ' Profile.csv': 'profile',
            ' Information.txt': 'info'}
G3_REQUIRED = ('iri', 'gnss', 'profile')


def _group_g3_files(uploads: dict) -> dict:
    """{survey prefix: {part: text}} from uploaded device file names."""
    surveys = {}
    for name, payload in uploads.items():
        for suffix, part in G3_PARTS.items():
            if name.endswith(suffix):
                surveys.setdefault(name[:-len(suffix)], {})[part] = payload.decode('utf-8-sig')
                break
        else:
            raise HTTPException(422, f"невідомий файл G3: '{name}' (очікуються IRI.csv, "
                                     'GNSS.csv, Profile.csv, Information.txt)')
    for prefix, parts in surveys.items():
        missing = [p for p in G3_REQUIRED if p not in parts]
        if missing:
            raise HTTPException(422, f"прохід '{prefix}': бракує файлів {', '.join(missing)}")
    return surveys


@router.post('/g3', status_code=201, response_model=ReferenceOut)
def upload_g3_reference(
    files: list[UploadFile],
    road_name: str = Form(...),
    measured_at: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """One road section from one or more Walking Profiler G3 passes, each pass
    one channel (spec 2026-11-15-g3-section-reference-design.md)."""
    if not road_name.strip():
        raise HTTPException(422, 'вкажіть назву дороги або ділянки')
    uploads = {Path(f.filename or '').name: f.file.read() for f in files}
    surveys = _group_g3_files(uploads)
    try:
        passes = [G3Pass.from_texts(prefix, parts['iri'], parts['gnss'], parts['profile'],
                                    parts.get('info'))
                  for prefix, parts in sorted(surveys.items())]
        section = build_section_reference(passes)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    existing = session.scalar(select(ReferenceDataset).where(ReferenceDataset.filename == section.label))
    if existing is not None:
        raise HTTPException(409, f"еталон '{section.label}' вже існує")
    row = store_g3_reference(session, get_settings(), section, uploads,
                             road_name.strip(), measured_at)
    return _to_out(row)


@router.get('', response_model=list[ReferenceOut])
def list_references(session: Session = Depends(get_session)):
    refs = session.scalars(
        select(ReferenceDataset).order_by(ReferenceDataset.uploaded_at.desc(), ReferenceDataset.id.desc())
    ).all()
    return [_to_out(r) for r in refs]


@router.get('/{ref_id}', response_model=ReferenceOut)
def get_reference(ref_id: int, session: Session = Depends(get_session)):
    return _to_out(_ref_or_404(ref_id, session))


@router.delete('/{ref_id}', status_code=204)
def delete_reference(ref_id: int, session: Session = Depends(get_session)):
    row = _ref_or_404(ref_id, session)
    settings = get_settings()
    delete_reference_data(settings, row)
    row.source_deleted = True
    session.commit()


@router.get('/{ref_id}/intervals')
def get_reference_intervals(ref_id: int, session: Session = Depends(get_session)):
    row = _ref_or_404(ref_id, session)
    if row.source_deleted:
        raise HTTPException(409, MSG_REFERENCE_DELETED)
    df = load_reference_intervals(get_settings(), row)
    # NaN -> null: strict JSON parsers reject NaN, and a missing metric must
    # never surface as a number (analyzer invariant)
    return df.replace({np.nan: None}).to_dict('records')


@router.get('/{ref_id}/geojson')
def get_reference_geojson(ref_id: int, session: Session = Depends(get_session)):
    row = _ref_or_404(ref_id, session)
    if row.source_deleted:
        raise HTTPException(409, MSG_REFERENCE_DELETED)
    return build_reference_geojson(get_settings(), row)
