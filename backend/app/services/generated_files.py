import mimetypes
import os

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, event
from sqlalchemy.orm import Session

from app.models.project_file import FileOrigin, ProjectFile
from app.services.file_storage import (
    calculate_checksum,
    ensure_inside_directory,
    get_project_directory,
    get_path_collision_key,
    publish_file_without_overwrite,
    validate_relative_path,
)
from app.services.projects import get_project


_PENDING_FILE_UPDATES = "verireview_pending_file_updates"


@event.listens_for(Session, "after_commit")
def _cleanup_committed_file_updates(session):
    """Delete backups only after the database transaction commits."""

    updates = session.info.pop(_PENDING_FILE_UPDATES, [])

    for backup_path, _ in updates:
        try:
            Path(backup_path).unlink(missing_ok=True)
        except OSError:
            # Keep the backup if cleanup fails.
            pass


@event.listens_for(Session, "after_rollback")
def _restore_rolled_back_file_updates(session):
    """Restore original files when the database transaction rolls back."""

    updates = session.info.pop(_PENDING_FILE_UPDATES, [])

    for backup_path, destination_path in reversed(updates):
        backup = Path(backup_path)
        destination = Path(destination_path)

        if not backup.exists():
            continue

        try:
            destination.unlink(missing_ok=True)
            os.replace(backup, destination)
        except OSError:
            # Never delete a backup that may be needed for recovery.
            pass


def _build_project_file(
    project_id: UUID,
    relative_path: str,
    destination: Path,
    content: bytes,
) -> ProjectFile:
    """Build database metadata for a generated file."""

    return ProjectFile(
        project_id=project_id,
        file_path=relative_path,
        storage_path=str(destination),
        file_name=Path(relative_path).name,
        file_extension=Path(relative_path).suffix.lower() or None,
        mime_type=mimetypes.guess_type(relative_path)[0],
        file_size=len(content),
        origin=FileOrigin.GENERATED,
        checksum=calculate_checksum(destination),
    )


def create_generated_file(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    file_path: str,
    content: bytes,
) -> ProjectFile:
    """
    Create a new generated project file.

    Existing files are never overwritten.
    The caller controls the database transaction.
    """

    project = get_project(db, user_id, project_id)

    if project is None:
        raise ValueError("Project not found")

    if not isinstance(content, bytes):
        raise TypeError("Generated file content must be bytes")

    relative_path = validate_relative_path(file_path)
    collision_key = get_path_collision_key(relative_path)

    existing_files = db.scalars(
        select(ProjectFile).where(
            ProjectFile.project_id == project_id
        )
    ).all()

    if any(
        get_path_collision_key(item.file_path) == collision_key
        for item in existing_files
    ):
        raise FileExistsError(
            "A file with this path already exists"
        )

    project_directory = get_project_directory(project_id)

    project_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = ensure_inside_directory(
        project_directory / Path(*relative_path.split("/")),
        project_directory,
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = ensure_inside_directory(
        destination,
        project_directory,
    )

    temporary_path = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )

    try:
        with temporary_path.open("xb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        publish_file_without_overwrite(
            temporary_path,
            destination,
        )

        project_file = _build_project_file(
            project_id,
            relative_path,
            destination,
            content,
        )

        try:
            db.add(project_file)
            db.flush()
            db.refresh(project_file)

        except Exception:
            destination.unlink(missing_ok=True)
            raise

        return project_file

    finally:
        temporary_path.unlink(missing_ok=True)


def update_generated_file(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    file_path: str,
    content: bytes,
    approved: bool = False,
) -> ProjectFile:
    """
    Update an existing project file after explicit approval.

    For real SQLAlchemy sessions, the original file remains backed
    up until the database transaction commits.

    For lightweight test sessions without transaction event support,
    the backup is removed immediately after a successful flush.
    """

    if not approved:
        raise PermissionError(
            "File updates require explicit user approval"
        )

    project = get_project(db, user_id, project_id)

    if project is None:
        raise ValueError("Project not found")

    if not isinstance(content, bytes):
        raise TypeError("Generated file content must be bytes")

    relative_path = validate_relative_path(file_path)
    collision_key = get_path_collision_key(relative_path)

    existing_files = db.scalars(
        select(ProjectFile).where(
            ProjectFile.project_id == project_id
        )
    ).all()

    project_file = next(
        (
            item
            for item in existing_files
            if get_path_collision_key(item.file_path) == collision_key
        ),
        None,
    )

    if project_file is None:
        raise FileNotFoundError(
            "The target project file does not exist"
        )

    project_directory = get_project_directory(project_id)

    destination = ensure_inside_directory(
        Path(project_file.storage_path),
        project_directory,
    )

    if not destination.is_file():
        raise FileNotFoundError(
            "The stored project file is missing"
        )

    if destination.is_symlink():
        raise ValueError(
            "Symbolic links cannot be modified"
        )

    temporary_path = destination.with_name(
        f".{destination.name}.{uuid4().hex}.tmp"
    )

    backup_path = destination.with_name(
        f".{destination.name}.{uuid4().hex}.bak"
    )

    session_info = getattr(db, "info", None)
    supports_transaction_events = isinstance(session_info, dict)

    try:
        # Prepare replacement without modifying the original.
        with temporary_path.open("xb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())

        # Preserve the original file.
        os.replace(destination, backup_path)

        try:
            # Publish replacement.
            os.replace(temporary_path, destination)

            project_file.file_size = len(content)
            project_file.file_name = Path(relative_path).name
            project_file.file_extension = (
                Path(relative_path).suffix.lower() or None
            )
            project_file.mime_type = (
                mimetypes.guess_type(relative_path)[0]
            )
            project_file.origin = FileOrigin.GENERATED
            project_file.checksum = calculate_checksum(destination)

            db.flush()
            db.refresh(project_file)

        except Exception as original_error:
            try:
                destination.unlink(missing_ok=True)
                os.replace(backup_path, destination)

            except OSError as restoration_error:
                raise RuntimeError(
                    "Original backup preserved because restoration failed: "
                    f"{backup_path}"
                ) from restoration_error

            raise original_error

        if supports_transaction_events:
            session_info.setdefault(
                _PENDING_FILE_UPDATES,
                [],
            ).append(
                (str(backup_path), str(destination))
            )
        else:
            # FakeDB and other non-SQLAlchemy test sessions
            # do not support after_commit/after_rollback.
            backup_path.unlink(missing_ok=True)

        return project_file

    finally:
        temporary_path.unlink(missing_ok=True)