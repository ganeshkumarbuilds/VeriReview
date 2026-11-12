import mimetypes

from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_file import FileOrigin, ProjectFile
from app.services.file_storage import (
    get_project_directory,
    save_uploaded_file,
    validate_relative_path,
)
from app.services.projects import get_project


def upload_project_file(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    file_path: str,
    content: bytes,
) -> ProjectFile:
    """Upload a file into a project owned by the user."""

    project = get_project(db, user_id, project_id)

    if project is None:
        raise ValueError("Project not found")

    relative_path = validate_relative_path(file_path)

    existing_file = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.file_path == relative_path,
        )
    )

    if existing_file is not None:
        raise FileExistsError(
            "A file with this path already exists"
        )

    destination, checksum = save_uploaded_file(
        project_id=project_id,
        file_path=relative_path,
        content=content,
    )

    project_file = ProjectFile(
        project_id=project_id,
        file_path=relative_path,
        storage_path=str(destination),
        file_name=Path(relative_path).name,
        file_extension=Path(relative_path).suffix.lower() or None,
        mime_type=mimetypes.guess_type(relative_path)[0],
        file_size=len(content),
        origin=FileOrigin.UPLOADED,
        checksum=checksum,
    )

    try:
        db.add(project_file)
        db.flush()
        db.refresh(project_file)

    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return project_file


def list_project_files(
    db: Session,
    user_id: UUID,
    project_id: UUID,
) -> dict:
    """List files belonging to an owned project."""

    project = get_project(db, user_id, project_id)

    if project is None:
        raise ValueError("Project not found")

    files = db.scalars(
        select(ProjectFile)
        .where(ProjectFile.project_id == project_id)
        .order_by(ProjectFile.file_path.asc())
    ).all()

    return {
        "files": files,
        "total": len(files),
    }


def get_project_file(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    file_id: UUID,
) -> tuple[ProjectFile, Path] | None:
    """Retrieve an owned project file and validate its storage path."""

    project = get_project(db, user_id, project_id)

    if project is None:
        return None

    project_file = db.scalar(
        select(ProjectFile).where(
            ProjectFile.id == file_id,
            ProjectFile.project_id == project_id,
        )
    )

    if project_file is None:
        return None

    project_directory = get_project_directory(project_id)

    storage_path = Path(project_file.storage_path).resolve()

    if not storage_path.is_relative_to(project_directory):
        raise ValueError("Invalid file storage path")

    if not storage_path.is_file():
        raise FileNotFoundError("Stored project file is missing")

    return project_file, storage_path


def delete_project_file(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    file_id: UUID,
) -> bool:
    """Delete an owned project file."""

    result = get_project_file(
        db,
        user_id,
        project_id,
        file_id,
    )

    if result is None:
        return False

    project_file, storage_path = result

    db.delete(project_file)
    db.flush()

    storage_path.unlink(missing_ok=True)

    project_directory = get_project_directory(project_id)
    parent = storage_path.parent

    while parent != project_directory:
        try:
            parent.rmdir()
        except OSError:
            break

        parent = parent.parent

    return True