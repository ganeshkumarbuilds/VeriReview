import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.agents.coding import coding_agent
from app.agents.review import review_agent
from app.agents.verifying import verifying_agent
from app.database.connection import SessionLocal
from app.models.finding import Finding, FindingStatus
from app.models.fix_request import FixRequest, FixRequestStatus
from app.models.project import Project
from app.models.project_file import ProjectFile
from app.models.review import ReviewType
from app.services.generated_files import update_generated_file
from app.services.fix_requests import (
    complete_fix_request,
    fail_fix_request,
    start_fix_request,
)
from app.services.review_persistence import persist_review


logger = logging.getLogger(__name__)


class FixExecutionError(Exception):
    """Base exception for approved fix execution errors."""


class FixApprovalError(FixExecutionError):
    """Raised when a fix has not been explicitly approved."""


class FixFileError(FixExecutionError):
    """Raised when the target file cannot be accessed."""


class FixVerificationError(FixExecutionError):
    """Raised when the updated file does not pass verification."""


def _load_fix_context(
    project_id: UUID,
    fix_request_id: UUID,
) -> dict[str, Any]:
    db = SessionLocal()

    try:
        fix_request = db.scalar(
            select(FixRequest).where(
                FixRequest.id == fix_request_id,
                FixRequest.project_id == project_id,
            )
        )

        if fix_request is None:
            raise FixExecutionError("Fix request not found.")

        if fix_request.approved_at is None:
            raise FixApprovalError(
                "Explicit user approval is required."
            )

        if fix_request.status != FixRequestStatus.REQUESTED:
            raise FixExecutionError(
                "Fix request is not in REQUESTED status."
            )

        finding = db.scalar(
            select(Finding).where(
                Finding.id == fix_request.finding_id,
                Finding.project_id == project_id,
            )
        )

        if finding is None:
            raise FixExecutionError("Finding not found.")

        if finding.status != FindingStatus.OPEN:
            raise FixExecutionError(
                "Only open findings can be fixed."
            )

        project = db.get(Project, project_id)

        if project is None:
            raise FixExecutionError("Project not found.")

        project_file = db.scalar(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id,
                ProjectFile.file_path == finding.file_path,
            )
        )

        if project_file is None:
            raise FixFileError(
                f"Project file not found: {finding.file_path}"
            )

        return {
            "fix_request_id": fix_request.id,
            "finding_id": finding.id,
            "project_id": project.id,
            "file_path": finding.file_path,
            "title": finding.title,
            "description": finding.description,
            "severity": finding.severity.value,
            "category": finding.category.value,
            "line_number": finding.line_number,
            "code_snippet": finding.code_snippet,
            "suggested_fix": finding.suggested_fix,
            "user_instruction": fix_request.user_instruction,
            "requirements": project.description or project.name,
            "technology_stack": project.technology_stack or "",
            "storage_path": project_file.storage_path,
        }

    finally:
        db.close()


def _read_file(storage_path: str) -> str:
    path = Path(storage_path)

    if not path.is_file():
        raise FixFileError(
            "The target project file does not exist."
        )

    if path.is_symlink():
        raise FixFileError(
            "Symbolic links cannot be modified."
        )

    try:
        return path.read_text(encoding="utf-8")

    except (OSError, UnicodeDecodeError) as exc:
        raise FixFileError(
            "Unable to read the target project file as UTF-8."
        ) from exc


def _start_request(
    project_id: UUID,
    fix_request_id: UUID,
) -> None:
    db = SessionLocal()

    try:
        start_fix_request(
            db=db,
            project_id=project_id,
            fix_request_id=fix_request_id,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _publish_replacement(
    user_id: UUID,
    project_id: UUID,
    file_path: str,
    content: str,
) -> None:
    db = SessionLocal()

    try:
        update_generated_file(
            db=db,
            user_id=user_id,
            project_id=project_id,
            file_path=file_path,
            content=content.encode("utf-8"),
            approved=True,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _restore_original(
    user_id: UUID,
    project_id: UUID,
    file_path: str,
    original_content: str,
) -> None:
    """Restore the original content after a failed fix workflow."""

    db = SessionLocal()

    try:
        update_generated_file(
            db=db,
            user_id=user_id,
            project_id=project_id,
            file_path=file_path,
            content=original_content.encode("utf-8"),
            approved=True,
        )

        db.commit()

        logger.info(
            "Restored original file after failed fix: %s",
            file_path,
        )

    except Exception:
        db.rollback()

        logger.critical(
            "CRITICAL: Could not restore original file: %s",
            file_path,
            exc_info=True,
        )

        raise

    finally:
        db.close()


def _verify_replacement(
    file_path: str,
    content: str,
    technology_stack: str,
) -> dict[str, Any]:
    verification_file = {
        "file_path": file_path,
        "content": content,
    }

    return asyncio.run(
        verifying_agent.verify_files(
            files=[verification_file],
            technology_stack=technology_stack,
            test_results=None,
        )
    )


def _run_review_agent(
    verification_results: dict[str, Any],
) -> dict[str, Any]:
    """Run the Review Agent against verified findings."""

    result = asyncio.run(
        review_agent.review(verification_results)
    )

    if not hasattr(result, "model_dump"):
        raise FixExecutionError(
            "Review Agent returned an invalid result."
        )

    review_data = result.model_dump()

    if not isinstance(review_data, dict):
        raise FixExecutionError(
            "Review Agent returned an invalid review report."
        )

    return review_data


def _build_empty_review() -> dict[str, Any]:
    """Build a no-findings report without unnecessary LLM calls."""

    return {
        "summary": (
            "Post-fix verification completed successfully. "
            "No remaining findings were reported."
        ),
        "total_findings": 0,
        "critical_count": 0,
        "high_count": 0,
        "medium_count": 0,
        "low_count": 0,
        "requires_user_approval": False,
        "findings": [],
    }


def _persist_post_fix_review(
    project_id: UUID,
    finding_id: UUID,
    verification_results: dict[str, Any],
) -> dict[str, Any]:
    """
    Generate and persist the post-fix review.

    The Verifying Agent remains authoritative for finding
    identity and severity. The Review Agent provides the
    explanation and recommended actions.
    """

    if hasattr(verification_results, "model_dump"):
        verification_results = verification_results.model_dump()

    if not isinstance(verification_results, dict):
        raise FixVerificationError(
            "Verification returned an invalid result."
        )

    findings = verification_results.get("findings")

    if not isinstance(findings, list):
        raise FixVerificationError(
            "Verification findings must be a list."
        )

    passed = verification_results.get("passed")

    if not isinstance(passed, bool):
        raise FixVerificationError(
            "Verification returned an invalid passed value."
        )

    normalized_findings = []

    for finding in findings:
        if hasattr(finding, "model_dump"):
            finding = finding.model_dump()

        if not isinstance(finding, dict):
            raise FixVerificationError(
                "Verification returned an invalid finding."
            )

        normalized_findings.append(finding)

    verification_results = {
        **verification_results,
        "findings": normalized_findings,
    }

    if not normalized_findings:
        if not passed:
            raise FixVerificationError(
                "Verification failed without reporting findings."
            )

        review_data = _build_empty_review()

    else:
        if passed:
            raise FixVerificationError(
                "Verification cannot pass while findings remain."
            )

        review_data = _run_review_agent(
            verification_results
        )

        if review_data.get("total_findings") != len(
            normalized_findings
        ):
            raise FixExecutionError(
                "Review Agent changed the finding count."
            )

        if review_data.get("requires_user_approval") is not True:
            raise FixExecutionError(
                "Review Agent must require explicit user approval."
            )

    db = SessionLocal()

    try:
        review = persist_review(
            db=db,
            project_id=project_id,
            verification_results=verification_results,
            review_data=review_data,
            review_type=ReviewType.POST_FIX,
        )

        original_finding = db.scalar(
            select(Finding)
            .where(
                Finding.id == finding_id,
                Finding.project_id == project_id,
            )
            .with_for_update()
        )

        if original_finding is not None:
            remaining_identity = any(
                item.get("file_path") == original_finding.file_path
                and item.get("title") == original_finding.title
                and item.get("line_number")
                == original_finding.line_number
                for item in normalized_findings
            )

            if not remaining_identity and passed:
                original_finding.status = FindingStatus.FIXED

        db.commit()

        return {
            "review_id": str(review.id),
            "review_number": review.review_number,
            "total_findings": review.total_findings,
            "passed": passed,
            "summary": review_data["summary"],
            "requires_user_approval": review_data[
                "requires_user_approval"
            ],
            "findings": review_data["findings"],
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _complete_request(
    project_id: UUID,
    fix_request_id: UUID,
) -> None:
    db = SessionLocal()

    try:
        complete_fix_request(
            db=db,
            project_id=project_id,
            fix_request_id=fix_request_id,
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _fail_request(
    project_id: UUID,
    fix_request_id: UUID,
    error_message: str,
) -> None:
    db = SessionLocal()

    try:
        fix_request = db.scalar(
            select(FixRequest)
            .where(
                FixRequest.id == fix_request_id,
                FixRequest.project_id == project_id,
            )
            .with_for_update()
        )

        if (
            fix_request is not None
            and fix_request.status == FixRequestStatus.IN_PROGRESS
        ):
            fail_fix_request(
                db=db,
                project_id=project_id,
                fix_request_id=fix_request_id,
                error_message=error_message,
            )

        db.commit()

    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist fix failure."
        )

    finally:
        db.close()


async def execute_approved_fix(
    user_id: UUID,
    project_id: UUID,
    fix_request_id: UUID,
) -> dict[str, Any]:
    """
    Execute one explicitly approved fix.

    Workflow:
        1. Validate approval.
        2. Mark request IN_PROGRESS.
        3. Read the original project file.
        4. Generate a complete replacement.
        5. Publish the replacement.
        6. Verify the replacement.
        7. Generate a Review Agent report.
        8. Persist the POST_FIX review.
        9. Complete the fix request.

    If a failure occurs after publication, attempt to restore
    the original file content.
    """

    started = False
    replacement_published = False
    original_content = None
    context = None

    try:
        context = await asyncio.to_thread(
            _load_fix_context,
            project_id,
            fix_request_id,
        )

        await asyncio.to_thread(
            _start_request,
            project_id,
            fix_request_id,
        )

        started = True

        original_content = await asyncio.to_thread(
            _read_file,
            context["storage_path"],
        )

        finding_data = {
            "title": context["title"],
            "description": context["description"],
            "severity": context["severity"],
            "category": context["category"],
            "line_number": context["line_number"],
            "code_snippet": context["code_snippet"],
            "suggested_fix": context["suggested_fix"],
        }

        generated_file = await coding_agent.generate_fix(
            requirements=context["requirements"],
            technology_stack=context["technology_stack"],
            file_path=context["file_path"],
            original_content=original_content,
            finding=finding_data,
            user_instruction=context["user_instruction"],
        )

        if generated_file.file_path != context["file_path"]:
            raise FixExecutionError(
                "Coding Agent returned an unexpected file path."
            )

        if not generated_file.content.strip():
            raise FixExecutionError(
                "Coding Agent returned empty replacement content."
            )

        await asyncio.to_thread(
            _publish_replacement,
            user_id,
            project_id,
            context["file_path"],
            generated_file.content,
        )

        replacement_published = True

        verification_results = await asyncio.to_thread(
            _verify_replacement,
            context["file_path"],
            generated_file.content,
            context["technology_stack"],
        )

        if hasattr(verification_results, "model_dump"):
            verification_results = verification_results.model_dump()

        if not isinstance(verification_results, dict):
            raise FixVerificationError(
                "Verifying Agent returned an invalid result."
            )

        if not verification_results.get("passed", False):
            raise FixVerificationError(
                "Updated file did not pass verification."
            )

        review_result = await asyncio.to_thread(
            _persist_post_fix_review,
            project_id,
            context["finding_id"],
            verification_results,
        )

        await asyncio.to_thread(
            _complete_request,
            project_id,
            fix_request_id,
        )

        return {
            "fix_request_id": str(fix_request_id),
            "project_id": str(project_id),
            "finding_id": str(context["finding_id"]),
            "file_path": context["file_path"],
            "status": "COMPLETED",
            "verification": verification_results,
            "review": review_result,
        }

    except Exception as exc:
        logger.exception(
            "Approved fix execution failed: project=%s request=%s",
            project_id,
            fix_request_id,
        )

        if replacement_published and context is not None:
            try:
                await asyncio.to_thread(
                    _restore_original,
                    user_id,
                    project_id,
                    context["file_path"],
                    original_content,
                )

            except Exception:
                logger.critical(
                    "Manual recovery may be required for project=%s file=%s",
                    project_id,
                    context["file_path"],
                    exc_info=True,
                )

        if started:
            await asyncio.to_thread(
                _fail_request,
                project_id,
                fix_request_id,
                str(exc),
            )

        if isinstance(exc, FixExecutionError):
            raise

        raise FixExecutionError(
            "Approved fix execution failed."
        ) from exc