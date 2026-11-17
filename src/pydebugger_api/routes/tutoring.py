"""Authenticated grounded-answer and hint endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from pydebugger.retrieval import RetrievalError

from ..dependencies import get_current_user, get_session, get_tutoring_service
from ..models import User
from ..schemas.tutoring import (
    HintRequest,
    HintResponse,
    TutorAnswerRequest,
    TutorAnswerResponse,
)
from ..services.documents import OwnedResourceNotFoundError
from ..services.tutoring import TutoringService

router = APIRouter(prefix="/tutor", tags=["tutoring"])


def _tutor_error(error: Exception) -> HTTPException:
    if isinstance(error, OwnedResourceNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    if isinstance(error, RetrievalError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Course-material retrieval is temporarily unavailable",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="The tutoring model is temporarily unavailable",
    )


@router.post("/answer", response_model=TutorAnswerResponse)
def answer(
    request: TutorAnswerRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> TutorAnswerResponse:
    try:
        result = tutoring.answer(
            session,
            user.id,
            request.query,
            request.mode.to_engine(),
            set(request.document_ids),
            [message.to_engine() for message in request.history],
        )
    except Exception as error:
        raise _tutor_error(error) from error
    return TutorAnswerResponse.from_result(result)


@router.post("/hint", response_model=HintResponse)
def next_hint(
    request: HintRequest,
    _: Annotated[User, Depends(get_current_user)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> HintResponse:
    try:
        result = tutoring.next_hint(
            request.problem,
            [message.to_engine() for message in request.history],
            request.previous_hints,
        )
    except Exception as error:
        raise _tutor_error(error) from error
    return HintResponse.from_result(result)
