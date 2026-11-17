"""Grounded tutoring and progressive-hint API contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from pydebugger.models import (
    AssistantMode,
    ChatMessage,
    Citation,
    HintProgress,
    TutorResponse,
)


class TutorMode(str, Enum):
    PROGRAMMING_TUTOR = "programming_tutor"
    RUBBER_DUCK = "rubber_duck"

    def to_engine(self) -> AssistantMode:
        if self is TutorMode.RUBBER_DUCK:
            return AssistantMode.RUBBER_DUCK
        return AssistantMode.PROGRAMMING_TUTOR


class ChatMessageRequest(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8_000)

    def to_engine(self) -> ChatMessage:
        return ChatMessage(role=self.role, content=self.content.strip())


class TutorAnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8_000)
    mode: TutorMode = TutorMode.PROGRAMMING_TUTOR
    document_ids: list[str] = Field(min_length=1, max_length=20)
    history: list[ChatMessageRequest] = Field(default_factory=list, max_length=50)


class CitationResponse(BaseModel):
    document_id: str
    source_name: str
    excerpt: str
    location: str | None = None
    chunk_id: str | None = None
    score: float | None = None
    source_uri: str | None = None

    @classmethod
    def from_citation(cls, citation: Citation) -> CitationResponse:
        return cls(**citation.__dict__)


class TutorAnswerResponse(BaseModel):
    answer: str
    grounded: bool
    citations: list[CitationResponse]

    @classmethod
    def from_result(cls, result: TutorResponse) -> TutorAnswerResponse:
        return cls(
            answer=result.answer,
            grounded=result.grounded,
            citations=[
                CitationResponse.from_citation(item) for item in result.citations
            ],
        )


class HintRequest(BaseModel):
    problem: str = Field(min_length=1, max_length=8_000)
    history: list[ChatMessageRequest] = Field(default_factory=list, max_length=50)
    previous_hints: list[str] = Field(default_factory=list, max_length=10)


class HintResponse(BaseModel):
    problem: str
    level: int
    hint: str
    hints: list[str]

    @classmethod
    def from_result(cls, result: HintProgress) -> HintResponse:
        return cls(
            problem=result.problem,
            level=result.level,
            hint=result.hint,
            hints=list(result.hints),
        )
