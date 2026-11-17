"""Shared FastAPI dependencies."""

from collections.abc import Generator
from pathlib import Path
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from pydebugger.config import Settings
from pydebugger.engine import PyDebuggerEngine

from .database import Database
from .models import User
from .services.auth import AuthenticationService, InvalidCredentialsError
from .services.documents import DocumentService
from .services.execution import ExecutionAPIService, ExecutionEngine
from .services.monitoring import MonitoringAPIService, MonitoringEngine
from .services.tutoring import TutorEngine, TutoringService

bearer_scheme = HTTPBearer(auto_error=False)


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> Generator[Session, None, None]:
    yield from database.session()


def get_authentication(request: Request) -> AuthenticationService:
    return request.app.state.authentication


def get_document_service(request: Request) -> DocumentService:
    service = request.app.state.document_service
    if service is not None:
        return service
    with request.app.state.document_service_lock:
        service = request.app.state.document_service
        if service is None:
            engine_settings = Settings.from_env(Path.cwd())
            service = DocumentService(PyDebuggerEngine(engine_settings))
            service.bind_database(request.app.state.database)
            request.app.state.document_service = service
    return service


def get_tutoring_service(
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> TutoringService:
    return TutoringService(cast(TutorEngine, documents.engine))


def get_execution_service(
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> ExecutionAPIService:
    return ExecutionAPIService(cast(ExecutionEngine, documents.engine))


def get_monitoring_service(
    documents: Annotated[DocumentService, Depends(get_document_service)],
) -> MonitoringAPIService:
    return MonitoringAPIService(cast(MonitoringEngine, documents.engine))


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_session)],
    authentication: Annotated[AuthenticationService, Depends(get_authentication)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise unauthorized
    try:
        return authentication.user_from_token(session, credentials.credentials)
    except InvalidCredentialsError as error:
        raise unauthorized from error


def get_current_instructor(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != "instructor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Instructor access required",
        )
    return user
