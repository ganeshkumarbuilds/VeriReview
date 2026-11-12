import logging
import mimetypes
import zipfile

from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.project_file import FileOrigin, ProjectFile
from app.models.user import User
from app.schemas.project_file import (
    ProjectFileListResponse,
    ProjectFileResponse,
)
from app.services.file_storage import (
    MAX_ARCHIVE_SIZE,
    extract_zip_archive,
    get_project_directory,
)
from app.services.file_deletion import (
    finalize_file_deletion,
    restore_file_deletion,
    stage_file_deletion,
)
from app.services.project_files import (
    get_project_file,
    list_project_files,
    upload_project_file,
)
from app.services.projects import get_project


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/files",
    tags=["Project Files"],
)

MAX_UPLOAD_SIZE = 50 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


async def read_upload(
    file: UploadFile,
    limit: int,
) -> bytes:
    """Read an uploaded file while enforcing its size limit."""

    content = bytearray()

    while True:
        chunk = await file.read(CHUNK_SIZE)

        if not chunk:
            break

        content.extend(chunk)

        if len(content) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Uploaded file exceeds the size limit",
            )

    return bytes(content)


def cleanup_files(paths: list[Path]) -> None:
    """Remove files created by a failed upload operation."""

    for path in reversed(paths):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # Preserve the original exception.
            pass


def validate_filename(filename: str | None) -> str:
    """Normalize and validate an uploaded filename."""

    if not filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is required",
        )

    normalized = filename.replace("\\", "/")
    safe_name = PurePosixPath(normalized).name

    if safe_name in ("", ".", ".."):
        raise HTTPException(
            status_code=400,
            detail="Invalid filename",
        )

    return safe_name


@router.post(
    "/upload",
    response_model=ProjectFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    project_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an individual file to an owned project."""

    created_path = None

    try:
        project = get_project(
            db,
            current_user.id,
            project_id,
        )

        if project is None:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        filename = validate_filename(file.filename)

        content = await read_upload(
            file,
            MAX_UPLOAD_SIZE,
        )

        project_file = upload_project_file(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
            file_path=filename,
            content=content,
        )

        created_path = Path(project_file.storage_path)

        db.commit()
        db.refresh(project_file)

        return project_file

    except HTTPException:
        db.rollback()
        raise

    except ValueError as exc:
        db.rollback()

        if created_path is not None:
            cleanup_files([created_path])

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except FileExistsError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="File already exists",
        )

    except IntegrityError:
        db.rollback()

        if created_path is not None:
            cleanup_files([created_path])

        raise HTTPException(
            status_code=409,
            detail="A file with this name already exists",
        )

    except Exception:
        db.rollback()

        if created_path is not None:
            cleanup_files([created_path])

        raise

    finally:
        await file.close()


@router.post(
    "/upload-zip",
    response_model=list[ProjectFileResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_zip(
    project_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload and safely extract a ZIP archive."""

    created_paths: list[Path] = []
    archive_path: Path | None = None

    try:
        project = get_project(
            db,
            current_user.id,
            project_id,
        )

        if project is None:
            raise HTTPException(
                status_code=404,
                detail="Project not found",
            )

        if (
            not file.filename
            or not file.filename.lower().endswith(".zip")
        ):
            raise HTTPException(
                status_code=400,
                detail="A ZIP archive is required",
            )

        content = await read_upload(
            file,
            MAX_ARCHIVE_SIZE,
        )

        with NamedTemporaryFile(
            suffix=".zip",
            delete=False,
        ) as temporary:
            temporary.write(content)
            archive_path = Path(temporary.name)

        extracted = extract_zip_archive(
            archive_path,
            project_id,
        )

        created_paths = [
            storage_path
            for _, storage_path, _, _ in extracted
        ]

        extracted_paths = {
            relative_path
            for relative_path, _, _, _ in extracted
        }

        if len(extracted_paths) != len(extracted):
            raise ValueError(
                "Duplicate file paths in archive"
            )

        existing_paths = set(
            db.scalars(
                select(ProjectFile.file_path).where(
                    ProjectFile.project_id == project_id
                )
            ).all()
        )

        if existing_paths.intersection(extracted_paths):
            raise ValueError(
                "Archive contains existing project file paths"
            )

        records = []

        for (
            relative_path,
            storage_path,
            checksum,
            file_size,
        ) in extracted:

            record = ProjectFile(
                project_id=project_id,
                file_path=relative_path,
                storage_path=str(storage_path),
                file_name=Path(relative_path).name,
                file_extension=(
                    Path(relative_path).suffix.lower() or None
                ),
                mime_type=mimetypes.guess_type(
                    relative_path
                )[0],
                file_size=file_size,
                origin=FileOrigin.UPLOADED,
                checksum=checksum,
            )

            records.append(record)

        db.add_all(records)
        db.commit()

        for record in records:
            db.refresh(record)

        return records

    except HTTPException:
        db.rollback()
        cleanup_files(created_paths)
        raise

    except (ValueError, zipfile.BadZipFile) as exc:
        db.rollback()
        cleanup_files(created_paths)

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except IntegrityError:
        db.rollback()
        cleanup_files(created_paths)

        raise HTTPException(
            status_code=409,
            detail="Archive contains duplicate project file paths",
        )

    except Exception:
        db.rollback()
        cleanup_files(created_paths)
        raise

    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)

        await file.close()


@router.get(
    "",
    response_model=ProjectFileListResponse,
)
def get_files(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files belonging to an owned project."""

    try:
        return list_project_files(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
        )

    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )


@router.get("/{file_id}/download")
def download_file(
    project_id: UUID,
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download a file from an owned project."""

    try:
        result = get_project_file(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
            file_id=file_id,
        )

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid file storage path",
        )

    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Stored file not found",
        )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Project file not found",
        )

    project_file, storage_path = result

    return FileResponse(
        path=storage_path,
        media_type="application/octet-stream",
        filename=project_file.file_name,
    )


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_file(
    project_id: UUID,
    file_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Safely delete a file using filesystem staging and DB commit."""

    staged_path = None

    try:
        result = get_project_file(
            db=db,
            user_id=current_user.id,
            project_id=project_id,
            file_id=file_id,
        )

        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Project file not found",
            )

        project_file, storage_path = result

        project_directory = get_project_directory(project_id)

        # Stage the physical file before modifying the database.
        staged_path = stage_file_deletion(
            storage_path,
            project_directory,
        )

        # Delete the database record.
        db.delete(project_file)
        db.commit()

    except HTTPException:
        db.rollback()

        if staged_path is not None:
            try:
                restore_file_deletion(
                    staged_path,
                    storage_path,
                )
            except Exception:
                logger.exception(
                    "CRITICAL: Failed to restore staged file: %s",
                    file_id,
                )

        raise

    except Exception:
        db.rollback()

        if staged_path is not None:
            try:
                restore_file_deletion(
                    staged_path,
                    storage_path,
                )
            except Exception:
                logger.exception(
                    "CRITICAL: Failed to restore file after database failure: %s",
                    file_id,
                )

        raise

    # The database commit succeeded. Physical cleanup can now be finalized.
    try:
        finalize_file_deletion(
            staged_path,
            project_directory,
        )
    except OSError:
        logger.exception(
            "File record was deleted, but staged file cleanup failed: %s",
            file_id,
        )

    return None