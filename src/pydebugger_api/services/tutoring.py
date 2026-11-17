"""Ownership-aware access to the existing tutoring engine."""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from pydebugger.models import (
    AssistantMode,
    ChatMessage,
    HintProgress,
    TutorResponse,
)

from ..models import DocumentRecord
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
    ) -> TutorResponse:
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
        return self.engine.answer(query.strip(), mode, owned_ids, history)

    def next_hint(
        self,
        problem: str,
        history: list[ChatMessage],
        previous_hints: list[str],
    ) -> HintProgress:
        return self.engine.next_hint(
            problem.strip(), history, [hint.strip() for hint in previous_hints]
        )
