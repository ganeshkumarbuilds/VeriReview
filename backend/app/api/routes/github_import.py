import asyncio
import mimetypes
import re
import tempfile
import zipfile

from pathlib import Path
from urllib.parse import quote, urlparse
from uuid import UUID

import httpx

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.project import ProjectType
from app.models.project_file import FileOrigin, ProjectFile
from app.models.user import User
from app.services.file_storage import (
    MAX_ARCHIVE_SIZE,
    extract_zip_archive,
)
from app.services.projects import get_project


router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["GitHub Import"],
)

GITHUB_API = "https://api.github.com"
GITHUB_WEB = "https://github.com"

MAX_GITHUB_ARCHIVE_SIZE = MAX_ARCHIVE_SIZE
MAX_BRANCH_NAME_LENGTH = 255

DOWNLOAD_CHUNK_SIZE = 1024 * 1024

HTTP_TIMEOUT = httpx.Timeout(
    60.0,
    connect=10.0,
)


class GitHubImportRequest(BaseModel):
    repository_url: str = Field(
        min_length=1,
        max_length=500,
    )


class GitHubImportResponse(BaseModel):
    repository: str
    default_branch: str
    imported_files: int
    files: list[dict[str, str | int | None]]


def parse_github_repository_url(
    repository_url: str,
) -> tuple[str, str]:
    """Accept only a public GitHub repository root URL."""

    try:
        parsed = urlparse(repository_url.strip())
    except ValueError as exc:
        raise ValueError(
            "Invalid GitHub repository URL."
        ) from exc

    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Provide a valid HTTPS github.com repository URL."
        )

    parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    if len(parts) != 2:
        raise ValueError(
            "Use a repository URL in the form "
            "https://github.com/owner/repository."
        )

    owner, repository = parts

    repository = repository.removesuffix(".git")

    component_pattern = re.compile(
        r"^[A-Za-z0-9_.-]{1,100}$"
    )

    if (
        not component_pattern.fullmatch(owner)
        or not component_pattern.fullmatch(repository)
    ):
        raise ValueError(
            "The GitHub owner or repository name is invalid."
        )

    if owner in {".", ".."} or repository in {".", ".."}:
        raise ValueError(
            "The GitHub repository URL is invalid."
        )

    return owner, repository


async def _download_repository_archive(
    client: httpx.AsyncClient,
    owner: str,
    repository: str,
) -> tuple[bytes, str]:
    """Resolve public repository metadata and download its ZIP."""

    metadata_url = (
        f"{GITHUB_API}/repos/{owner}/{repository}"
    )

    try:
        metadata_response = await client.get(
            metadata_url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to GitHub.",
        ) from exc

    if metadata_response.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "GitHub repository was not found "
                "or is not public."
            ),
        )

    if metadata_response.status_code == 403:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "GitHub rate limit reached. "
                "Try again later."
            ),
        )

    if metadata_response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "GitHub could not provide repository metadata."
            ),
        )

    try:
        metadata = metadata_response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned invalid repository metadata.",
        ) from exc

    if not isinstance(metadata, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned invalid repository metadata.",
        )

    if (
        metadata.get("private") is True
        or metadata.get("archived") is True
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Private or archived repositories "
                "cannot be imported."
            ),
        )

    default_branch = metadata.get("default_branch")

    if (
        not isinstance(default_branch, str)
        or not default_branch
        or len(default_branch) > MAX_BRANCH_NAME_LENGTH
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub returned invalid repository metadata.",
        )

    # Encode special characters while preserving branch separators.
    encoded_branch = quote(
        default_branch,
        safe="/",
    )

    archive_url = (
        f"https://codeload.github.com/{owner}/{repository}"
        f"/zip/refs/heads/{encoded_branch}"
    )

    try:
        async with client.stream(
            "GET",
            archive_url,
            headers={
                "Accept": "application/zip",
            },
            follow_redirects=False,
        ) as response:

            if response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(
                        "The repository's default branch "
                        "archive was not found."
                    ),
                )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="GitHub archive download failed.",
                )

            content_length = response.headers.get(
                "content-length"
            )

            if content_length:
                try:
                    if int(content_length) > MAX_GITHUB_ARCHIVE_SIZE:
                        raise HTTPException(
                            status_code=(
                                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                            ),
                            detail=(
                                "GitHub repository archive "
                                "exceeds the 100 MB limit."
                            ),
                        )

                except ValueError:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="GitHub returned an invalid archive size.",
                    )

            archive = bytearray()

            async for chunk in response.aiter_bytes(
                DOWNLOAD_CHUNK_SIZE
            ):
                archive.extend(chunk)

                if len(archive) > MAX_GITHUB_ARCHIVE_SIZE:
                    raise HTTPException(
                        status_code=(
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                        ),
                        detail=(
                            "GitHub repository archive "
                            "exceeds the 100 MB limit."
                        ),
                    )

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not download the GitHub repository archive."
            ),
        ) from exc

    return bytes(archive), default_branch


@router.post(
    "/import-github",
    response_model=GitHubImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_github_repository(
    project_id: UUID,
    payload: GitHubImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitHubImportResponse:
    """
    Import a public GitHub repository into an owned
    uploaded VeriReview project.
    """

    created_paths: list[Path] = []
    archive_path: Path | None = None

    project = get_project(
        db,
        current_user.id,
        project_id,
    )

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    # GitHub imports are only permitted for uploaded projects.
    if project.project_type != ProjectType.UPLOADED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "GitHub repositories can only be imported "
                "into uploaded projects."
            ),
        )

    try:
        owner, repository = parse_github_repository_url(
            payload.repository_url
        )

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            trust_env=False,
        ) as client:

            archive_content, default_branch = (
                await _download_repository_archive(
                    client,
                    owner,
                    repository,
                )
            )

        with tempfile.NamedTemporaryFile(
            suffix=".zip",
            delete=False,
        ) as temporary:

            temporary.write(archive_content)

            archive_path = Path(temporary.name)

        extracted = await asyncio.to_thread(
            extract_zip_archive,
            archive_path,
            project_id,
        )

        created_paths = [
            item[1]
            for item in extracted
        ]

        imported_paths = [
            item[0]
            for item in extracted
        ]

        if not imported_paths:
            raise ValueError(
                "The GitHub repository contains no importable files."
            )

        existing_paths = db.scalars(
            select(ProjectFile.file_path).where(
                ProjectFile.project_id == project_id
            )
        ).all()

        existing_keys = {
            path.casefold()
            for path in existing_paths
        }

        imported_keys = [
            path.casefold()
            for path in imported_paths
        ]

        if len(imported_keys) != len(set(imported_keys)):
            raise ValueError(
                "Repository contains duplicate file paths."
            )

        if existing_keys.intersection(imported_keys):
            raise FileExistsError(
                "Repository contains paths that already "
                "exist in this project."
            )

        records: list[ProjectFile] = []

        response_files: list[
            dict[str, str | int | None]
        ] = []

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
                    Path(relative_path).suffix.lower()
                    or None
                ),
                mime_type=mimetypes.guess_type(
                    relative_path
                )[0],
                file_size=file_size,
                origin=FileOrigin.UPLOADED,
                checksum=checksum,
            )

            records.append(record)

            response_files.append(
                {
                    "file_path": relative_path,
                    "file_size": file_size,
                    "checksum": checksum,
                }
            )

        db.add_all(records)

        db.commit()

        return GitHubImportResponse(
            repository=f"{owner}/{repository}",
            default_branch=default_branch,
            imported_files=len(records),
            files=response_files,
        )

    except HTTPException:
        db.rollback()

        for path in reversed(created_paths):
            path.unlink(missing_ok=True)

        raise

    except (ValueError, zipfile.BadZipFile) as exc:
        db.rollback()

        for path in reversed(created_paths):
            path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except FileExistsError as exc:
        db.rollback()

        for path in reversed(created_paths):
            path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except IntegrityError as exc:
        db.rollback()

        for path in reversed(created_paths):
            path.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Repository files conflict with "
                "existing project files."
            ),
        ) from exc

    except Exception:
        db.rollback()

        for path in reversed(created_paths):
            path.unlink(missing_ok=True)

        raise

    finally:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)