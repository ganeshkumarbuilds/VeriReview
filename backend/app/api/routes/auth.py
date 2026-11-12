from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import jwt

from app.core.config import settings
from app.core.tokens import create_access_token, decode_access_token
from app.database.connection import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth import (
    authenticate_user,
    create_auth_session,
    register_user,
)
from app.services.refresh_tokens import (
    get_refresh_token,
    revoke_token_family,
    rotate_refresh_token,
)


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

security = HTTPBearer()

FRONTEND_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

REFRESH_COOKIE_NAME = "verireview_refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(
    response: Response,
    token: str,
) -> None:
    """Store refresh token in an HttpOnly cookie."""

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.APP_ENV != "development",
        samesite="strict",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh-token cookie."""

    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.APP_ENV != "development",
        samesite="strict",
    )


def validate_request_origin(request: Request) -> None:
    """Validate the origin of cookie-authenticated requests."""

    origin = request.headers.get("origin")

    if origin not in FRONTEND_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid request origin",
        )


def build_user_response(user: User) -> UserResponse:
    """Build a safe public representation of a user."""

    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        is_active=user.is_active,
        is_verified=user.is_verified,
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate a request using its JWT access token."""

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = UUID(payload["sub"])

    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.scalar(
        select(User).where(User.id == user_id)
    )

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    data: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Register a new user and create an authentication session."""

    try:
        user = register_user(db, data)

        access_token, refresh_token, expires_in = (
            create_auth_session(db, user)
        )

        db.commit()
        db.refresh(user)

        set_refresh_cookie(response, refresh_token)

        return TokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=build_user_response(user),
        )

    except ValueError as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username is already registered",
        )

    except Exception:
        db.rollback()
        raise


@router.post(
    "/login",
    response_model=TokenResponse,
)
def login(
    data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate a user and create a session."""

    user = authenticate_user(
        db,
        data.identifier,
        data.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
        )

    try:
        access_token, refresh_token, expires_in = (
            create_auth_session(db, user)
        )

        db.commit()

        set_refresh_cookie(response, refresh_token)

        return TokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=build_user_response(user),
        )

    except Exception:
        db.rollback()
        raise


@router.post(
    "/refresh",
    response_model=TokenResponse,
)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Rotate a refresh token and issue a new access token."""

    validate_request_origin(request)

    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    try:
        result = rotate_refresh_token(db, raw_token)

        if result.status == "reuse_detected":
            # This commit is essential: family revocation must persist.
            db.commit()
            clear_refresh_cookie(response)

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token reuse detected. Please log in again.",
            )

        if result.status != "rotated":
            db.rollback()
            clear_refresh_cookie(response)

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )

        user = db.scalar(
            select(User).where(
                User.id == result.token_record.user_id
            )
        )

        if user is None or not user.is_active:
            revoke_token_family(
                db,
                result.token_record.family_id,
            )

            db.commit()
            clear_refresh_cookie(response)

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is unavailable",
            )

        access_token = create_access_token(user.id)

        db.commit()

        set_refresh_cookie(response, result.raw_token)

        return TokenResponse(
            access_token=access_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=build_user_response(user),
        )

    except HTTPException:
        raise

    except Exception:
        db.rollback()
        raise


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Revoke the current refresh-token session."""

    validate_request_origin(request)

    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)

    try:
        if raw_token:
            token_record = get_refresh_token(
                db,
                raw_token,
                lock=True,
            )

            if token_record is not None:
                revoke_token_family(
                    db,
                    token_record.family_id,
                )

        db.commit()

        clear_refresh_cookie(response)

        return {
            "message": "Successfully logged out",
        }

    except Exception:
        db.rollback()
        raise


@router.get(
    "/me",
    response_model=UserResponse,
)
def get_me(
    current_user: User = Depends(get_current_user),
):
    """Return the currently authenticated user."""

    return build_user_response(current_user)