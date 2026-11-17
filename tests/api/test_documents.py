from __future__ import annotations

import uuid
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pydebugger.engine import PyDebuggerEngine
from pydebugger.models import DocumentSource, IngestionJob, JobState
from pydebugger_api.config import APISettings
from pydebugger_api.main import create_app
from pydebugger_api.models import DocumentRecord, IngestionJobRecord, User
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
        IngestionJobRecord.__table__.create(self.engine)

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session

    def readiness(self) -> tuple[bool, str]:
        return True, "Test database is ready"

    def dispose(self) -> None:
        self.engine.dispose()


class FakeDocumentEngine:
    def __init__(self, upload_limit: int = 1_024) -> None:
        self.settings = SimpleNamespace(upload_limit_bytes=upload_limit)
        self.jobs: dict[str, IngestionJob] = {}
        self.documents: dict[str, DocumentSource] = {}
        self.uploads: list[tuple[str, bytes, str | None, str]] = []
        self.youtube: list[tuple[str, tuple[str, ...], str]] = []
        self.cancelled: list[str] = []

    def _completed_job(self, source: DocumentSource) -> IngestionJob:
        job_id = f"job-{len(self.jobs) + 1}"
        job = IngestionJob(
            id=job_id,
            state=JobState.COMPLETED,
            result=source,
            progress=1.0,
            message="Document indexed",
            attempt=1,
            max_attempts=3,
        )
        self.jobs[job_id] = job
        self.documents[source.id] = source
        return job

    def start_document_ingestion(
        self,
        filename: str,
        data: bytes,
        media_type: str | None,
        owner_id: str | None = None,
    ) -> IngestionJob:
        assert owner_id is not None
        self.uploads.append((filename, data, media_type, owner_id))
        document_id = PyDebuggerEngine._stable_id(
            "upload",
            PyDebuggerEngine._scoped_source_key(
                "upload", filename.casefold(), owner_id
            ),
        )
        return self._completed_job(
            DocumentSource(
                id=document_id,
                name=filename,
                path=Path("uploads") / document_id / filename,
                media_type=media_type or "application/octet-stream",
                sha256="a" * 64,
                index_version="index-v1",
                metadata={"owner_id": owner_id, "stored_filename": filename},
            )
        )

    def start_youtube_ingestion(
        self,
        reference: str,
        languages: tuple[str, ...],
        owner_id: str | None = None,
    ) -> IngestionJob:
        assert owner_id is not None
        self.youtube.append((reference, languages, owner_id))
        video_id = reference.rsplit("/", maxsplit=1)[-1]
        document_id = PyDebuggerEngine._stable_id(
            "youtube",
            PyDebuggerEngine._scoped_source_key("youtube", video_id, owner_id),
        )
        return self._completed_job(
            DocumentSource(
                id=document_id,
                name=f"YouTube {video_id}",
                path=Path("uploads") / document_id / "transcript.txt",
                media_type="text/vnd.youtube-transcript",
                sha256="b" * 64,
                index_version="index-v1",
                source_type="youtube",
                origin_uri=reference,
                metadata={"owner_id": owner_id, "stored_filename": "transcript.txt"},
            )
        )

    def get_ingestion(self, job_id: str) -> IngestionJob:
        if job_id not in self.jobs:
            raise KeyError(job_id)
        return self.jobs[job_id]

    def cancel_ingestion(self, job_id: str) -> bool:
        self.cancelled.append(job_id)
        return job_id in self.jobs

    def list_documents(self) -> tuple[DocumentSource, ...]:
        return tuple(self.documents.values())

    def remove_document(self, document_id: str) -> bool:
        return self.documents.pop(document_id, None) is not None


def settings() -> APISettings:
    return APISettings(
        PYDEBUGGER_DATABASE_URL=(
            "postgresql+psycopg://pydebugger:pydebugger@localhost/pydebugger"
        ),
        PYDEBUGGER_JWT_SECRET_KEY="test-secret-that-is-longer-than-thirty-two-characters",
    )


def register(client: TestClient, email: str) -> str:
    password = "safe-password-123"
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return login.json()["access_token"]


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_upload_job_list_and_delete_are_owner_scoped() -> None:
    database = TestDatabase()
    engine = FakeDocumentEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        first_token = register(client, "first@example.com")
        second_token = register(client, "second@example.com")
        upload = client.post(
            "/api/v1/documents/upload",
            files={"file": ("lesson.txt", b"Python loops", "text/plain")},
            headers=authorization(first_token),
        )
        job_id = upload.json()["id"]
        forbidden_job = client.get(
            f"/api/v1/ingestion-jobs/{job_id}",
            headers=authorization(second_token),
        )
        completed = client.get(
            f"/api/v1/ingestion-jobs/{job_id}",
            headers=authorization(first_token),
        )
        document_id = completed.json()["result"]["id"]
        first_documents = client.get(
            "/api/v1/documents", headers=authorization(first_token)
        )
        second_documents = client.get(
            "/api/v1/documents", headers=authorization(second_token)
        )
        forbidden_delete = client.delete(
            f"/api/v1/documents/{document_id}",
            headers=authorization(second_token),
        )
        deleted = client.delete(
            f"/api/v1/documents/{document_id}",
            headers=authorization(first_token),
        )

    assert upload.status_code == 202
    assert forbidden_job.status_code == 404
    assert completed.status_code == 200
    assert "owner_id" not in completed.json()["result"]["metadata"]
    assert len(first_documents.json()) == 1
    assert second_documents.json() == []
    assert forbidden_delete.status_code == 404
    assert deleted.status_code == 204
    assert engine.uploads[0][0:3] == ("lesson.txt", b"Python loops", "text/plain")


def test_same_filename_produces_different_ids_for_different_users() -> None:
    first = PyDebuggerEngine._stable_id(
        "upload",
        PyDebuggerEngine._scoped_source_key("upload", "lesson.txt", str(uuid.uuid4())),
    )
    second = PyDebuggerEngine._stable_id(
        "upload",
        PyDebuggerEngine._scoped_source_key("upload", "lesson.txt", str(uuid.uuid4())),
    )

    assert first != second


def test_youtube_job_is_scoped_to_authenticated_user() -> None:
    database = TestDatabase()
    engine = FakeDocumentEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token = register(client, "student@example.com")
        response = client.post(
            "/api/v1/documents/youtube",
            json={"reference": "https://youtu.be/video123", "languages": ["en", "ta"]},
            headers=authorization(token),
        )

    assert response.status_code == 202
    assert engine.youtube[0][0:2] == (
        "https://youtu.be/video123",
        ("en", "ta"),
    )


def test_upload_size_is_bounded_before_engine_submission() -> None:
    database = TestDatabase()
    engine = FakeDocumentEngine(upload_limit=5)
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token = register(client, "student@example.com")
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("lesson.txt", b"too large", "text/plain")},
            headers=authorization(token),
        )

    assert response.status_code == 413
    assert engine.uploads == []
