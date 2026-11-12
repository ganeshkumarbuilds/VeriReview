import asyncio
import logging
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.project import ProjectStatus, ProjectType
from app.models.user import User
from app.services.projects import get_project
from app.workflows.repository_review import (
    RepositoryReviewError,
    review_imported_project,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["Repository Review"],
)


class RepositoryReviewAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    workflow_status: str
    message: str


def _run_repository_review(
    user_id: UUID,
    project_id: UUID,
) -> None:
    """Run the async repository workflow from a background task."""

    try:
        asyncio.run(
            review_imported_project(
                user_id=user_id,
                project_id=project_id,
            )
        )
    except RepositoryReviewError:
        logger.exception(
            "Repository review could not be completed: project=%s",
            project_id,
        )
    except Exception:
        logger.exception(
            "Unexpected repository review failure: project=%s",
            project_id,
        )


@router.post(
    "/review",
    response_model=RepositoryReviewAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_repository_review(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue a review of an owned uploaded project's files."""

    project = get_project(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if project.project_type != ProjectType.UPLOADED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Repository review is only available "
                "for uploaded projects."
            ),
        )

    active_statuses = {
        ProjectStatus.PLANNING,
        ProjectStatus.GENERATING,
        ProjectStatus.VERIFYING,
        ProjectStatus.REVIEWING,
        ProjectStatus.FIXING,
    }

    if project.status in active_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This project already has an active workflow.",
        )

    background_tasks.add_task(
        _run_repository_review,
        current_user.id,
        project_id,
    )

    return RepositoryReviewAccepted(
        project_id=project_id,
        workflow_status="QUEUED",
        message=(
            "Repository review has been queued. "
            "No project files will be modified."
        ),
    )