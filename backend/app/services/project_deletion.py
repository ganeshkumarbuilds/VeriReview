import logging
import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from app.services.file_storage import (
    STORAGE_ROOT,
    get_project_directory,
)

logger = logging.getLogger(__name__)


def stage_project_directory_deletion(
    project_id: UUID,
) -> Path | None:
    """
    Move a project's storage directory to a temporary deletion location.

    Returns the staged directory path, or None if no directory exists.
    """

    project_directory = get_project_directory(project_id)

    if not project_directory.exists():
        return None

    staged_directory = (
        STORAGE_ROOT
        / f".deleting-{project_id}-{uuid4().hex}"
    )

    os.replace(project_directory, staged_directory)

    return staged_directory


def restore_project_directory(
    project_id: UUID,
    staged_directory: Path | None,
) -> None:
    """
    Restore a staged project directory if database deletion fails.
    """

    if staged_directory is None or not staged_directory.exists():
        return

    project_directory = get_project_directory(project_id)

    if project_directory.exists():
        raise FileExistsError(
            "Cannot restore project storage because the original directory already exists"
        )

    os.replace(staged_directory, project_directory)


def finalize_project_directory_deletion(
    staged_directory: Path | None,
) -> None:
    """
    Permanently remove a staged directory after database commit.
    """

    if staged_directory is not None and staged_directory.exists():
        shutil.rmtree(staged_directory)