"""
FastAPI application factory for the web admin.
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.db.session import init_db, make_engine

health_router = APIRouter()


@health_router.get('/health')
def health():
    return {'status': 'ok'}


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_dirs()
        app.state.engine = make_engine(settings.db_url)
        init_db(app.state.engine)
        yield
        app.state.engine.dispose()

    app = FastAPI(title='Road Quality Admin', lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['http://localhost:4200'],
        allow_methods=['*'],
        allow_headers=['*'],
    )
    app.include_router(health_router, prefix='/api')

    from src.api.files import router as files_router
    app.include_router(files_router, prefix='/api')
    return app


app = create_app()
