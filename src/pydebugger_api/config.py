"""Validated environment configuration for the FastAPI layer."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """API-only settings kept separate from the existing engine settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias="PYDEBUGGER_ENVIRONMENT",
    )
    database_url: str = Field(
        default="postgresql+psycopg://pydebugger:pydebugger@localhost:5432/pydebugger",
        validation_alias="PYDEBUGGER_DATABASE_URL",
        repr=False,
    )
    api_host: str = Field(default="127.0.0.1", validation_alias="PYDEBUGGER_API_HOST")
    api_port: int = Field(default=8000, validation_alias="PYDEBUGGER_API_PORT")
    cors_origins: str = Field(
        default="http://localhost:5173",
        validation_alias="PYDEBUGGER_CORS_ORIGINS",
    )
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("development-only-secret-change-before-production-7f3c8a91"),
        validation_alias="PYDEBUGGER_JWT_SECRET_KEY",
        repr=False,
    )
    jwt_expiry_minutes: int = Field(
        default=60,
        validation_alias="PYDEBUGGER_JWT_EXPIRY_MINUTES",
    )
    instructor_emails: str = Field(
        default="",
        validation_alias="PYDEBUGGER_INSTRUCTOR_EMAILS",
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql+psycopg://", "postgresql://")):
            raise ValueError("PYDEBUGGER_DATABASE_URL must be a PostgreSQL URL")
        return value

    @field_validator("api_port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65_535:
            raise ValueError("PYDEBUGGER_API_PORT must be between 1 and 65535")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret.startswith("<") or len(secret) < 32:
            raise ValueError("PYDEBUGGER_JWT_SECRET_KEY must be at least 32 characters")
        return value

    @field_validator("jwt_expiry_minutes")
    @classmethod
    def validate_jwt_expiry(cls, value: int) -> int:
        if not 5 <= value <= 1_440:
            raise ValueError("PYDEBUGGER_JWT_EXPIRY_MINUTES must be between 5 and 1440")
        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> APISettings:
        secret = self.jwt_secret_key.get_secret_value()
        if self.environment == "production" and secret.startswith("development-only"):
            raise ValueError("Production requires a unique PYDEBUGGER_JWT_SECRET_KEY")
        if "*" in self.allowed_origins:
            raise ValueError(
                "PYDEBUGGER_CORS_ORIGINS cannot contain '*' when credentials are enabled"
            )
        return self

    @property
    def allowed_origins(self) -> list[str]:
        origins = [
            origin.strip().rstrip("/") for origin in self.cors_origins.split(",")
        ]
        return [origin for origin in origins if origin]

    @property
    def configured_instructor_emails(self) -> set[str]:
        return {
            email.strip().casefold()
            for email in self.instructor_emails.split(",")
            if email.strip()
        }


@lru_cache(maxsize=1)
def get_api_settings() -> APISettings:
    return APISettings()
