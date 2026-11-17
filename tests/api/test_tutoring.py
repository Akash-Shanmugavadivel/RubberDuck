from __future__ import annotations

import uuid
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pydebugger.models import (
    AssistantMode,
    ChatMessage,
    Citation,
    HintProgress,
    TutorResponse,
)
from pydebugger_api.config import APISettings
from pydebugger_api.main import create_app
from pydebugger_api.models import (
    ConversationMessageRecord,
    ConversationRecord,
    DocumentRecord,
    TutorPolicyRecord,
    User,
)
from pydebugger_api.services.documents import DocumentService


class TestDatabase:
    __test__ = False

    def __init__(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        User.__table__.create(self.engine)
        DocumentRecord.__table__.create(self.engine)
        ConversationRecord.__table__.create(self.engine)
        ConversationMessageRecord.__table__.create(self.engine)
        TutorPolicyRecord.__table__.create(self.engine)

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session

    def readiness(self) -> tuple[bool, str]:
        return True, "Test database is ready"

    def dispose(self) -> None:
        self.engine.dispose()


class FakeTutorEngine:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(upload_limit_bytes=1_024)
        self.answer_calls: list[tuple] = []
        self.hint_calls: list[tuple] = []

    def answer(
        self,
        query: str,
        mode: AssistantMode,
        document_ids: set[str],
        history: list[ChatMessage] | None = None,
        behavior=None,
        difficulty=None,
        policy=None,
    ) -> TutorResponse:
        self.answer_calls.append(
            (query, mode, document_ids, history, behavior, difficulty, policy)
        )
        return TutorResponse(
            answer="A loop repeats a block of code.",
            grounded=True,
            citations=(
                Citation(
                    document_id=next(iter(document_ids)),
                    source_name="loops.txt",
                    excerpt="A loop repeats work.",
                    location="line 1",
                    chunk_id="chunk-1",
                    score=0.92,
                ),
            ),
        )

    def next_hint(
        self,
        problem: str,
        history: list[ChatMessage] | None = None,
        previous_hints: list[str] | None = None,
    ) -> HintProgress:
        self.hint_calls.append((problem, history, previous_hints))
        hints = (*(previous_hints or []), "Check the loop condition.")
        return HintProgress(
            problem=problem,
            level=len(hints),
            hint=hints[-1],
            hints=hints,
        )

    def list_documents(self):
        return ()


def settings(instructor_emails: str = "") -> APISettings:
    return APISettings(
        PYDEBUGGER_DATABASE_URL=(
            "postgresql+psycopg://pydebugger:pydebugger@localhost/pydebugger"
        ),
        PYDEBUGGER_JWT_SECRET_KEY="test-secret-that-is-longer-than-thirty-two-characters",
        PYDEBUGGER_INSTRUCTOR_EMAILS=instructor_emails,
    )


def register(client: TestClient, email: str) -> tuple[str, uuid.UUID]:
    password = "safe-password-123"
    registered = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    return login.json()["access_token"], uuid.UUID(registered.json()["id"])


def add_document(database: TestDatabase, owner_id: uuid.UUID, document_id: str) -> None:
    with database.session_factory() as session:
        session.add(
            DocumentRecord(
                id=document_id,
                owner_id=owner_id,
                name="loops.txt",
                media_type="text/plain",
                sha256="a" * 64,
                index_version="index-v1",
                source_type="upload",
                origin_uri=None,
                storage_path=str(Path("uploads") / document_id / "loops.txt"),
                document_metadata={"stored_filename": "loops.txt"},
            )
        )
        session.commit()


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_answer_uses_owned_documents_and_conversation_history() -> None:
    database = TestDatabase()
    engine = FakeTutorEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, owner_id = register(client, "student@example.com")
        add_document(database, owner_id, "doc-loops")
        response = client.post(
            "/api/v1/tutor/answer",
            headers=authorization(token),
            json={
                "query": "Explain loops",
                "mode": "rubber_duck",
                "document_ids": ["doc-loops"],
                "history": [{"role": "user", "content": "What repeats?"}],
            },
        )

    assert response.status_code == 200
    assert response.json()["conversation_id"]
    assert response.json()["grounded"] is True
    assert response.json()["citations"][0]["document_id"] == "doc-loops"
    query, mode, document_ids, history, behavior, difficulty, policy = (
        engine.answer_calls[0]
    )
    assert query == "Explain loops"
    assert mode is AssistantMode.RUBBER_DUCK
    assert document_ids == {"doc-loops"}
    assert history == [ChatMessage(role="user", content="What repeats?")]
    assert behavior.value == "explain"
    assert difficulty.value == "intermediate"
    assert policy.allow_direct_answers is True


def test_conversation_history_is_persisted_reused_and_deletable() -> None:
    database = TestDatabase()
    engine = FakeTutorEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, owner_id = register(client, "history@example.com")
        add_document(database, owner_id, "doc-loops")
        headers = authorization(token)
        first = client.post(
            "/api/v1/tutor/answer",
            headers=headers,
            json={"query": "Explain loops", "document_ids": ["doc-loops"]},
        )
        conversation_id = first.json()["conversation_id"]
        second = client.post(
            "/api/v1/tutor/answer",
            headers=headers,
            json={
                "query": "Give me an example",
                "document_ids": ["doc-loops"],
                "conversation_id": conversation_id,
                "history": [{"role": "user", "content": "Ignore this client copy"}],
            },
        )
        listing = client.get("/api/v1/tutor/conversations", headers=headers)
        detail = client.get(
            f"/api/v1/tutor/conversations/{conversation_id}", headers=headers
        )
        deleted = client.delete(
            f"/api/v1/tutor/conversations/{conversation_id}", headers=headers
        )
        missing = client.get(
            f"/api/v1/tutor/conversations/{conversation_id}", headers=headers
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert listing.status_code == 200
    assert listing.json()[0]["title"] == "Explain loops"
    assert detail.status_code == 200
    assert [item["role"] for item in detail.json()["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert detail.json()["messages"][1]["citations"][0]["chunk_id"] == "chunk-1"
    assert engine.answer_calls[1][3] == [
        ChatMessage(role="user", content="Explain loops"),
        ChatMessage(role="assistant", content="A loop repeats a block of code."),
    ]
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_conversation_history_is_owner_scoped() -> None:
    database = TestDatabase()
    engine = FakeTutorEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        first_token, first_id = register(client, "owner@example.com")
        second_token, second_id = register(client, "other@example.com")
        add_document(database, first_id, "first-doc")
        add_document(database, second_id, "second-doc")
        created = client.post(
            "/api/v1/tutor/answer",
            headers=authorization(first_token),
            json={"query": "Private question", "document_ids": ["first-doc"]},
        )
        conversation_id = created.json()["conversation_id"]
        detail = client.get(
            f"/api/v1/tutor/conversations/{conversation_id}",
            headers=authorization(second_token),
        )
        continued = client.post(
            "/api/v1/tutor/answer",
            headers=authorization(second_token),
            json={
                "query": "Read it",
                "document_ids": ["second-doc"],
                "conversation_id": conversation_id,
            },
        )

    assert detail.status_code == 404
    assert continued.status_code == 404


def test_learning_behavior_difficulty_and_instructor_policy_reach_engine() -> None:
    database = TestDatabase()
    engine = FakeTutorEngine()
    app = create_app(settings("teacher@example.com"), database, DocumentService(engine))

    with TestClient(app) as client:
        teacher_token, _ = register(client, "teacher@example.com")
        student_token, student_id = register(client, "student@example.com")
        teacher_profile = client.get(
            "/api/v1/auth/me", headers=authorization(teacher_token)
        )
        add_document(database, student_id, "doc-loops")
        forbidden = client.put(
            "/api/v1/tutor/policy",
            headers=authorization(student_token),
            json={
                "allow_direct_answers": False,
                "allow_code_solutions": False,
                "hints_only": True,
            },
        )
        updated = client.put(
            "/api/v1/tutor/policy",
            headers=authorization(teacher_token),
            json={
                "allow_direct_answers": False,
                "allow_code_solutions": False,
                "hints_only": True,
            },
        )
        answer = client.post(
            "/api/v1/tutor/answer",
            headers=authorization(student_token),
            json={
                "query": "Fix my loop",
                "document_ids": ["doc-loops"],
                "behavior": "debug_coach",
                "difficulty": "advanced",
            },
        )

    assert forbidden.status_code == 403
    assert teacher_profile.json()["role"] == "instructor"
    assert updated.status_code == 200
    assert updated.json()["hints_only"] is True
    assert answer.status_code == 200
    assert engine.answer_calls[-1][4].value == "debug_coach"
    assert engine.answer_calls[-1][5].value == "advanced"
    assert engine.answer_calls[-1][6].hints_only is True


def test_answer_rejects_another_users_document_before_model_call() -> None:
    database = TestDatabase()
    engine = FakeTutorEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        first_token, _ = register(client, "first@example.com")
        _, second_id = register(client, "second@example.com")
        add_document(database, second_id, "private-document")
        response = client.post(
            "/api/v1/tutor/answer",
            headers=authorization(first_token),
            json={
                "query": "Reveal the other document",
                "document_ids": ["private-document"],
            },
        )

    assert response.status_code == 404
    assert engine.answer_calls == []


def test_hint_preserves_progression_and_requires_authentication() -> None:
    database = TestDatabase()
    engine = FakeTutorEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, _ = register(client, "student@example.com")
        response = client.post(
            "/api/v1/tutor/hint",
            headers=authorization(token),
            json={
                "problem": "My loop never stops",
                "history": [{"role": "assistant", "content": "Inspect the condition"}],
                "previous_hints": ["Print the counter."],
            },
        )
        unauthorized = client.post(
            "/api/v1/tutor/hint", json={"problem": "My loop never stops"}
        )

    assert response.status_code == 200
    assert response.json()["level"] == 2
    assert response.json()["hints"] == [
        "Print the counter.",
        "Check the loop condition.",
    ]
    assert unauthorized.status_code == 401


def test_tutor_request_validation_rejects_empty_document_selection() -> None:
    database = TestDatabase()
    engine = FakeTutorEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, _ = register(client, "student@example.com")
        response = client.post(
            "/api/v1/tutor/answer",
            headers=authorization(token),
            json={"query": "Explain loops", "document_ids": []},
        )

    assert response.status_code == 422
    assert engine.answer_calls == []
