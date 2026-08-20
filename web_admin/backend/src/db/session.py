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


# Nullable columns added to tables that predate them, as {table: {column: type}}.
# SQLite's create_all() never ALTERs an existing table, so every column here is
# added in place, once (idempotent: skipped when already present).
_ADDED_COLUMNS = {
    'analysis_runs': {'eq3_set_id': 'INTEGER', 'eq6_bias_set_id': 'INTEGER'},
    'coefficient_sets': {'aggregate_comparison_id': 'INTEGER',
                         'device_id': 'TEXT', 'vehicle_id': 'TEXT'},
}


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
    _ensure_run_columns(engine)


def _ensure_run_columns(engine) -> None:
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {c['name'] for c in inspector.get_columns(table)}
            for column, sql_type in columns.items():
                if column not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {sql_type}'))


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session
