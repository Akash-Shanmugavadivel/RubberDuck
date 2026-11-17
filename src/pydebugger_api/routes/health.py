"""Liveness and dependency-readiness endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..database import Database
from ..dependencies import get_database

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    service: str = "pydebugger-api"


class ReadinessResponse(HealthResponse):
    database: str
    checks: dict[str, bool]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report whether the API process can serve requests."""

    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
def ready(
    database: Annotated[Database, Depends(get_database)],
) -> ReadinessResponse | JSONResponse:
    """Report whether required PostgreSQL services are available."""

    if hasattr(database, "readiness_report"):
        report = database.readiness_report()
        is_ready = report.ready
        detail = report.detail
        checks = {
            "postgresql": report.postgresql,
            "pgvector": report.pgvector,
            "migrations": report.migrations,
        }
    else:
        is_ready, detail = database.readiness()
        checks = {
            "postgresql": is_ready,
            "pgvector": is_ready,
            "migrations": is_ready,
        }
    response = ReadinessResponse(
        status="ready" if is_ready else "not_ready",
        database=detail,
        checks=checks,
    )
    if not is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(),
        )
    return response
