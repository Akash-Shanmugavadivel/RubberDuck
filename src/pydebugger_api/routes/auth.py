"""Email/password authentication endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..dependencies import get_authentication, get_current_user, get_session
from ..models import User
from ..schemas.auth import (
    CredentialsRequest,
    MessageResponse,
    TokenResponse,
    UserResponse,
)
from ..services.auth import (
    AuthenticationService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: CredentialsRequest,
    session: Annotated[Session, Depends(get_session)],
    authentication: Annotated[AuthenticationService, Depends(get_authentication)],
) -> User:
    try:
        return authentication.register(session, request.email, request.password)
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error


@router.post("/login", response_model=TokenResponse)
def login(
    request: CredentialsRequest,
    session: Annotated[Session, Depends(get_session)],
    authentication: Annotated[AuthenticationService, Depends(get_authentication)],
) -> TokenResponse:
    try:
        user = authentication.authenticate(session, request.email, request.password)
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    token, expires_in = authentication.create_access_token(user)
    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.post("/logout", response_model=MessageResponse)
def logout(_: Annotated[User, Depends(get_current_user)]) -> MessageResponse:
    return MessageResponse(
        message="Logged out; remove the access token from the client"
    )
