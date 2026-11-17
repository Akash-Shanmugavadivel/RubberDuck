"""Password and JWT authentication service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import APISettings
from ..models import User

JWT_ALGORITHM = "HS256"


class EmailAlreadyRegisteredError(ValueError):
    """Raised when registration uses an existing normalized email."""


class InvalidCredentialsError(ValueError):
    """Raised when credentials or an access token cannot be accepted."""


class AuthenticationService:
    """Own password hashing and signed access-token behavior."""

    def __init__(self, settings: APISettings) -> None:
        self._passwords = PasswordHash.recommended()
        self._dummy_hash = self._passwords.hash(uuid.uuid4().hex)
        self._secret = settings.jwt_secret_key.get_secret_value()
        self._expiry = timedelta(minutes=settings.jwt_expiry_minutes)

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().casefold()

    def register(self, session: Session, email: str, password: str) -> User:
        user = User(
            email=self.normalize_email(email),
            password_hash=self._passwords.hash(password),
        )
        session.add(user)
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise EmailAlreadyRegisteredError(
                "An account with this email already exists"
            ) from error
        session.refresh(user)
        return user

    def authenticate(self, session: Session, email: str, password: str) -> User:
        user = session.scalar(
            select(User).where(User.email == self.normalize_email(email))
        )
        password_hash = user.password_hash if user is not None else self._dummy_hash
        password_matches = self._passwords.verify(password, password_hash)
        if user is None or not password_matches:
            raise InvalidCredentialsError("Invalid email or password")
        if not user.is_active:
            raise InvalidCredentialsError("Invalid email or password")
        return user

    def create_access_token(self, user: User) -> tuple[str, int]:
        now = datetime.now(UTC)
        expires_at = now + self._expiry
        token = jwt.encode(
            {
                "sub": str(user.id),
                "type": "access",
                "iss": "pydebugger-api",
                "iat": now,
                "exp": expires_at,
                "jti": uuid.uuid4().hex,
            },
            self._secret,
            algorithm=JWT_ALGORITHM,
        )
        return token, int(self._expiry.total_seconds())

    def user_from_token(self, session: Session, token: str) -> User:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                issuer="pydebugger-api",
                options={"require": ["sub", "type", "iss", "iat", "exp", "jti"]},
            )
            if payload.get("type") != "access":
                raise InvalidCredentialsError("Invalid access token")
            user_id = uuid.UUID(str(payload["sub"]))
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise InvalidCredentialsError("Invalid access token") from error
        user = session.get(User, user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError("Invalid access token")
        return user
