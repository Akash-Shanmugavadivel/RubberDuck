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
    TeachingBehavior,
    TutorDifficulty,
    TutorPolicy,
    TutorResponse,
)

from ..models import (
    ConversationMessageRecord,
    ConversationRecord,
    DocumentRecord,
    StudentNoteRecord,
    TutorPolicyRecord,
)
from .documents import OwnedResourceNotFoundError


class TutorEngine(Protocol):
    def answer(
        self,
        query: str,
        mode: AssistantMode,
        document_ids: set[str],
        history: list[ChatMessage] | None = None,
        behavior: TeachingBehavior | None = None,
        difficulty: TutorDifficulty = TutorDifficulty.INTERMEDIATE,
        policy: TutorPolicy | None = None,
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
        behavior: TeachingBehavior = TeachingBehavior.EXPLAIN,
        difficulty: TutorDifficulty = TutorDifficulty.INTERMEDIATE,
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
        policy_record = self.get_policy(session)
        result = self.engine.answer(
            query.strip(),
            mode,
            owned_ids,
            stored_history or history,
            behavior,
            difficulty,
            TutorPolicy(
                allow_direct_answers=policy_record.allow_direct_answers,
                allow_code_solutions=policy_record.allow_code_solutions,
                hints_only=policy_record.hints_only,
            ),
        )
        mode_name = (
            "rubber_duck" if mode is AssistantMode.RUBBER_DUCK else "programming_tutor"
        )
        if conversation is None:
            conversation = ConversationRecord(
                owner_id=owner_id,
                title=self._title(query),
                mode=mode_name,
                behavior=behavior.value,
                difficulty=difficulty.value,
                document_ids=sorted(owned_ids),
            )
            session.add(conversation)
            session.flush()
        else:
            conversation = self.get_conversation(
                session, owner_id, conversation.id, lock=True
            )
            conversation.mode = mode_name
            conversation.behavior = behavior.value
            conversation.difficulty = difficulty.value
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

    def regenerate(
        self, session: Session, owner_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> tuple[TutorResponse, ConversationRecord]:
        conversation = self.get_conversation(
            session, owner_id, conversation_id, lock=True
        )
        messages = self.conversation_messages(session, conversation.id)
        if (
            len(messages) < 2
            or messages[-2].role != "user"
            or messages[-1].role != "assistant"
        ):
            raise ValueError("The conversation has no answer to regenerate")
        owned_ids = set(
            session.scalars(
                select(DocumentRecord.id).where(
                    DocumentRecord.owner_id == owner_id,
                    DocumentRecord.id.in_(conversation.document_ids),
                )
            ).all()
        )
        if owned_ids != set(conversation.document_ids):
            raise OwnedResourceNotFoundError(
                "One or more conversation documents are no longer available"
            )
        policy_record = self.get_policy(session)
        result = self.engine.answer(
            messages[-2].content,
            (
                AssistantMode.RUBBER_DUCK
                if conversation.mode == "rubber_duck"
                else AssistantMode.PROGRAMMING_TUTOR
            ),
            owned_ids,
            [
                ChatMessage(role=item.role, content=item.content)
                for item in messages[:-2]
            ],
            TeachingBehavior(conversation.behavior),
            TutorDifficulty(conversation.difficulty),
            TutorPolicy(
                allow_direct_answers=policy_record.allow_direct_answers,
                allow_code_solutions=policy_record.allow_code_solutions,
                hints_only=policy_record.hints_only,
            ),
        )
        assistant = messages[-1]
        assistant.content = result.answer
        assistant.grounded = result.grounded
        assistant.citations = [asdict(citation) for citation in result.citations]
        conversation.updated_at = datetime.now(UTC)
        session.commit()
        session.refresh(conversation)
        return result, conversation

    @staticmethod
    def get_policy(session: Session) -> TutorPolicyRecord:
        policy = session.get(TutorPolicyRecord, 1)
        if policy is None:
            policy = TutorPolicyRecord(id=1)
            session.add(policy)
            session.flush()
        return policy

    @staticmethod
    def update_policy(
        session: Session,
        instructor_id: uuid.UUID,
        *,
        allow_direct_answers: bool,
        allow_code_solutions: bool,
        hints_only: bool,
    ) -> TutorPolicyRecord:
        policy = TutoringService.get_policy(session)
        policy.allow_direct_answers = allow_direct_answers
        policy.allow_code_solutions = allow_code_solutions
        policy.hints_only = hints_only
        policy.updated_by = instructor_id
        policy.updated_at = datetime.now(UTC)
        session.commit()
        session.refresh(policy)
        return policy

    @staticmethod
    def list_conversations(
        session: Session, owner_id: uuid.UUID
    ) -> list[ConversationRecord]:
        return list(
            session.scalars(
                select(ConversationRecord)
                .where(ConversationRecord.owner_id == owner_id)
                .order_by(
                    ConversationRecord.pinned.desc(),
                    ConversationRecord.updated_at.desc(),
                )
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

    def update_conversation(
        self,
        session: Session,
        owner_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        title: str | None,
        pinned: bool | None,
    ) -> ConversationRecord:
        conversation = self.get_conversation(session, owner_id, conversation_id)
        if title is not None:
            normalized_title = " ".join(title.split())
            if not normalized_title:
                raise ValueError("Conversation title cannot be empty")
            conversation.title = normalized_title
        if pinned is not None:
            conversation.pinned = pinned
        conversation.updated_at = datetime.now(UTC)
        session.commit()
        session.refresh(conversation)
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

    def list_notes(
        self, session: Session, owner_id: uuid.UUID
    ) -> list[StudentNoteRecord]:
        return list(
            session.scalars(
                select(StudentNoteRecord)
                .where(StudentNoteRecord.owner_id == owner_id)
                .order_by(StudentNoteRecord.updated_at.desc())
                .limit(200)
            ).all()
        )

    def create_note(
        self,
        session: Session,
        owner_id: uuid.UUID,
        *,
        kind: str,
        title: str,
        content: str,
        conversation_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
        citations: list[dict[str, object]],
    ) -> StudentNoteRecord:
        if conversation_id is not None:
            self.get_conversation(session, owner_id, conversation_id)
        if message_id is not None:
            owned_message = session.scalar(
                select(ConversationMessageRecord.id)
                .join(
                    ConversationRecord,
                    ConversationRecord.id == ConversationMessageRecord.conversation_id,
                )
                .where(
                    ConversationMessageRecord.id == message_id,
                    ConversationRecord.owner_id == owner_id,
                )
            )
            if owned_message is None:
                raise OwnedResourceNotFoundError("Message not found")
        normalized_title = " ".join(title.split())
        normalized_content = content.strip()
        if not normalized_title or not normalized_content:
            raise ValueError("Note title and content cannot be empty")
        note = StudentNoteRecord(
            owner_id=owner_id,
            kind=kind,
            title=normalized_title,
            content=normalized_content,
            conversation_id=conversation_id,
            message_id=message_id,
            citations=citations,
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        return note

    def delete_note(
        self, session: Session, owner_id: uuid.UUID, note_id: uuid.UUID
    ) -> None:
        note = session.scalar(
            select(StudentNoteRecord).where(
                StudentNoteRecord.id == note_id,
                StudentNoteRecord.owner_id == owner_id,
            )
        )
        if note is None:
            raise OwnedResourceNotFoundError("Note not found")
        session.delete(note)
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
