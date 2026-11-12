import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.finding import Finding, FindingStatus
from app.models.fix_request import FixRequest, FixRequestStatus
from app.services.projects import get_project


logger = logging.getLogger(__name__)


class FixRequestError(Exception):
    """Base exception for fix request errors."""


class FindingNotFoundError(FixRequestError):
    """Finding does not exist or is not accessible."""


class FindingNotFixableError(FixRequestError):
    """Finding cannot be fixed in its current state."""


class ActiveFixRequestExistsError(FixRequestError):
    """An active fix request already exists."""


def approve_fix_request(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    finding_id: UUID,
    user_instruction: str | None = None,
) -> FixRequest:
    """
    Create an explicitly approved fix request.

    This function records approval only. It does not modify
    project files or execute the Coding Agent.
    """

    project = get_project(
        db=db,
        user_id=user_id,
        project_id=project_id,
    )

    if project is None:
        raise FindingNotFoundError("Project not found.")

    finding = db.scalar(
        select(Finding)
        .where(
            Finding.id == finding_id,
            Finding.project_id == project_id,
        )
        .with_for_update()
    )

    if finding is None:
        raise FindingNotFoundError("Finding not found.")

    if finding.status != FindingStatus.OPEN:
        raise FindingNotFixableError(
            "Only open findings can be approved for fixing."
        )

    active_request = db.scalar(
        select(FixRequest)
        .where(
            FixRequest.project_id == project_id,
            FixRequest.finding_id == finding_id,
            FixRequest.status.in_([
                FixRequestStatus.REQUESTED,
                FixRequestStatus.IN_PROGRESS,
            ]),
        )
        .with_for_update()
    )

    if active_request is not None:
        raise ActiveFixRequestExistsError(
            "An active fix request already exists for this finding."
        )

    instruction = (
        user_instruction.strip()
        if user_instruction and user_instruction.strip()
        else None
    )

    fix_request = FixRequest(
        project_id=project_id,
        finding_id=finding_id,
        status=FixRequestStatus.REQUESTED,
        user_instruction=instruction,
        approved_at=datetime.now(timezone.utc),
    )

    db.add(fix_request)
    db.flush()
    db.refresh(fix_request)

    logger.info(
        "Fix request approved: project=%s finding=%s request=%s",
        project_id,
        finding_id,
        fix_request.id,
    )

    return fix_request


def start_fix_request(
    db: Session,
    project_id: UUID,
    fix_request_id: UUID,
) -> FixRequest:
    """Mark an approved fix request as in progress."""

    fix_request = db.scalar(
        select(FixRequest)
        .where(
            FixRequest.id == fix_request_id,
            FixRequest.project_id == project_id,
        )
        .with_for_update()
    )

    if fix_request is None:
        raise FixRequestError("Fix request not found.")

    if fix_request.approved_at is None:
        raise FixRequestError(
            "Fix request requires explicit user approval."
        )

    if fix_request.status != FixRequestStatus.REQUESTED:
        raise FixRequestError(
            "Only requested fix operations can be started."
        )

    now = datetime.now(timezone.utc)

    fix_request.status = FixRequestStatus.IN_PROGRESS
    fix_request.started_at = now
    fix_request.error_message = None

    db.flush()
    db.refresh(fix_request)

    return fix_request


def complete_fix_request(
    db: Session,
    project_id: UUID,
    fix_request_id: UUID,
) -> FixRequest:
    """Mark a successfully verified fix as completed."""

    fix_request = db.scalar(
        select(FixRequest)
        .where(
            FixRequest.id == fix_request_id,
            FixRequest.project_id == project_id,
        )
        .with_for_update()
    )

    if fix_request is None:
        raise FixRequestError("Fix request not found.")

    if fix_request.status != FixRequestStatus.IN_PROGRESS:
        raise FixRequestError(
            "Only in-progress fix requests can be completed."
        )

    fix_request.status = FixRequestStatus.COMPLETED
    fix_request.completed_at = datetime.now(timezone.utc)
    fix_request.error_message = None

    db.flush()
    db.refresh(fix_request)

    return fix_request


def fail_fix_request(
    db: Session,
    project_id: UUID,
    fix_request_id: UUID,
    error_message: str,
) -> FixRequest:
    """Record a failed fix operation."""

    fix_request = db.scalar(
        select(FixRequest)
        .where(
            FixRequest.id == fix_request_id,
            FixRequest.project_id == project_id,
        )
        .with_for_update()
    )

    if fix_request is None:
        raise FixRequestError("Fix request not found.")

    if fix_request.status != FixRequestStatus.IN_PROGRESS:
        raise FixRequestError(
            "Only in-progress fix requests can fail."
        )

    fix_request.status = FixRequestStatus.FAILED
    fix_request.error_message = (
        error_message.strip() or "Fix operation failed."
    )

    db.flush()
    db.refresh(fix_request)

    return fix_request


def cancel_fix_request(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    fix_request_id: UUID,
) -> FixRequest:
    """Cancel a pending approved fix request."""

    project = get_project(
        db=db,
        user_id=user_id,
        project_id=project_id,
    )

    if project is None:
        raise FixRequestError("Project not found.")

    fix_request = db.scalar(
        select(FixRequest)
        .where(
            FixRequest.id == fix_request_id,
            FixRequest.project_id == project_id,
        )
        .with_for_update()
    )

    if fix_request is None:
        raise FixRequestError("Fix request not found.")

    if fix_request.status != FixRequestStatus.REQUESTED:
        raise FixRequestError(
            "Only pending fix requests can be cancelled."
        )

    fix_request.status = FixRequestStatus.CANCELLED

    db.flush()
    db.refresh(fix_request)

    return fix_request