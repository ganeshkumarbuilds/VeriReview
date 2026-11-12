import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.project_deletion import (
    finalize_project_directory_deletion,
    restore_project_directory,
    stage_project_directory_deletion,
)
from app.services.projects import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["Projects"],
)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_new_project(
    data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = create_project(
        db=db,
        user_id=current_user.id,
        data=data,
    )

    db.commit()
    db.refresh(project)

    return project


@router.get(
    "",
    response_model=ProjectListResponse,
)
def get_all_projects(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_projects(
        db=db,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
)
def get_project_details(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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

    return project


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
)
def update_project_details(
    project_id: UUID,
    data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = update_project(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
        data=data,
    )

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    db.commit()
    db.refresh(project)

    return project


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_details(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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

    staged_directory = None

    try:
        staged_directory = stage_project_directory_deletion(project_id)

        deleted = delete_project(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
        )

        if not deleted:
            db.rollback()
            restore_project_directory(
                project_id,
                staged_directory,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        db.commit()

    except HTTPException:
        raise

    except Exception:
        db.rollback()

        try:
            restore_project_directory(
                project_id,
                staged_directory,
            )
        except Exception:
            logger.exception(
                "CRITICAL: Failed to restore project storage after deletion failure: %s",
                project_id,
            )

        raise

    try:
        finalize_project_directory_deletion(staged_directory)
    except OSError:
        logger.exception(
            "Project was deleted from the database, but staged storage cleanup failed: %s",
            project_id,
        )

    return None