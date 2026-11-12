import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agents.review import review_agent
from app.agents.verifying import verifying_agent
from app.database.connection import SessionLocal
from app.models.project import Project, ProjectStatus
from app.models.project_file import ProjectFile
from app.models.review import ReviewType
from app.services.file_storage import get_project_directory
from app.services.projects import get_project
from app.services.review_persistence import persist_review


logger = logging.getLogger(__name__)

MAX_REVIEW_FILES = 500
MAX_REVIEW_FILE_BYTES = 1024 * 1024
MAX_REVIEW_TOTAL_BYTES = 8 * 1024 * 1024


class RepositoryReviewError(Exception):
    """Raised when an imported repository cannot be reviewed."""


def _load_repository_context(
    user_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    """Load an owned project's files and read their actual contents."""

    db = SessionLocal()

    try:
        project = get_project(
            db=db,
            user_id=user_id,
            project_id=project_id,
        )

        if project is None:
            raise RepositoryReviewError("Project not found.")

        project_directory = get_project_directory(project_id)

        project_files = db.scalars(
            select(ProjectFile)
            .where(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.file_path.asc())
        ).all()

        if not project_files:
            raise RepositoryReviewError(
                "The project contains no imported files to review."
            )

        if len(project_files) > MAX_REVIEW_FILES:
            raise RepositoryReviewError(
                f"Project exceeds the {MAX_REVIEW_FILES}-file review limit."
            )

        files: list[dict[str, str]] = []
        skipped_binary_files: list[str] = []
        total_bytes = 0

        for project_file in project_files:
            stored_path = Path(project_file.storage_path)

            if stored_path.is_symlink() or not stored_path.is_file():
                raise RepositoryReviewError(
                    f"Project file is missing or unsafe: "
                    f"{project_file.file_path}"
                )

            resolved_path = stored_path.resolve()

            if not resolved_path.is_relative_to(project_directory):
                raise RepositoryReviewError(
                    f"Project file escapes its storage directory: "
                    f"{project_file.file_path}"
                )

            file_size = resolved_path.stat().st_size

            if file_size > MAX_REVIEW_FILE_BYTES:
                raise RepositoryReviewError(
                    f"File exceeds the 1 MB review limit: "
                    f"{project_file.file_path}"
                )

            total_bytes += file_size

            if total_bytes > MAX_REVIEW_TOTAL_BYTES:
                raise RepositoryReviewError(
                    "Project exceeds the 8 MB total review input limit."
                )

            raw_content = resolved_path.read_bytes()

            try:
                text_content = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                skipped_binary_files.append(project_file.file_path)
                continue

            files.append({
                "file_path": project_file.file_path,
                "content": text_content,
            })

        if not files:
            raise RepositoryReviewError(
                "No UTF-8 text files were found in this project."
            )

        return {
            "project_id": project.id,
            "project_name": project.name,
            "technology_stack": project.technology_stack or "",
            "files": files,
            "skipped_binary_files": skipped_binary_files,
        }

    finally:
        db.close()


def _persist_repository_review(
    project_id: UUID,
    verification_results: dict[str, Any],
    review_data: dict[str, Any],
) -> dict[str, Any]:
    """Persist the INITIAL review and mark the project status."""

    db = SessionLocal()

    try:
        review = persist_review(
            db=db,
            project_id=project_id,
            verification_results=verification_results,
            review_data=review_data,
            review_type=ReviewType.INITIAL,
        )

        project = db.get(Project, project_id)

        if project is None:
            raise RepositoryReviewError(
                "Project disappeared while saving its review."
            )

        project.status = (
            ProjectStatus.COMPLETED
            if verification_results["passed"]
            else ProjectStatus.REVIEWING
        )

        db.commit()

        return {
            "review_id": str(review.id),
            "review_number": review.review_number,
            "total_findings": review.total_findings,
            "status": review.status.value,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _mark_project_failed(project_id: UUID) -> None:
    """Persist a failed review workflow without hiding the original error."""

    db = SessionLocal()

    try:
        project = db.get(Project, project_id)

        if project is not None:
            project.status = ProjectStatus.FAILED
            db.commit()

    except Exception:
        db.rollback()
        logger.exception(
            "Could not mark repository review as failed: %s",
            project_id,
        )

    finally:
        db.close()


async def review_imported_project(
    user_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    """
    Review an imported project's actual stored files.

    Workflow:
        1. Confirm project ownership and load actual files.
        2. Run the Verifying Agent.
        3. Run the Review Agent when findings exist.
        4. Persist an INITIAL review and its findings.
        5. Never invoke the Coding Agent or modify project files.
    """

    try:
        context = await asyncio.to_thread(
            _load_repository_context,
            user_id,
            project_id,
        )

        db = SessionLocal()

        try:
            project = get_project(
                db=db,
                user_id=user_id,
                project_id=project_id,
            )

            if project is None:
                raise RepositoryReviewError("Project not found.")

            project.status = ProjectStatus.VERIFYING
            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

        verification_result = await verifying_agent.verify_files(
            files=context["files"],
            technology_stack=context["technology_stack"],
            test_results=None,
        )

        verification_results = verification_result.model_dump()

        findings = verification_results.get("findings", [])

        if findings:
            review_result = await review_agent.review(
                verification_results
            )
            review_data = review_result.model_dump()
        else:
            review_data = {
                "summary": (
                    "Verification completed without reported findings. "
                    "This does not guarantee the absence of defects."
                ),
                "total_findings": 0,
                "critical_count": 0,
                "high_count": 0,
                "medium_count": 0,
                "low_count": 0,
                "findings": [],
                "requires_user_approval": False,
            }

        persisted_review = await asyncio.to_thread(
            _persist_repository_review,
            project_id,
            verification_results,
            review_data,
        )

        return {
            "project_id": str(project_id),
            "project_name": context["project_name"],
            "workflow_status": (
                "COMPLETED"
                if verification_results["passed"]
                else "WAITING_FOR_APPROVAL"
            ),
            "verification": verification_results,
            "review": review_data,
            "persistence": persisted_review,
            "files_reviewed": len(context["files"]),
            "binary_files_skipped": context["skipped_binary_files"],
        }

    except Exception:
        logger.exception(
            "Repository review failed: project=%s",
            project_id,
        )
        await asyncio.to_thread(
            _mark_project_failed,
            project_id,
        )
        raise
