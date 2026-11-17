from fastapi.testclient import TestClient

from pydebugger_api.config import APISettings
from pydebugger_api.main import create_app


class StubDatabase:
    def __init__(self, readiness: tuple[bool, str]) -> None:
        self.result = readiness
        self.disposed = False

    def readiness(self) -> tuple[bool, str]:
        return self.result

    def dispose(self) -> None:
        self.disposed = True


def settings(**overrides: object) -> APISettings:
    values = {
        "PYDEBUGGER_DATABASE_URL": (
            "postgresql+psycopg://pydebugger:pydebugger@localhost/pydebugger"
        ),
        "PYDEBUGGER_CORS_ORIGINS": "http://localhost:5173,http://localhost:3000/",
    }
    values.update(overrides)
    return APISettings(**values)


def test_health_does_not_depend_on_database_readiness() -> None:
    app = create_app(settings(), StubDatabase((False, "database unavailable")))

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "pydebugger-api"}


def test_ready_reports_postgres_and_pgvector() -> None:
    database = StubDatabase((True, "PostgreSQL and pgvector are ready"))
    app = create_app(settings(), database)

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["database"] == "PostgreSQL and pgvector are ready"
    assert database.disposed is True


def test_ready_returns_503_when_dependency_is_unavailable() -> None:
    app = create_app(settings(), StubDatabase((False, "PostgreSQL is unavailable")))

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "service": "pydebugger-api",
        "database": "PostgreSQL is unavailable",
        "checks": {
            "postgresql": False,
            "pgvector": False,
            "migrations": False,
        },
    }


def test_cors_origins_are_normalized() -> None:
    api_settings = settings()

    assert api_settings.allowed_origins == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]
