"""Authenticated grounded-answer and hint endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pydebugger.retrieval import RetrievalError

from ..dependencies import (
    get_current_instructor,
    get_current_user,
    get_session,
    get_tutoring_service,
)
from ..models import ConversationRecord, StudentNoteRecord, TutorPolicyRecord, User
from ..schemas.tutoring import (
    CitationResponse,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    HintRequest,
    HintResponse,
    StoredMessageResponse,
    StudentNoteCreate,
    StudentNoteResponse,
    TutorAnswerRequest,
    TutorAnswerResponse,
    TutorPolicyResponse,
    TutorPolicyUpdate,
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
            request.behavior,
            request.difficulty,
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


@router.get("/policy", response_model=TutorPolicyResponse)
def get_policy(
    _: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> TutorPolicyResponse:
    try:
        return _policy_response(tutoring.get_policy(session))
    except Exception as error:
        raise _tutor_error(error) from error


@router.put("/policy", response_model=TutorPolicyResponse)
def update_policy(
    request: TutorPolicyUpdate,
    instructor: Annotated[User, Depends(get_current_instructor)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> TutorPolicyResponse:
    try:
        policy = tutoring.update_policy(
            session,
            instructor.id,
            allow_direct_answers=request.allow_direct_answers,
            allow_code_solutions=request.allow_code_solutions,
            hints_only=request.hints_only,
        )
    except Exception as error:
        raise _tutor_error(error) from error
    return _policy_response(policy)


@router.patch(
    "/conversations/{conversation_id}", response_model=ConversationSummaryResponse
)
def update_conversation(
    conversation_id: uuid.UUID,
    request: ConversationUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> ConversationSummaryResponse:
    try:
        conversation = tutoring.update_conversation(
            session,
            user.id,
            conversation_id,
            title=request.title,
            pinned=request.pinned,
        )
    except Exception as error:
        raise _tutor_error(error) from error
    return _conversation_summary(conversation)


@router.post(
    "/conversations/{conversation_id}/regenerate", response_model=TutorAnswerResponse
)
def regenerate_answer(
    conversation_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> TutorAnswerResponse:
    try:
        result, conversation = tutoring.regenerate(session, user.id, conversation_id)
    except Exception as error:
        raise _tutor_error(error) from error
    return TutorAnswerResponse.from_result(result, conversation.id)


@router.get("/notes", response_model=list[StudentNoteResponse])
def list_notes(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> list[StudentNoteResponse]:
    return [_note_response(note) for note in tutoring.list_notes(session, user.id)]


@router.post("/notes", response_model=StudentNoteResponse, status_code=201)
def create_note(
    request: StudentNoteCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> StudentNoteResponse:
    try:
        note = tutoring.create_note(
            session,
            user.id,
            kind=request.kind,
            title=request.title,
            content=request.content,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            citations=[item.model_dump() for item in request.citations],
        )
    except Exception as error:
        raise _tutor_error(error) from error
    return _note_response(note)


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(
    note_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    tutoring: Annotated[TutoringService, Depends(get_tutoring_service)],
) -> Response:
    try:
        tutoring.delete_note(session, user.id, note_id)
    except Exception as error:
        raise _tutor_error(error) from error
    return Response(status_code=204)


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
        behavior=record.behavior,
        difficulty=record.difficulty,
        pinned=record.pinned,
        document_ids=list(record.document_ids),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _policy_response(record: TutorPolicyRecord) -> TutorPolicyResponse:
    return TutorPolicyResponse(
        allow_direct_answers=record.allow_direct_answers,
        allow_code_solutions=record.allow_code_solutions,
        hints_only=record.hints_only,
        updated_at=record.updated_at,
        updated_by=record.updated_by,
    )


def _note_response(record: StudentNoteRecord) -> StudentNoteResponse:
    return StudentNoteResponse(
        id=record.id,
        kind=record.kind,
        title=record.title,
        content=record.content,
        conversation_id=record.conversation_id,
        message_id=record.message_id,
        citations=[CitationResponse.model_validate(item) for item in record.citations],
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
