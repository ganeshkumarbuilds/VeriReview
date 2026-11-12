import hashlib
import io
import shutil
import uuid
import zipfile

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import github_import
from app.api.routes import repository_review_api
from app.api.routes.auth import get_current_user
from app.database.connection import SessionLocal, get_db

from app.agents.verifying import (
    VerificationFinding,
    VerificationResult,
)

from app.models.finding import Finding, FindingSeverity, FindingStatus
from app.models.project import Project, ProjectStatus, ProjectType
from app.models.project_file import FileOrigin, ProjectFile
from app.models.review import Review, ReviewStatus, ReviewType
from app.models.user import User

from app.services.file_storage import get_project_directory
from app.workflows import repository_review


def make_repository_archive():
    """Create a genuine GitHub-style ZIP archive."""

    archive = io.BytesIO()

    source_files = {
        "demo-repository/src/main.py": (
            "def get_user(user_id):\n"
            "    return user_id\n"
        ),
        "demo-repository/README.md": (
            "# Demo Repository\n\n"
            "Imported through the GitHub integration test.\n"
        ),
    }

    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zip_file:
        for path, content in source_files.items():
            zip_file.writestr(path, content)

    return archive.getvalue(), source_files


def make_verification_result():
    finding = VerificationFinding(
        file_path="demo-repository/src/main.py",
        title="Missing input validation",
        description="The function accepts user input without validation.",
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
            "Python syntax validation",
            "Source inspection",
        ],
    )


def make_review_result():
    return SimpleNamespace(
        model_dump=lambda: {
            "summary": "One security finding requires user approval.",
            "total_findings": 1,
            "critical_count": 0,
            "high_count": 1,
            "medium_count": 0,
            "low_count": 0,
            "requires_user_approval": True,
            "findings": [
                {
                    "file_path": "demo-repository/src/main.py",
                    "title": "Missing input validation",
                    "description": (
                        "The function accepts user input "
                        "without validation."
                    ),
                    "severity": "HIGH",
                    "category": "SECURITY",
                    "line_number": 1,
                    "suggested_fix": "Validate user_id before using it.",
                    "recommended_action": (
                        "Request user approval before fixing."
                    ),
                }
            ],
        }
    )


@pytest.fixture
def github_review_environment(monkeypatch):
    """Set up real PostgreSQL, real storage, and a test FastAPI app."""

    db = SessionLocal()
    unique_id = uuid.uuid4().hex

    user_id = None
    project_id = None
    project_directory = None

    try:
        user = User(
            email=f"github-review-{unique_id}@example.com",
            username=f"githubreview_{unique_id[:20]}",
            hashed_password="test-only-password-hash",
        )

        db.add(user)
        db.flush()

        user_id = user.id

        project = Project(
            user_id=user.id,
            name=f"GitHub Integration {unique_id[:8]}",
            project_type=ProjectType.UPLOADED,
            status=ProjectStatus.CREATED,
            technology_stack="Python",
        )

        db.add(project)
        db.commit()

        project_id = project.id
        project_directory = get_project_directory(project_id)

        archive_content, expected_files = make_repository_archive()

        def github_handler(request):
            if request.url.host == "api.github.com":
                return httpx.Response(
                    200,
                    json={
                        "private": False,
                        "archived": False,
                        "default_branch": "main",
                    },
                )

            if request.url.host == "codeload.github.com":
                return httpx.Response(
                    200,
                    content=archive_content,
                    headers={"content-type": "application/zip"},
                )

            return httpx.Response(500)

        original_async_client = httpx.AsyncClient

        def mock_async_client(*args, **kwargs):
            return original_async_client(
                transport=httpx.MockTransport(github_handler),
                timeout=kwargs.get("timeout", 10.0),
                trust_env=False,
            )

        monkeypatch.setattr(
            github_import.httpx,
            "AsyncClient",
            mock_async_client,
        )

        agent_calls = []

        async def mock_verification(**kwargs):
            agent_calls.append("VERIFYING")

            assert len(kwargs["files"]) == 2
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

        app = FastAPI()

        app.include_router(github_import.router)
        app.include_router(repository_review_api.router)

        app.dependency_overrides[get_current_user] = (
            lambda: user
        )

        def override_get_db():
            session = SessionLocal()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as client:
            yield {
                "client": client,
                "user_id": user_id,
                "project_id": project_id,
                "directory": project_directory,
                "expected_files": expected_files,
                "agent_calls": agent_calls,
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


def test_github_import_then_repository_review_end_to_end(
    github_review_environment,
):
    """
    Exercise actual GitHub import and repository review endpoints.

    Uses real PostgreSQL, ZIP extraction, file storage,
    and review persistence. Only GitHub HTTP responses
    and external agent responses are mocked.
    """

    client = github_review_environment["client"]
    project_id = github_review_environment["project_id"]
    directory = github_review_environment["directory"]
    expected_files = github_review_environment["expected_files"]

    # 1. Import GitHub repository.

    import_response = client.post(
        f"/api/v1/projects/{project_id}/import-github",
        json={
            "repository_url": "https://github.com/example/demo-repository"
        },
    )

    assert import_response.status_code == 201

    import_body = import_response.json()

    assert import_body["repository"] == "example/demo-repository"
    assert import_body["default_branch"] == "main"
    assert import_body["imported_files"] == 2

    imported_paths = {
        item["file_path"]
        for item in import_body["files"]
    }

    assert imported_paths == set(expected_files)

    # 2. Verify actual extracted files.

    for relative_path in expected_files:
        actual_path = directory / relative_path

        assert actual_path.is_file()

        assert actual_path.read_text(
            encoding="utf-8"
        ) == expected_files[relative_path]

    # 3. Verify PostgreSQL ProjectFile records.

    db = SessionLocal()

    try:
        project_files = db.scalars(
            select(ProjectFile).where(
                ProjectFile.project_id == project_id
            )
        ).all()

        assert len(project_files) == 2

        for project_file in project_files:
            assert project_file.origin == FileOrigin.UPLOADED

            content = (
                directory / project_file.file_path
            ).read_bytes()

            assert project_file.checksum == hashlib.sha256(
                content
            ).hexdigest()

    finally:
        db.close()

    # 4. Start repository review.

    review_response = client.post(
        f"/api/v1/projects/{project_id}/review"
    )

    assert review_response.status_code == 202

    review_body = review_response.json()

    assert review_body["project_id"] == str(project_id)
    assert review_body["workflow_status"] == "QUEUED"

    # TestClient executes background tasks before returning.

    assert github_review_environment["agent_calls"] == [
        "VERIFYING",
        "REVIEW",
    ]

    # 5. Verify PostgreSQL review and finding records.

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

    # 6. Verify original imported files remain unchanged.

    for relative_path, expected_content in expected_files.items():
        actual_content = (
            directory / relative_path
        ).read_text(encoding="utf-8")

        assert actual_content == expected_content