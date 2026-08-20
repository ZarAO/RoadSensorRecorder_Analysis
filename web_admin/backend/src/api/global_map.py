from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.db.session import get_session
from src.services.global_map import load_global_map, rebuild_global_map

router = APIRouter(prefix='/global-map', tags=['global-map'])


@router.post('/rebuild')
def rebuild(session: Session = Depends(get_session)):
    return rebuild_global_map(session, get_settings())


@router.get('')
def get_map(session: Session = Depends(get_session)):
    return load_global_map(session, get_settings())
