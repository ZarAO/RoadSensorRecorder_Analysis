"""
Engine/session wiring. The engine is created once per app in create_app()'s
lifespan and stored on app.state; get_session is the FastAPI dependency.
"""

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.db.models import Base


def make_engine(db_url: str):
    # check_same_thread=False: the worker thread of the job queue shares the
    # SQLite file with request handlers; SQLAlchemy serializes per-connection
    connect_args = {'check_same_thread': False} if db_url.startswith('sqlite') else {}
    return create_engine(db_url, connect_args=connect_args)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_run_columns(engine)


def _ensure_run_columns(engine) -> None:
    # SQLite create_all() never ALTERs an existing table; add Phase-3 columns in place
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if 'analysis_runs' not in inspector.get_table_names():
        return
    existing = {c['name'] for c in inspector.get_columns('analysis_runs')}
    with engine.begin() as conn:
        for column in ('eq3_set_id', 'eq6_bias_set_id'):
            if column not in existing:
                conn.execute(text(f'ALTER TABLE analysis_runs ADD COLUMN {column} INTEGER'))


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
