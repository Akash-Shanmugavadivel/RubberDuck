"""Authenticated operational monitoring endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import get_current_user, get_monitoring_service
from ..models import User
from ..schemas.monitoring import MonitoringSummaryResponse
from ..services.monitoring import MonitoringAPIService

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/summary", response_model=MonitoringSummaryResponse)
def monitoring_summary(
    _: Annotated[User, Depends(get_current_user)],
    monitoring: Annotated[MonitoringAPIService, Depends(get_monitoring_service)],
    window_seconds: Annotated[
        float | None,
        Query(ge=60, le=2_592_000),
    ] = 86_400,
) -> MonitoringSummaryResponse:
    try:
        return monitoring.summary(window_seconds)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Monitoring data is temporarily unavailable",
        ) from error
