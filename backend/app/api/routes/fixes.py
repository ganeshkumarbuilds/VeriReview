import logging
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.fix_request import FixRequest, FixRequestStatus
from app.models.user import User
from app.services.fix_requests import (
    ActiveFixRequestExistsError,
    FindingNotFixableError,
    FindingNotFoundError,
    FixRequestError,
    approve_fix_request,
    cancel_fix_request,
)
from app.services.projects import get_project
from app.workflows.fix_execution import execute_approved_fix


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["Project Fixes"],
)


class ApproveFixRequest(BaseModel):
    user_instruction: str | None = Field(
        default=None,
        max_length=5000,
    )


def serialize_fix_request(fix_request: FixRequest) -> dict:
    return {
        "id": str(fix_request.id),
        "project_id": str(fix_request.project_id),
        "finding_id": str(fix_request.finding_id),
        "status": fix_request.status.value,
        "user_instruction": fix_request.user_instruction,
        "approved_at": fix_request.approved_at,
        "started_at": fix_request.started_at,
        "completed_at": fix_request.completed_at,
        "error_message": fix_request.error_message,
        "created_at": fix_request.created_at,
    }


def verify_project_ownership(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> None:
    project = get_project(
        db=db,
        user_id=user_id,
        project_id=project_id,
    )

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )


@router.post(
    "/findings/{finding_id}/approve-fix",
    status_code=status.HTTP_201_CREATED,
)
def approve_finding_fix(
    project_id: UUID,
    finding_id: UUID,
    payload: ApproveFixRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Explicitly approve a fix for an individual finding."""

    try:
        fix_request = approve_fix_request(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
            finding_id=finding_id,
            user_instruction=payload.user_instruction,
        )

        db.commit()
        db.refresh(fix_request)

        return serialize_fix_request(fix_request)

    except FindingNotFoundError as exc:
        db.rollback()
        raise HTTPException(404, str(exc)) from exc

    except (
        FindingNotFixableError,
        ActiveFixRequestExistsError,
    ) as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc

    except Exception:
        db.rollback()
        raise


@router.post(
    "/fix-requests/{fix_request_id}/execute",
    status_code=status.HTTP_202_ACCEPTED,
)
def execute_fix(
    project_id: UUID,
    fix_request_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute an explicitly approved fix asynchronously."""

    verify_project_ownership(
        db,
        current_user.id,
        project_id,
    )

    fix_request = db.scalar(
        select(FixRequest)
        .where(
            FixRequest.id == fix_request_id,
            FixRequest.project_id == project_id,
        )
    )

    if fix_request is None:
        raise HTTPException(
            status_code=404,
            detail="Fix request not found.",
        )

    if fix_request.approved_at is None:
        raise HTTPException(
            status_code=403,
            detail="Explicit user approval is required.",
        )

    if fix_request.status != FixRequestStatus.REQUESTED:
        raise HTTPException(
            status_code=409,
            detail="Fix request is not available for execution.",
        )

    background_tasks.add_task(
        execute_approved_fix,
        user_id=current_user.id,
        project_id=project_id,
        fix_request_id=fix_request_id,
    )

    return {
        "message": "Approved fix execution started.",
        "fix_request_id": str(fix_request_id),
        "status": "REQUESTED",
    }


@router.get("/fix-requests/{fix_request_id}")
def get_fix_request(
    project_id: UUID,
    fix_request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve the current state of a fix request."""

    verify_project_ownership(
        db,
        current_user.id,
        project_id,
    )

    fix_request = db.scalar(
        select(FixRequest).where(
            FixRequest.id == fix_request_id,
            FixRequest.project_id == project_id,
        )
    )

    if fix_request is None:
        raise HTTPException(
            status_code=404,
            detail="Fix request not found.",
        )

    return serialize_fix_request(fix_request)


@router.post(
    "/fix-requests/{fix_request_id}/cancel",
)
def cancel_approved_fix(
    project_id: UUID,
    fix_request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending approved fix request."""

    try:
        fix_request = cancel_fix_request(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
            fix_request_id=fix_request_id,
        )

        db.commit()
        db.refresh(fix_request)

        return serialize_fix_request(fix_request)

    except FixRequestError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except Exception:
        db.rollback()
        raise