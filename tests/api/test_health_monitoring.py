from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pydebugger.monitoring import MetricSummary
from pydebugger_api.config import APISettings
from pydebugger_api.database import DatabaseReadiness
from pydebugger_api.main import create_app
from pydebugger_api.models import User
from pydebugger_api.services.documents import DocumentService


class TestDatabase:
    __test__ = False

    def __init__(self, report: DatabaseReadiness | None = None) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        User.__table__.create(self.engine)
        self.report = report or DatabaseReadiness(
            True, True, True, "PostgreSQL, pgvector, and migrations are ready"
        )

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session

    def readiness_report(self) -> DatabaseReadiness:
        return self.report

    def dispose(self) -> None:
        self.engine.dispose()


class FakeMonitoringEngine:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(upload_limit_bytes=1_024)
        self.monitor = SimpleNamespace(last_error=None)
        self.windows: list[float | None] = []
        self.fail = False

    def monitoring_summary(
        self, *, since_seconds: float | None = 86_400
    ) -> tuple[MetricSummary, ...]:
        self.windows.append(since_seconds)
        if self.fail:
            raise RuntimeError("metrics storage unavailable")
        return (
            MetricSummary(
                operation="model.chat",
                calls=4,
                failures=1,
                average_latency_ms=120.0,
                p95_latency_ms=200.0,
                input_tokens=1_000,
                output_tokens=200,
                embedding_tokens=0,
                cost_usd=0.01,
                cost_configured=True,
            ),
            MetricSummary(
                operation="tutor.answer",
                calls=3,
                failures=0,
                average_latency_ms=150.0,
                p95_latency_ms=220.0,
                input_tokens=0,
                output_tokens=0,
                embedding_tokens=0,
                cost_usd=0.0,
                cost_configured=True,
            ),
        )


def settings() -> APISettings:
    return APISettings(
        PYDEBUGGER_DATABASE_URL=(
            "postgresql+psycopg://pydebugger:pydebugger@localhost/pydebugger"
        ),
        PYDEBUGGER_JWT_SECRET_KEY="test-secret-that-is-longer-than-thirty-two-characters",
    )


def register(client: TestClient) -> str:
    credentials = {"email": "student@example.com", "password": "safe-password-123"}
    client.post("/api/v1/auth/register", json=credentials)
    response = client.post("/api/v1/auth/login", json=credentials)
    return response.json()["access_token"]


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_readiness_returns_individual_failed_checks() -> None:
    database = TestDatabase(
        DatabaseReadiness(
            True,
            True,
            False,
            "Database migrations are not at the required revision",
        )
    )
    app = create_app(settings(), database, DocumentService(FakeMonitoringEngine()))

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"] == {
        "postgresql": True,
        "pgvector": True,
        "migrations": False,
    }


def test_monitoring_summary_is_authenticated_and_aggregated() -> None:
    database = TestDatabase()
    engine = FakeMonitoringEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        unauthorized = client.get("/api/v1/monitoring/summary")
        token = register(client)
        response = client.get(
            "/api/v1/monitoring/summary?window_seconds=3600",
            headers=authorization(token),
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    payload = response.json()
    assert payload["window_seconds"] == 3_600
    assert payload["total_calls"] == 7
    assert payload["total_failures"] == 1
    assert payload["total_cost_usd"] == 0.01
    assert payload["operations"][0]["failure_rate"] == 0.25
    assert engine.windows == [3_600]


def test_monitoring_validation_and_storage_failures_are_safe() -> None:
    database = TestDatabase()
    engine = FakeMonitoringEngine()
    app = create_app(settings(), database, DocumentService(engine))

    with TestClient(app) as client:
        token = register(client)
        invalid_window = client.get(
            "/api/v1/monitoring/summary?window_seconds=5",
            headers=authorization(token),
        )
        engine.fail = True
        unavailable = client.get(
            "/api/v1/monitoring/summary", headers=authorization(token)
        )

    assert invalid_window.status_code == 422
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "detail": "Monitoring data is temporarily unavailable"
    }
