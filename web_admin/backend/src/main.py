"""
FastAPI application factory for the web admin.
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.config import get_settings
from src.core.queue import make_queue
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
        app.state.queue = make_queue()
        yield
        app.state.queue.shutdown()
        app.state.engine.dispose()

    app = FastAPI(title='Road Quality Admin', lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['http://localhost:4200'],
        allow_methods=['*'],
        allow_headers=['*'],
    )
    app.include_router(health_router, prefix='/api')

    from src.api.dashboard import router as dashboard_router
    from src.api.files import router as files_router
    from src.api.global_map import router as global_map_router
    from src.api.references import router as references_router
    from src.api.runs import router as runs_router
    app.include_router(files_router, prefix='/api')
    app.include_router(runs_router, prefix='/api')
    app.include_router(global_map_router, prefix='/api')
    app.include_router(dashboard_router, prefix='/api')
    app.include_router(references_router, prefix='/api')
    return app


app = create_app()
