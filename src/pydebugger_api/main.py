"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import APISettings, get_api_settings
from .database import Database
from .routes.auth import router as auth_router
from .routes.documents import router as documents_router
from .routes.execution import router as execution_router
from .routes.health import router as health_router
from .routes.monitoring import router as monitoring_router
from .routes.tutoring import router as tutoring_router
from .services.auth import AuthenticationService
from .services.documents import DocumentService
from .services.job_persistence import recover_interrupted_jobs


def create_app(
    settings: APISettings | None = None,
    database: Database | None = None,
    document_service: DocumentService | None = None,
) -> FastAPI:
    """Build the API with replaceable dependencies for focused tests."""

    resolved_settings = settings or get_api_settings()
    resolved_database = database or Database(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if isinstance(resolved_database, Database):
            recover_interrupted_jobs(resolved_database)
        yield
        active_documents = app.state.document_service
        if active_documents is not None:
            active_documents.shutdown()
        resolved_database.dispose()

    app = FastAPI(
        title="PyDebugger API",
        description="Backend API for the RubberDuck learning platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.database = resolved_database
    app.state.authentication = AuthenticationService(resolved_settings)
    app.state.document_service = document_service
    app.state.document_service_lock = Lock()
    if document_service is not None:
        document_service.bind_database(resolved_database)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(execution_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(monitoring_router, prefix="/api/v1")
    app.include_router(tutoring_router, prefix="/api/v1")
    return app


app = create_app()
