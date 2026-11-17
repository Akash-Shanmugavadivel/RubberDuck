"""Ownership-aware access to the existing tutoring engine."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pydebugger.models import (
    AssistantMode,
    ChatMessage,
    HintProgress,
    TutorResponse,
)

from ..models import (
    ConversationMessageRecord,
    ConversationRecord,
    DocumentRecord,
)
from .documents import OwnedResourceNotFoundError


class TutorEngine(Protocol):
    def answer(
        self,
        query: str,
        mode: AssistantMode,
        document_ids: set[str],
        history: list[ChatMessage] | None = None,
    ) -> TutorResponse: ...

    def next_hint(
        self,
        problem: str,
        history: list[ChatMessage] | None = None,
        previous_hints: list[str] | None = None,
    ) -> HintProgress: ...


class TutoringService:
    def __init__(self, engine: TutorEngine) -> None:
        self.engine = engine

    def answer(
        self,
        session: Session,
        owner_id: uuid.UUID,
        query: str,
        mode: AssistantMode,
        document_ids: set[str],
        history: list[ChatMessage],
        conversation_id: uuid.UUID | None = None,
    ) -> tuple[TutorResponse, ConversationRecord]:
        cleaned_ids = {
            document_id.strip() for document_id in document_ids if document_id.strip()
        }
        if not cleaned_ids:
            raise ValueError("Select at least one document")
        owned_ids = set(
            session.scalars(
                select(DocumentRecord.id).where(
                    DocumentRecord.owner_id == owner_id,
                    DocumentRecord.id.in_(cleaned_ids),
                )
            ).all()
        )
        if owned_ids != cleaned_ids:
            raise OwnedResourceNotFoundError(
                "One or more selected documents were not found"
            )
        conversation = (
            self.get_conversation(session, owner_id, conversation_id)
            if conversation_id is not None
            else None
        )
        stored_history = (
            self._history(session, conversation.id) if conversation is not None else []
        )
        result = self.engine.answer(
            query.strip(), mode, owned_ids, stored_history or history
        )
        mode_name = (
            "rubber_duck" if mode is AssistantMode.RUBBER_DUCK else "programming_tutor"
        )
        if conversation is None:
            conversation = ConversationRecord(
                owner_id=owner_id,
                title=self._title(query),
                mode=mode_name,
                document_ids=sorted(owned_ids),
            )
            session.add(conversation)
            session.flush()
        else:
            conversation = self.get_conversation(
                session, owner_id, conversation.id, lock=True
            )
            conversation.mode = mode_name
            conversation.document_ids = sorted(owned_ids)
            conversation.updated_at = datetime.now(UTC)
        next_position = (
            int(
                session.scalar(
                    select(func.max(ConversationMessageRecord.position)).where(
                        ConversationMessageRecord.conversation_id == conversation.id
                    )
                )
                or 0
            )
            + 1
        )
        session.add_all(
            [
                ConversationMessageRecord(
                    conversation_id=conversation.id,
                    position=next_position,
                    role="user",
                    content=query.strip(),
                    grounded=None,
                    citations=[],
                ),
                ConversationMessageRecord(
                    conversation_id=conversation.id,
                    position=next_position + 1,
                    role="assistant",
                    content=result.answer,
                    grounded=result.grounded,
                    citations=[asdict(citation) for citation in result.citations],
                ),
            ]
        )
        session.commit()
        session.refresh(conversation)
        return result, conversation

    @staticmethod
    def list_conversations(
        session: Session, owner_id: uuid.UUID
    ) -> list[ConversationRecord]:
        return list(
            session.scalars(
                select(ConversationRecord)
                .where(ConversationRecord.owner_id == owner_id)
                .order_by(ConversationRecord.updated_at.desc())
                .limit(100)
            ).all()
        )

    @staticmethod
    def get_conversation(
        session: Session,
        owner_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> ConversationRecord:
        statement = select(ConversationRecord).where(
            ConversationRecord.id == conversation_id,
            ConversationRecord.owner_id == owner_id,
        )
        if lock:
            statement = statement.with_for_update()
        conversation = session.scalar(statement)
        if conversation is None:
            raise OwnedResourceNotFoundError("Conversation not found")
        return conversation

    def conversation_messages(
        self, session: Session, conversation_id: uuid.UUID
    ) -> list[ConversationMessageRecord]:
        return list(
            session.scalars(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == conversation_id)
                .order_by(ConversationMessageRecord.position)
            ).all()
        )

    def delete_conversation(
        self, session: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> None:
        conversation = self.get_conversation(session, owner_id, conversation_id)
        session.delete(conversation)
        session.commit()

    @staticmethod
    def _history(session: Session, conversation_id: uuid.UUID) -> list[ChatMessage]:
        newest = list(
            session.scalars(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == conversation_id)
                .order_by(ConversationMessageRecord.position.desc())
                .limit(50)
            ).all()
        )
        return [
            ChatMessage(role=message.role, content=message.content)
            for message in reversed(newest)
        ]

    @staticmethod
    def _title(query: str) -> str:
        cleaned = " ".join(query.split())
        return cleaned if len(cleaned) <= 80 else f"{cleaned[:77].rstrip()}…"

    def next_hint(
        self,
        problem: str,
        history: list[ChatMessage],
        previous_hints: list[str],
    ) -> HintProgress:
        return self.engine.next_hint(
            problem.strip(), history, [hint.strip() for hint in previous_hints]
        )
