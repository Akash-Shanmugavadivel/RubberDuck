"""PostgreSQL connection and readiness checks."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

EXPECTED_DATABASE_REVISION = "20261117_0009"


@dataclass(frozen=True)
class DatabaseReadiness:
    postgresql: bool
    pgvector: bool
    migrations: bool
    detail: str

    @property
    def ready(self) -> bool:
        return self.postgresql and self.pgvector and self.migrations


class Base(DeclarativeBase):
    """Base class for API-owned SQLAlchemy models."""


class Database:
    """Own the SQLAlchemy engine and session factory."""

    def __init__(self, url: str) -> None:
        self.engine: Engine = create_engine(url, pool_pre_ping=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session

    def readiness(self) -> tuple[bool, str]:
        """Check PostgreSQL connectivity and the pgvector extension."""

        report = self.readiness_report()
        return report.ready, report.detail

    def readiness_report(self) -> DatabaseReadiness:
        """Return individual readiness checks for deployment probes."""

        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                has_vector = connection.scalar(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                        ")"
                    )
                )
                has_migration_table = connection.scalar(
                    text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
                )
                revision = (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    if has_migration_table
                    else None
                )
        except SQLAlchemyError:
            return DatabaseReadiness(False, False, False, "PostgreSQL is unavailable")
        if not has_vector:
            return DatabaseReadiness(
                True,
                False,
                revision == EXPECTED_DATABASE_REVISION,
                "PostgreSQL is available, but pgvector is not installed",
            )
        if revision != EXPECTED_DATABASE_REVISION:
            return DatabaseReadiness(
                True,
                True,
                False,
                "Database migrations are not at the required revision",
            )
        return DatabaseReadiness(
            True, True, True, "PostgreSQL, pgvector, and migrations are ready"
        )

    def dispose(self) -> None:
        self.engine.dispose()
