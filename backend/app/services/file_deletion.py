import os
from pathlib import Path
from uuid import uuid4


def stage_file_deletion(
    storage_path: Path,
    project_directory: Path,
) -> Path:
    """
    Atomically move a file to a temporary deletion location.

    The temporary file remains inside the same directory so that
    os.replace can perform the move on the same filesystem.
    """

    project_directory = project_directory.resolve()
    storage_path = storage_path.resolve()

    if not storage_path.is_relative_to(project_directory):
        raise ValueError("File is outside the project storage directory")

    if not storage_path.is_file():
        raise FileNotFoundError("Stored project file is missing")

    staged_path = storage_path.with_name(
        f".{storage_path.name}.{uuid4().hex}.deleting"
    )

    os.replace(storage_path, staged_path)

    return staged_path


def restore_file_deletion(
    staged_path: Path,
    original_path: Path,
) -> None:
    """
    Restore a staged file if the database transaction fails.
    """

    if not staged_path.exists():
        return

    if original_path.exists():
        raise FileExistsError(
            "Cannot restore file because the original path already exists"
        )

    os.replace(staged_path, original_path)


def finalize_file_deletion(
    staged_path: Path,
    project_directory: Path,
) -> None:
    """
    Permanently remove a staged file and its empty parent directories.
    """

    project_directory = project_directory.resolve()
    staged_path = staged_path.resolve()

    if not staged_path.is_relative_to(project_directory):
        raise ValueError("Staged file is outside project storage")

    staged_path.unlink(missing_ok=True)

    parent = staged_path.parent

    while parent != project_directory:
        try:
            parent.rmdir()
        except OSError:
            break

        parent = parent.parent