"""Authenticated grounded-answer and hint endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pydebugger.retrieval import RetrievalError

from ..dependencies import get_current_user, get_session, get_tutoring_service
from ..models import ConversationRecord, User
from ..schemas.tutoring import (
    CitationResponse,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    HintRequest,
    HintResponse,
    StoredMessageResponse,
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
    if isinstance(error, SQLAlchemyError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation storage is temporarily unavailable",
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
        result, conversation = tutoring.answer(
            session,
            user.id,
            request.query,
            request.mode.to_engine(),
            set(request.document_ids),
            [message.to_engine() for message in request.history],
            request.conversation_id,
        )
    except Exception as error:
        raise _tutor_error(error) from error
    return TutorAnswerResponse.from_result(result, conversation.id)


@router.get("/conversations", response_model=list[ConversationSummaryResponse])
def list_conversations(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> list[ConversationSummaryResponse]:
    try:
        records = tutoring.list_conversations(session, user.id)
    except Exception as error:
        raise _tutor_error(error) from error
    return [_conversation_summary(record) for record in records]


@router.get(
    "/conversations/{conversation_id}", response_model=ConversationDetailResponse
)
def get_conversation(
    conversation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> ConversationDetailResponse:
    try:
        conversation = tutoring.get_conversation(session, user.id, conversation_id)
        messages = tutoring.conversation_messages(session, conversation.id)
    except Exception as error:
        raise _tutor_error(error) from error
    summary = _conversation_summary(conversation)
    return ConversationDetailResponse(
        **summary.model_dump(),
        messages=[
            StoredMessageResponse(
                id=message.id,
                position=message.position,
                role=message.role,
                content=message.content,
                grounded=message.grounded,
                citations=[
                    CitationResponse.model_validate(citation)
                    for citation in message.citations
                ],
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_conversation(
    conversation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> Response:
    try:
        tutoring.delete_conversation(session, user.id, conversation_id)
    except Exception as error:
        raise _tutor_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


def _conversation_summary(record: ConversationRecord) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        id=record.id,
        title=record.title,
        mode=record.mode,
        document_ids=list(record.document_ids),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
