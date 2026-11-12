import asyncio
import hashlib
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.verifying import (
    VerificationFinding,
    VerificationResult,
)
from app.database.connection import SessionLocal
from app.models.finding import (
    Finding,
    FindingSeverity,
    FindingStatus,
)
from app.models.project import Project, ProjectStatus, ProjectType
from app.models.project_file import FileOrigin, ProjectFile
from app.models.review import Review, ReviewStatus, ReviewType
from app.models.user import User
from app.services.file_storage import get_project_directory
from app.workflows import repository_review


def run_async(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def imported_repository():
    """
    Create a genuine uploaded project with actual files on disk
    and corresponding PostgreSQL records.
    """
    db = SessionLocal()
    unique_id = uuid.uuid4().hex

    project_id = None
    user_id = None
    project_directory = None

    try:
        user = User(
            email=f"e2e-review-{unique_id}@example.com",
            username=f"e2ereview_{unique_id[:20]}",
            hashed_password="test-only-password-hash",
        )

        db.add(user)
        db.flush()

        user_id = user.id

        project = Project(
            user_id=user.id,
            name=f"E2E Repository {unique_id[:8]}",
            project_type=ProjectType.UPLOADED,
            status=ProjectStatus.CREATED,
            technology_stack="Python",
        )

        db.add(project)
        db.flush()

        project_id = project.id

        project_directory = get_project_directory(project_id)
        project_directory.mkdir(parents=True, exist_ok=True)

        source_files = {
            "src/main.py": (
                "def get_user(user_id):\n"
                "    return user_id\n"
            ),
            "README.md": (
                "# Test Repository\n"
                "\n"
                "Repository review integration test.\n"
            ),
        }

        for relative_path, content in source_files.items():
            file_path = project_directory / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

            content_bytes = content.encode("utf-8")

            project_file = ProjectFile(
                project_id=project_id,
                file_path=relative_path,
                storage_path=str(file_path),
                file_name=Path(relative_path).name,
                file_extension=Path(relative_path).suffix,
                mime_type="text/plain",
                file_size=len(content_bytes),
                origin=FileOrigin.UPLOADED,
                checksum=hashlib.sha256(content_bytes).hexdigest(),
            )

            db.add(project_file)

        db.commit()

        yield {
            "project_id": project_id,
            "user_id": user_id,
            "directory": project_directory,
            "original_files": source_files,
        }

    finally:
        db.rollback()

        if project_id is not None:
            project = db.get(Project, project_id)

            if project is not None:
                db.delete(project)

        if user_id is not None:
            user = db.get(User, user_id)

            if user is not None:
                db.delete(user)

        db.commit()
        db.close()

        if project_directory is not None:
            shutil.rmtree(project_directory, ignore_errors=True)


def make_verification_result():
    finding = VerificationFinding(
        file_path="src/main.py",
        title="Missing input validation",
        description=(
            "The function accepts user input without validating it."
        ),
        severity="HIGH",
        category="SECURITY",
        line_number=1,
        suggested_fix="Validate user_id before using it.",
    )

    return VerificationResult(
        passed=False,
        summary="Verification identified one security finding.",
        findings=[finding],
        files_checked=2,
        checks_performed=[
            "File input validation",
            "Python syntax validation",
            "LLM-based source inspection",
        ],
    )


def make_review_result():
    return SimpleNamespace(
        model_dump=lambda: {
            "summary": (
                "One security finding requires user approval."
            ),
            "total_findings": 1,
            "critical_count": 0,
            "high_count": 1,
            "medium_count": 0,
            "low_count": 0,
            "requires_user_approval": True,
            "findings": [
                {
                    "file_path": "src/main.py",
                    "title": "Missing input validation",
                    "description": (
                        "The function accepts user input "
                        "without validating it."
                    ),
                    "severity": "HIGH",
                    "category": "SECURITY",
                    "line_number": 1,
                    "suggested_fix": (
                        "Validate user_id before using it."
                    ),
                    "recommended_action": (
                        "Request user approval before fixing."
                    ),
                }
            ],
        }
    )


def test_complete_repository_review_end_to_end(
    imported_repository,
    monkeypatch,
):
    """
    Exercise actual project loading, agent orchestration,
    PostgreSQL persistence, and file preservation.

    Only external agent responses are mocked.
    """
    project_id = imported_repository["project_id"]
    user_id = imported_repository["user_id"]
    project_directory = imported_repository["directory"]

    agent_calls = []

    async def mock_verification(**kwargs):
        agent_calls.append("VERIFYING")

        assert len(kwargs["files"]) == 2

        assert any(
            item["file_path"] == "src/main.py"
            for item in kwargs["files"]
        )

        assert kwargs["technology_stack"] == "Python"

        return make_verification_result()

    async def mock_review(verification_results):
        agent_calls.append("REVIEW")

        assert verification_results["passed"] is False
        assert len(verification_results["findings"]) == 1

        return make_review_result()

    monkeypatch.setattr(
        repository_review.verifying_agent,
        "verify_files",
        mock_verification,
    )

    monkeypatch.setattr(
        repository_review.review_agent,
        "review",
        mock_review,
    )

    result = run_async(
        repository_review.review_imported_project(
            user_id=user_id,
            project_id=project_id,
        )
    )

    # Verify agent execution order.
    assert agent_calls == ["VERIFYING", "REVIEW"]

    # Verify workflow result.
    assert result["project_id"] == str(project_id)
    assert result["workflow_status"] == "WAITING_FOR_APPROVAL"
    assert result["files_reviewed"] == 2
    assert result["binary_files_skipped"] == []

    # Verify persisted review information.
    assert result["persistence"]["review_number"] == 1
    assert result["persistence"]["total_findings"] == 1
    assert result["persistence"]["status"] == "COMPLETED"

    # Verify actual database records.
    db = SessionLocal()

    try:
        project = db.get(Project, project_id)

        review = db.scalar(
            select(Review).where(
                Review.project_id == project_id
            )
        )

        findings = db.scalars(
            select(Finding).where(
                Finding.project_id == project_id
            )
        ).all()

        assert project is not None
        assert project.status == ProjectStatus.REVIEWING

        assert review is not None
        assert review.review_type == ReviewType.INITIAL
        assert review.status == ReviewStatus.COMPLETED
        assert review.total_findings == 1

        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.HIGH
        assert findings[0].status == FindingStatus.OPEN

    finally:
        db.close()

    # Verify that the original repository files were not modified.
    for relative_path, original_content in (
        imported_repository["original_files"].items()
    ):
        actual_content = (
            project_directory / relative_path
        ).read_text(encoding="utf-8")

        assert actual_content == original_content


def test_repository_review_with_no_findings_end_to_end(
    imported_repository,
    monkeypatch,
):
    """
    Verify the successful no-findings path using real
    project files and PostgreSQL persistence.
    """
    project_id = imported_repository["project_id"]
    user_id = imported_repository["user_id"]

    agent_calls = []

    async def mock_verification(**kwargs):
        agent_calls.append("VERIFYING")

        return VerificationResult(
            passed=True,
            summary="No findings detected.",
            findings=[],
            files_checked=2,
            checks_performed=[
                "File input validation",
                "Python syntax validation",
            ],
        )

    async def unexpected_review(*args, **kwargs):
        agent_calls.append("REVIEW")

        raise AssertionError(
            "Review Agent must not run when no findings exist."
        )

    monkeypatch.setattr(
        repository_review.verifying_agent,
        "verify_files",
        mock_verification,
    )

    monkeypatch.setattr(
        repository_review.review_agent,
        "review",
        unexpected_review,
    )

    result = run_async(
        repository_review.review_imported_project(
            user_id=user_id,
            project_id=project_id,
        )
    )

    assert agent_calls == ["VERIFYING"]
    assert result["workflow_status"] == "COMPLETED"
    assert result["persistence"]["total_findings"] == 0

    db = SessionLocal()

    try:
        project = db.get(Project, project_id)

        review = db.scalar(
            select(Review).where(
                Review.project_id == project_id
            )
        )

        findings = db.scalars(
            select(Finding).where(
                Finding.project_id == project_id
            )
        ).all()

        assert project.status == ProjectStatus.COMPLETED

        assert review is not None
        assert review.review_type == ReviewType.INITIAL
        assert review.total_findings == 0

        assert findings == []

    finally:
        db.close()