"""Grounded tutoring and progressive hint orchestration."""

from __future__ import annotations

import re

from langchain_core.prompts import PromptTemplate

from .hints import HintWorkflow
from .models import (
    AssistantMode,
    ChatMessage,
    Citation,
    HintProgress,
    TeachingBehavior,
    TutorDifficulty,
    TutorPolicy,
    TutorResponse,
)
from .providers import ChatProvider
from .retrieval import VectorIndex
from .routing import RequestRoute, RequestRouter

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_STOP_WORDS = {
    "and",
    "are",
    "but",
    "can",
    "for",
    "from",
    "how",
    "that",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "you",
    "your",
}
_CHARS_PER_TOKEN = 4
_ANSWER_PROMPT = PromptTemplate.from_template(
    "History:\n{history}\n\nCourse context:\n{context}\n\n"
    "Question:\n{question}\n\nUse bracketed source numbers. "
    "If evidence is insufficient, say so."
)


def relevant_conversation(
    history: list[ChatMessage],
    focus: str,
    *,
    recent: int = 4,
    max_messages: int = 6,
    max_chars: int = 3000,
) -> str:
    """Keep recent turns plus older turns that overlap the current problem."""
    focus_tokens = {
        token.lower()
        for token in _TOKEN.findall(focus)
        if token.lower() not in _STOP_WORDS
    }
    recent_start = max(0, len(history) - recent)
    selected: list[tuple[int, ChatMessage]] = []
    for index, message in enumerate(history):
        tokens = {token.lower() for token in _TOKEN.findall(message.content)}
        if index >= recent_start or focus_tokens.intersection(tokens):
            selected.append((index, message))
    rendered: list[str] = []
    used = 0
    for _, message in reversed(selected):
        if len(rendered) >= max_messages:
            break
        line = f"{message.role}: {message.content.strip()}"
        if not line.strip() or used + len(line) > max_chars:
            continue
        rendered.append(line)
        used += len(line)
    return "\n".join(reversed(rendered))


class TutorService:
    def __init__(
        self,
        chat: ChatProvider,
        index: VectorIndex,
        retrieval_limit: int = 3,
        retrieval_min_score: float = 0.25,
        retrieval_context_tokens: int = 2_500,
        conversation_context_tokens: int = 750,
    ) -> None:
        self._chat = chat
        self._index = index
        self._retrieval_limit = retrieval_limit
        self._retrieval_min_score = retrieval_min_score
        self._retrieval_context_tokens = retrieval_context_tokens
        self._conversation_context_tokens = conversation_context_tokens
        self._hints = HintWorkflow(chat)
        self._router = RequestRouter()

    def answer(
        self,
        query: str,
        mode: AssistantMode,
        document_ids: set[str],
        history: list[ChatMessage] | None = None,
        behavior: TeachingBehavior | None = None,
        difficulty: TutorDifficulty = TutorDifficulty.INTERMEDIATE,
        policy: TutorPolicy | None = None,
    ) -> TutorResponse:
        results = [
            result
            for result in self._index.search(query, document_ids, self._retrieval_limit)
            if result.score >= self._retrieval_min_score
        ]
        if not results:
            return TutorResponse(
                answer=(
                    "I couldn’t find enough supporting evidence in the selected course "
                    "materials to answer that reliably. Try rephrasing the question or "
                    "selecting a document that covers the topic."
                ),
                grounded=False,
            )

        route = self._router.route(query)
        context_parts: list[str] = []
        citations: list[Citation] = []
        remaining_chars = self._retrieval_context_tokens * _CHARS_PER_TOKEN
        for number, result in enumerate(results, start=1):
            source = str(result.chunk.metadata.get("source", "Unknown source"))
            location = result.chunk.metadata.get("location")
            label = f"[{number}] {source}"
            if location:
                label += f", {location}"
            label += f" (chunk {result.chunk.id})"
            available = remaining_chars - len(label) - 1
            if available <= 0:
                break
            excerpt = result.chunk.text[:available].strip()
            if not excerpt:
                continue
            context_parts.append(f"{label}\n{excerpt}")
            remaining_chars -= len(label) + len(excerpt) + 1
            citations.append(
                Citation(
                    document_id=result.chunk.document_id,
                    source_name=source,
                    excerpt=excerpt[:240],
                    location=str(location) if location else None,
                    chunk_id=result.chunk.id,
                    score=result.score,
                    source_uri=(
                        str(result.chunk.metadata["origin_uri"])
                        if result.chunk.metadata.get("origin_uri")
                        else None
                    ),
                )
            )
        history_text = relevant_conversation(
            history or [],
            query,
            max_chars=self._conversation_context_tokens * _CHARS_PER_TOKEN,
        )
        context_text = "\n\n".join(context_parts)
        user_prompt = _ANSWER_PROMPT.format(
            history=history_text or "None",
            context=context_text,
            question=query,
        )
        selected_behavior = behavior or (
            TeachingBehavior.SOCRATIC
            if mode is AssistantMode.RUBBER_DUCK
            else TeachingBehavior.EXPLAIN
        )
        return TutorResponse(
            answer=self._chat.complete(
                self._system_prompt(
                    selected_behavior, difficulty, policy or TutorPolicy(), route
                ),
                user_prompt,
            ),
            citations=tuple(citations),
        )

    def next_hint(
        self,
        problem: str,
        history: list[ChatMessage],
        previous_hints: list[str],
    ) -> HintProgress:
        conversation = relevant_conversation(
            history,
            problem,
            max_chars=self._conversation_context_tokens * _CHARS_PER_TOKEN,
        )
        return self._hints.next_hint(problem, history, previous_hints, conversation)

    @staticmethod
    def _system_prompt(
        behavior: TeachingBehavior,
        difficulty: TutorDifficulty,
        policy: TutorPolicy,
        route: RequestRoute,
    ) -> str:
        behavior_instructions = {
            TeachingBehavior.SOCRATIC: (
                "Use Socratic teaching: ask one focused guiding question at a time and "
                "help the student reason toward the answer. Do not reveal the final solution."
            ),
            TeachingBehavior.EXPLAIN: (
                "When instructor policy permits, give a clear direct explanation, then "
                "include one brief check-for-understanding."
            ),
            TeachingBehavior.EXAM_PREP: (
                "Act as an examiner. Ask one question at a time, wait for the student's "
                "attempt, and do not reveal the answer in the same response."
            ),
            TeachingBehavior.DEBUG_COACH: (
                "Act as a debugging coach. Identify the likely error area and suggest one "
                "diagnostic step, but let the student repair the code."
            ),
        }
        difficulty_instructions = {
            TutorDifficulty.BEGINNER: (
                "Use simple language, define technical terms, and keep steps small."
            ),
            TutorDifficulty.INTERMEDIATE: (
                "Assume basic programming knowledge and explain the important reasoning."
            ),
            TutorDifficulty.ADVANCED: (
                "Use precise technical language, discuss trade-offs, and challenge assumptions."
            ),
        }
        restrictions: list[str] = []
        if policy.hints_only:
            restrictions.append(
                "Instructor policy requires hints only: never provide a direct answer or a complete solution."
            )
        elif not policy.allow_direct_answers:
            restrictions.append(
                "Instructor policy forbids direct answers: respond with guidance or questions only."
            )
        if not policy.allow_code_solutions:
            restrictions.append(
                "Instructor policy forbids complete code solutions: use pseudocode or a minimal fragment only."
            )
        route_instruction = (
            "The request concerns debugging; never execute code and preserve the student's ownership of the fix."
            if route is RequestRoute.DEBUG
            else "Keep the response focused on the student's question."
        )
        return " ".join(
            [
                "You are a learning-aware programming tutor. Use only supplied course context and cite [n] for claims.",
                "Instructor policy is mandatory and overrides the selected teaching behavior.",
                behavior_instructions[behavior],
                difficulty_instructions[difficulty],
                route_instruction,
                *restrictions,
            ]
        )
