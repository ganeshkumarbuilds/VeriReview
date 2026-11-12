from math import ceil
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


def create_project(
    db: Session,
    user_id: UUID,
    data: ProjectCreate,
) -> Project:
    """Create a project owned by the authenticated user."""

    project = Project(
        user_id=user_id,
        name=data.name,
        description=data.description,
        project_type=data.project_type,
        technology_stack=data.technology_stack,
    )

    db.add(project)
    db.flush()
    db.refresh(project)

    return project


def list_projects(
    db: Session,
    user_id: UUID,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """List projects belonging to a specific user."""

    statement = select(Project).where(
        Project.user_id == user_id
    )

    total = db.scalar(
        select(func.count())
        .select_from(Project)
        .where(Project.user_id == user_id)
    ) or 0

    projects = db.scalars(
        statement
        .order_by(Project.created_at.desc(), Project.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    total_pages = ceil(total / page_size) if total else 0

    return {
        "projects": projects,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def get_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> Project | None:
    """Retrieve a project only if it belongs to the user."""

    return db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
    )


def update_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    data: ProjectUpdate,
) -> Project | None:
    """Update a project owned by the authenticated user."""

    project = get_project(
        db,
        user_id,
        project_id,
    )

    if project is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(project, field, value)

    db.flush()
    db.refresh(project)

    return project


def delete_project(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> bool:
    """Delete a project only if it belongs to the user."""

    project = get_project(
        db,
        user_id,
        project_id,
    )

    if project is None:
        return False

    db.delete(project)
    db.flush()

    return True