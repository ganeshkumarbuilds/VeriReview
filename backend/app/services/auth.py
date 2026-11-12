from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    hash_password,
    verify_password_and_update,
)
from app.core.tokens import create_access_token
from app.models.user import User
from app.schemas.auth import RegisterRequest
from app.services.refresh_tokens import create_refresh_token


def register_user(
    db: Session,
    data: RegisterRequest,
) -> User:
    """Register a new user."""

    email = str(data.email).lower()
    username = data.username.lower()

    existing_user = db.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == email,
                func.lower(User.username) == username,
            )
        )
    )

    if existing_user:
        raise ValueError("Email or username is already registered")

    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
    )

    db.add(user)
    db.flush()

    return user


def authenticate_user(
    db: Session,
    identifier: str,
    password: str,
) -> User | None:
    """Authenticate using email or username."""

    normalized_identifier = identifier.strip().lower()

    user = db.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == normalized_identifier,
                func.lower(User.username) == normalized_identifier,
            )
        )
    )

    if user is None:
        return None

    if not user.is_active:
        return None

    valid, updated_hash = verify_password_and_update(
        password,
        user.hashed_password,
    )

    if not valid:
        return None

    if updated_hash is not None:
        user.hashed_password = updated_hash
        db.flush()

    return user


def create_auth_session(
    db: Session,
    user: User,
) -> tuple[str, str, int]:
    """Create access and refresh tokens for an authenticated user."""

    access_token = create_access_token(user.id)

    refresh_token, _ = create_refresh_token(
        db=db,
        user_id=user.id,
    )

    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    return access_token, refresh_token, expires_in