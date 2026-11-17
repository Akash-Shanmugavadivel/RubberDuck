from __future__ import annotations

import uuid
from collections.abc import Generator
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pydebugger.models import (
    ExecutionJob,
    ExecutionResult,
    ExecutionState,
    ExecutionTestCase,
    ExecutionTestResult,
    PythonDiagnostic,
    TracebackFrame,
)
from pydebugger_api.config import APISettings
from pydebugger_api.main import create_app
from pydebugger_api.models import ExecutionJobRecord, User
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
        ExecutionJobRecord.__table__.create(self.engine)

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session

    def readiness(self) -> tuple[bool, str]:
        return True, "Test database is ready"

    def dispose(self) -> None:
        self.engine.dispose()


class FakeExecutionEngine:
    def __init__(self, source_limit: int = 100_000) -> None:
        self.settings = SimpleNamespace(
            execution_source_limit=source_limit,
            upload_limit_bytes=1_024,
        )
        self.jobs: dict[str, ExecutionJob] = {}
        self.single_calls: list[str] = []
        self.project_calls: list[tuple] = []
        self.cancel_calls: list[str] = []

    def _job(self, result: ExecutionResult) -> ExecutionJob:
        job_id = f"execution-{len(self.jobs) + 1}"
        result = replace(result, execution_id=job_id)
        job = ExecutionJob(
            id=job_id,
            state=ExecutionState.COMPLETED,
            result=result,
            progress=1.0,
            message="Execution completed",
            attempt=1,
            max_attempts=2,
        )
        self.jobs[job_id] = job
        return job

    def start_execution(self, source: str) -> ExecutionJob:
        self.single_calls.append(source)
        diagnostic = PythonDiagnostic(
            exception_type="ValueError",
            message="bad value",
            file_name="submission.py",
            line_number=2,
            source_line="raise ValueError('bad value')",
            frames=(
                TracebackFrame(
                    file_name="submission.py",
                    line_number=2,
                    function_name="<module>",
                    source_line="raise ValueError('bad value')",
                ),
            ),
        )
        return self._job(
            ExecutionResult(
                stderr="ValueError: bad value",
                exit_code=1,
                duration_seconds=0.01,
                diagnostic=diagnostic,
                traceback='File "submission.py", line 2',
            )
        )

    def start_project_execution(
        self,
        files: dict[str, str],
        entrypoint: str,
        tests: list[ExecutionTestCase] | None = None,
    ) -> ExecutionJob:
        self.project_calls.append((files, entrypoint, tests))
        test = (tests or [ExecutionTestCase("default")])[0]
        return self._job(
            ExecutionResult(
                stdout="5\n",
                exit_code=0,
                duration_seconds=0.02,
                test_results=(
                    ExecutionTestResult(
                        name=test.name,
                        passed=True,
                        expected_output=test.expected_output,
                        actual_output="5\n",
                        exit_code=0,
                        duration_seconds=0.01,
                    ),
                ),
            )
        )

    def get_execution(self, execution_id: str) -> ExecutionJob:
        if execution_id not in self.jobs:
            raise KeyError(execution_id)
        return self.jobs[execution_id]

    def cancel_execution(self, execution_id: str) -> bool:
        self.cancel_calls.append(execution_id)
        job = self.jobs.get(execution_id)
        if job is None:
            return False
        self.jobs[execution_id] = replace(
            job,
            state=ExecutionState.CANCELLED,
            result=ExecutionResult(execution_id=execution_id, cancelled=True),
            message="Execution cancelled",
        )
        return True


def settings() -> APISettings:
    return APISettings(
        PYDEBUGGER_DATABASE_URL=(
            "postgresql+psycopg://pydebugger:pydebugger@localhost/pydebugger"
        ),
        PYDEBUGGER_JWT_SECRET_KEY="test-secret-that-is-longer-than-thirty-two-characters",
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


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_single_file_execution_returns_diagnostics_and_is_owner_scoped() -> None:
    database = TestDatabase()
    engine = FakeExecutionEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        first_token, _ = register(client, "first@example.com")
        second_token, _ = register(client, "second@example.com")
        submitted = client.post(
            "/api/v1/executions/single-file",
            json={"source": "print('hello')"},
            headers=authorization(first_token),
        )
        execution_id = submitted.json()["id"]
        forbidden = client.get(
            f"/api/v1/executions/{execution_id}",
            headers=authorization(second_token),
        )
        result = client.get(
            f"/api/v1/executions/{execution_id}",
            headers=authorization(first_token),
        )

    assert submitted.status_code == 202
    assert forbidden.status_code == 404
    assert result.status_code == 200
    diagnostic = result.json()["result"]["diagnostic"]
    assert diagnostic["exception_type"] == "ValueError"
    assert diagnostic["line_number"] == 2
    assert diagnostic["frames"][0]["file_name"] == "submission.py"


def test_project_execution_returns_structured_test_results() -> None:
    database = TestDatabase()
    engine = FakeExecutionEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, _ = register(client, "student@example.com")
        response = client.post(
            "/api/v1/executions/project",
            headers=authorization(token),
            json={
                "files": {
                    "main.py": "from utils import add\nprint(add(2, 3))",
                    "utils.py": "def add(a, b): return a + b",
                },
                "entrypoint": "main.py",
                "tests": [{"name": "addition", "expected_output": "5\n"}],
            },
        )

    assert response.status_code == 202
    test_result = response.json()["result"]["test_results"][0]
    assert test_result["name"] == "addition"
    assert test_result["passed"] is True
    assert test_result["expected_output"] == "5\n"
    assert engine.project_calls[0][1] == "main.py"


def test_unsafe_project_path_is_rejected_before_engine_submission() -> None:
    database = TestDatabase()
    engine = FakeExecutionEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, _ = register(client, "student@example.com")
        response = client.post(
            "/api/v1/executions/project",
            headers=authorization(token),
            json={
                "files": {"../escape.py": "print('unsafe')"},
                "entrypoint": "../escape.py",
            },
        )

    assert response.status_code == 400
    assert "Unsafe Python project path" in response.json()["detail"]
    assert engine.project_calls == []


@pytest.mark.parametrize(
    "files,entrypoint",
    [
        ({"main.py": "print('a')", "MAIN.py": "print('b')"}, "main.py"),
        ({"CON.py": "print('unsafe')"}, "CON.py"),
        ({"módulo.py": "print('unsafe')"}, "módulo.py"),
    ],
)
def test_platform_unsafe_project_names_are_rejected(
    files: dict[str, str], entrypoint: str
) -> None:
    database = TestDatabase()
    engine = FakeExecutionEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, _ = register(client, "student@example.com")
        response = client.post(
            "/api/v1/executions/project",
            headers=authorization(token),
            json={"files": files, "entrypoint": entrypoint},
        )

    assert response.status_code == 400
    assert engine.project_calls == []


def test_source_limit_is_enforced_before_engine_submission() -> None:
    database = TestDatabase()
    engine = FakeExecutionEngine(source_limit=5)
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, _ = register(client, "student@example.com")
        response = client.post(
            "/api/v1/executions/single-file",
            headers=authorization(token),
            json={"source": "print('too large')"},
        )

    assert response.status_code == 400
    assert engine.single_calls == []


def test_blank_test_name_is_rejected_before_engine_submission() -> None:
    database = TestDatabase()
    engine = FakeExecutionEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token, _ = register(client, "student@example.com")
        response = client.post(
            "/api/v1/executions/project",
            headers=authorization(token),
            json={
                "files": {"main.py": "print('hello')"},
                "entrypoint": "main.py",
                "tests": [{"name": "   "}],
            },
        )

    assert response.status_code == 400
    assert engine.project_calls == []


def test_execution_cancellation_requires_job_ownership() -> None:
    database = TestDatabase()
    engine = FakeExecutionEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        first_token, _ = register(client, "first@example.com")
        second_token, _ = register(client, "second@example.com")
        submitted = client.post(
            "/api/v1/executions/single-file",
            json={"source": "while True: pass"},
            headers=authorization(first_token),
        )
        execution_id = submitted.json()["id"]
        forbidden = client.post(
            f"/api/v1/executions/{execution_id}/cancel",
            headers=authorization(second_token),
        )
        cancelled = client.post(
            f"/api/v1/executions/{execution_id}/cancel",
            headers=authorization(first_token),
        )

    assert forbidden.status_code == 404
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert engine.cancel_calls == [execution_id]
