"""Authenticated isolated-execution endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pydebugger.jobs import JobQueueFullError
from pydebugger.models import ExecutionTestCase

from ..dependencies import get_current_user, get_execution_service, get_session
from ..models import User
from ..schemas.execution import (
    ExecutionJobResponse,
    ProjectExecutionRequest,
    SingleFileExecutionRequest,
)
from ..services.documents import OwnedResourceNotFoundError
from ..services.execution import ExecutionAPIService

router = APIRouter(prefix="/executions", tags=["execution"])


def _execution_error(error: Exception) -> HTTPException:
    if isinstance(error, OwnedResourceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, JobQueueFullError):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(error)
        )
    if isinstance(error, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    if isinstance(error, SQLAlchemyError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Execution job persistence is temporarily unavailable",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Execution operation failed",
    )


@router.post(
    "/single-file",
    response_model=ExecutionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_single_file(
    request: SingleFileExecutionRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    execution: Annotated[ExecutionAPIService, Depends(get_execution_service)],
) -> ExecutionJobResponse:
    try:
        job = execution.start_single(session, user.id, request.source)
    except Exception as error:
        raise _execution_error(error) from error
    return ExecutionJobResponse.from_job(job)


@router.post(
    "/project",
    response_model=ExecutionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_project(
    request: ProjectExecutionRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    execution: Annotated[ExecutionAPIService, Depends(get_execution_service)],
) -> ExecutionJobResponse:
    tests = [
        ExecutionTestCase(
            name=item.name,
            stdin=item.stdin,
            expected_output=item.expected_output,
        )
        for item in request.tests
    ]
    try:
        job = execution.start_project(
            session, user.id, request.files, request.entrypoint, tests
        )
    except Exception as error:
        raise _execution_error(error) from error
    return ExecutionJobResponse.from_job(job)


@router.get("/{execution_id}", response_model=ExecutionJobResponse)
def get_execution(
    execution_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    execution: Annotated[ExecutionAPIService, Depends(get_execution_service)],
) -> ExecutionJobResponse:
    try:
        job = execution.get_job(session, user.id, execution_id)
    except Exception as error:
        raise _execution_error(error) from error
    return ExecutionJobResponse.from_job(job)


@router.post("/{execution_id}/cancel", response_model=ExecutionJobResponse)
def cancel_execution(
    execution_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    execution: Annotated[ExecutionAPIService, Depends(get_execution_service)],
) -> ExecutionJobResponse:
    try:
        job = execution.cancel_job(session, user.id, execution_id)
    except Exception as error:
        raise _execution_error(error) from error
    return ExecutionJobResponse.from_job(job)
