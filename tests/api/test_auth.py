from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pydebugger_api.config import APISettings
from pydebugger_api.main import create_app
from pydebugger_api.models import User


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

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session

    def readiness(self) -> tuple[bool, str]:
        return True, "Test database is ready"

    def dispose(self) -> None:
        self.engine.dispose()


def api_settings() -> APISettings:
    return APISettings(
        PYDEBUGGER_DATABASE_URL=(
            "postgresql+psycopg://pydebugger:pydebugger@localhost/pydebugger"
        ),
        PYDEBUGGER_JWT_SECRET_KEY="test-secret-that-is-longer-than-thirty-two-characters",
        PYDEBUGGER_JWT_EXPIRY_MINUTES=60,
    )


def test_register_login_and_get_current_user() -> None:
    database = TestDatabase()
    app = create_app(api_settings(), database)

    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/auth/register",
            json={"email": " Student@College.edu ", "password": "safe-password-123"},
        )
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"email": "student@college.edu", "password": "safe-password-123"},
        )
        token = logged_in.json()["access_token"]
        current = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        logged_out = client.post(
            "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )

    assert registered.status_code == 201
    assert registered.json()["email"] == "student@college.edu"
    assert "password" not in registered.json()
    assert logged_in.status_code == 200
    assert logged_in.json()["token_type"] == "bearer"
    assert logged_in.json()["expires_in"] == 3_600
    assert current.status_code == 200
    assert current.json()["id"] == registered.json()["id"]
    assert logged_out.status_code == 200


def test_password_is_argon2_hashed() -> None:
    database = TestDatabase()
    app = create_app(api_settings(), database)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "student@example.com", "password": "safe-password-123"},
        )
        with database.session_factory() as session:
            user = session.scalar(select(User))

    assert response.status_code == 201
    assert user is not None
    assert user.password_hash != "safe-password-123"
    assert user.password_hash.startswith("$argon2")


def test_duplicate_email_is_case_insensitive() -> None:
    database = TestDatabase()
    app = create_app(api_settings(), database)

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/auth/register",
            json={"email": "student@example.com", "password": "safe-password-123"},
        )
        duplicate = client.post(
            "/api/v1/auth/register",
            json={"email": "STUDENT@example.com", "password": "another-password"},
        )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "An account with this email already exists"}


def test_wrong_password_and_invalid_token_are_rejected() -> None:
    database = TestDatabase()
    app = create_app(api_settings(), database)

    with TestClient(app) as client:
        client.post(
            "/api/v1/auth/register",
            json={"email": "student@example.com", "password": "safe-password-123"},
        )
        wrong_password = client.post(
            "/api/v1/auth/login",
            json={"email": "student@example.com", "password": "wrong-password"},
        )
        invalid_token = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer invalid-token"}
        )
        missing_token = client.get("/api/v1/auth/me")

    assert wrong_password.status_code == 401
    assert wrong_password.json() == {"detail": "Invalid email or password"}
    assert invalid_token.status_code == 401
    assert missing_token.status_code == 401
    assert invalid_token.headers["www-authenticate"] == "Bearer"


def test_credentials_are_validated_before_database_access() -> None:
    database = TestDatabase()
    app = create_app(api_settings(), database)

    with TestClient(app) as client:
        bad_email = client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": "safe-password-123"},
        )
        short_password = client.post(
            "/api/v1/auth/register",
            json={"email": "student@example.com", "password": "short"},
        )

    assert bad_email.status_code == 422
    assert short_password.status_code == 422


def test_production_rejects_development_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="Production requires a unique"):
        APISettings(
            PYDEBUGGER_ENVIRONMENT="production",
            PYDEBUGGER_DATABASE_URL=(
                "postgresql+psycopg://pydebugger:pydebugger@localhost/pydebugger"
            ),
        )
