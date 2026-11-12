import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.refresh_token import RefreshToken


@dataclass
class RotationResult:
    status: Literal[
        "rotated",
        "invalid",
        "expired",
        "reuse_detected",
    ]
    raw_token: str | None = None
    token_record: RefreshToken | None = None


def generate_refresh_token() -> str:
    """Generate a cryptographically secure refresh token."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(token: str) -> str:
    """Return the SHA-256 hash of a refresh token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_refresh_token(
    db: Session,
    user_id: UUID,
    family_id: UUID | None = None,
) -> tuple[str, RefreshToken]:
    """Create and store a hashed refresh token."""

    raw_token = generate_refresh_token()

    token_record = RefreshToken(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_token),
        family_id=family_id or uuid4(),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )

    db.add(token_record)
    db.flush()

    return raw_token, token_record


def get_refresh_token(
    db: Session,
    raw_token: str,
    lock: bool = False,
) -> RefreshToken | None:
    """Find a refresh token using its hash."""

    statement = select(RefreshToken).where(
        RefreshToken.token_hash == hash_refresh_token(raw_token)
    )

    if lock:
        statement = statement.with_for_update()

    return db.scalar(statement)


def revoke_refresh_token(
    token_record: RefreshToken,
) -> None:
    """Revoke an individual refresh token."""

    if token_record.revoked_at is None:
        token_record.revoked_at = datetime.now(timezone.utc)


def revoke_token_family(
    db: Session,
    family_id: UUID,
) -> None:
    """Revoke every active token belonging to a session family."""

    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.family_id == family_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )


def rotate_refresh_token(
    db: Session,
    raw_token: str,
) -> RotationResult:
    """Rotate a refresh token and detect reuse of revoked tokens."""

    # Lock the existing token to prevent concurrent rotation.
    old_token = get_refresh_token(
        db,
        raw_token,
        lock=True,
    )

    if old_token is None:
        return RotationResult(status="invalid")

    # A previously rotated token has been reused.
    if old_token.revoked_at is not None:
        revoke_token_family(db, old_token.family_id)
        db.flush()

        return RotationResult(status="reuse_detected")

    # Reject expired tokens.
    now = datetime.now(timezone.utc)

    if old_token.expires_at <= now:
        return RotationResult(status="expired")

    # Revoke the previous token.
    revoke_refresh_token(old_token)

    # Create a replacement in the same session family.
    new_raw_token, new_record = create_refresh_token(
        db=db,
        user_id=old_token.user_id,
        family_id=old_token.family_id,
    )

    db.flush()

    return RotationResult(
        status="rotated",
        raw_token=new_raw_token,
        token_record=new_record,
    )