from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.api.schemas import DashboardOut
from src.db.session import get_session
from src.services.dashboard import build_dashboard

router = APIRouter(prefix='/dashboard', tags=['dashboard'])


@router.get('', response_model=DashboardOut)
def get_dashboard(session: Session = Depends(get_session)):
    return build_dashboard(session)
