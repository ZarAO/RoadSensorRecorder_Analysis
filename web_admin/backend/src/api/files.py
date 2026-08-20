"""
Files API: upload (with immediate contract validation), list, delete.
Deleting a file keeps its runs and their artifacts (spec §4) — the row is
marked source_deleted and the CSV leaves storage/data/.
"""

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import FileOut
from src.core.config import get_settings
from src.db.models import SourceFile
from src.db.session import get_session
from src.services.preview import probe_csv

router = APIRouter(prefix='/files', tags=['files'])


def _to_out(f: SourceFile) -> FileOut:
    out = FileOut.model_validate(f)
    out.runs_count = len(f.runs)
    return out


@router.post('', status_code=201, response_model=FileOut)
def upload_file(file: UploadFile, session: Session = Depends(get_session)):
    settings = get_settings()
    filename = Path(file.filename or 'upload.csv').name

    existing = session.scalar(select(SourceFile).where(SourceFile.filename == filename))
    if existing is not None:
        raise HTTPException(409, f"файл '{filename}' вже існує")

    # Stream to a temp file first: a contract violation must leave storage/ clean
    with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        info = probe_csv(str(tmp_path))
    except ValueError as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc))

    target = settings.storage_data_dir / filename
    settings.storage_data_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_path), target)

    row = SourceFile(
        filename=filename,
        size_bytes=target.stat().st_size,
        duration_s=info['duration_s'],
        fs_hz=info['fs_hz'],
        gps_coverage_ratio=info['gps_coverage_ratio'],
        recording_meta=info['recording_meta'],
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_out(row)


@router.get('', response_model=list[FileOut])
def list_files(session: Session = Depends(get_session)):
    files = session.scalars(
        select(SourceFile).order_by(SourceFile.uploaded_at.desc(), SourceFile.id.desc())
    ).all()
    return [_to_out(f) for f in files]


@router.delete('/{file_id}', status_code=204)
def delete_file(file_id: int, session: Session = Depends(get_session)):
    row = session.get(SourceFile, file_id)
    if row is None:
        raise HTTPException(404, 'File not found')
    settings = get_settings()
    (settings.storage_data_dir / row.filename).unlink(missing_ok=True)
    row.source_deleted = True
    session.commit()
