import uuid

import pytest
from sqlalchemy import select

from app.database.connection import SessionLocal
from app.models.finding import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)
from app.models.project import Project, ProjectStatus, ProjectType
from app.models.review import Review, ReviewStatus, ReviewType
from app.models.user import User
from app.workflows.repository_review import (
    _persist_repository_review,
)


@pytest.fixture
def persisted_project():
    """
    Create a committed project so the repository-review function,
    which opens its own SessionLocal session, can access it.
    """
    db = SessionLocal()
    unique_id = uuid.uuid4().hex

    user = User(
        email=f"repository-persist-{unique_id}@example.com",
        username=f"repopersist_{unique_id[:20]}",
        hashed_password="test-only-password-hash",
    )

    try:
        db.add(user)
        db.flush()

        project = Project(
            user_id=user.id,
            name=f"Repository Persistence {unique_id[:8]}",
            project_type=ProjectType.UPLOADED,
            status=ProjectStatus.VERIFYING,
            technology_stack="Python",
        )

        db.add(project)
        db.commit()

        project_id = project.id
        user_id = user.id

        yield project_id

    finally:
        db.rollback()

        if "project_id" in locals():
            project_to_delete = db.get(Project, project_id)
            if project_to_delete is not None:
                db.delete(project_to_delete)

        if "user_id" in locals():
            user_to_delete = db.get(User, user_id)
            if user_to_delete is not None:
                db.delete(user_to_delete)

        db.commit()
        db.close()


def make_verification_results(findings=None, passed=False):
    if findings is None:
        findings = []

    return {
        "passed": passed,
        "summary": (
            "Verification completed."
            if not findings
            else "Verification detected findings."
        ),
        "files_checked": 2,
        "checks_performed": [
            "Source inspection",
            "Configuration validation",
        ],
        "findings": findings,
    }


def make_review_data(findings=None):
    if findings is None:
        findings = []

    counts = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
    }

    reviewed_findings = []

    for finding in findings:
        severity = finding["severity"].upper()

        if severity == "INFO":
            severity = "LOW"

        counts[severity] += 1

        reviewed_findings.append({
            **finding,
            "severity": severity,
            "recommended_action": "Request user approval.",
        })

    return {
        "summary": (
            "No findings detected."
            if not findings
            else "Repository review identified findings."
        ),
        "total_findings": len(reviewed_findings),
        "critical_count": counts["CRITICAL"],
        "high_count": counts["HIGH"],
        "medium_count": counts["MEDIUM"],
        "low_count": counts["LOW"],
        "requires_user_approval": bool(reviewed_findings),
        "findings": reviewed_findings,
    }


def make_security_finding():
    return {
        "file_path": "src/database.py",
        "title": "Potential SQL injection",
        "description": (
            "User-controlled input is directly interpolated into SQL."
        ),
        "severity": "HIGH",
        "category": "SECURITY",
        "line_number": 24,
        "suggested_fix": (
            "Use parameterized SQL queries."
        ),
    }


def test_persist_repository_review_saves_review_and_findings(
    persisted_project,
):
    finding = make_security_finding()

    verification = make_verification_results(
        findings=[finding],
        passed=False,
    )

    review_data = make_review_data([finding])

    result = _persist_repository_review(
        project_id=persisted_project,
        verification_results=verification,
        review_data=review_data,
    )

    assert result["total_findings"] == 1
    assert result["review_number"] == 1
    assert result["status"] == ReviewStatus.COMPLETED.value

    db = SessionLocal()

    try:
        project = db.get(Project, persisted_project)

        review = db.scalar(
            select(Review).where(
                Review.id == uuid.UUID(result["review_id"])
            )
        )

        findings = db.scalars(
            select(Finding).where(
                Finding.review_id == review.id
            )
        ).all()

        assert project.status == ProjectStatus.REVIEWING

        assert review is not None
        assert review.review_type == ReviewType.INITIAL
        assert review.status == ReviewStatus.COMPLETED
        assert review.total_findings == 1
        assert review.high_count == 1

        assert len(findings) == 1

        saved_finding = findings[0]

        assert saved_finding.title == "Potential SQL injection"
        assert saved_finding.severity == FindingSeverity.HIGH
        assert saved_finding.category == FindingCategory.SECURITY
        assert saved_finding.status == FindingStatus.OPEN
        assert saved_finding.is_auto_fixable is True

    finally:
        db.close()


def test_persist_repository_review_without_findings(
    persisted_project,
):
    verification = make_verification_results(
        findings=[],
        passed=True,
    )

    review_data = make_review_data([])

    result = _persist_repository_review(
        project_id=persisted_project,
        verification_results=verification,
        review_data=review_data,
    )

    assert result["total_findings"] == 0
    assert result["review_number"] == 1
    assert result["status"] == ReviewStatus.COMPLETED.value

    db = SessionLocal()

    try:
        project = db.get(Project, persisted_project)

        review = db.scalar(
            select(Review).where(
                Review.id == uuid.UUID(result["review_id"])
            )
        )

        findings = db.scalars(
            select(Finding).where(
                Finding.review_id == review.id
            )
        ).all()

        assert project.status == ProjectStatus.COMPLETED

        assert review is not None
        assert review.review_type == ReviewType.INITIAL
        assert review.total_findings == 0

        assert findings == []

    finally:
        db.close()


def test_persist_repository_review_commits_project_status(
    persisted_project,
):
    """
    Verify that the project status change is committed and visible
    from a completely separate database session.
    """
    verification = make_verification_results(
        findings=[],
        passed=True,
    )

    review_data = make_review_data([])

    _persist_repository_review(
        project_id=persisted_project,
        verification_results=verification,
        review_data=review_data,
    )

    db = SessionLocal()

    try:
        project = db.get(Project, persisted_project)

        assert project is not None
        assert project.status == ProjectStatus.COMPLETED

    finally:
        db.close()


def test_persist_repository_review_creates_initial_review(
    persisted_project,
):
    verification = make_verification_results(
        findings=[],
        passed=True,
    )

    review_data = make_review_data([])

    result = _persist_repository_review(
        project_id=persisted_project,
        verification_results=verification,
        review_data=review_data,
    )

    db = SessionLocal()

    try:
        review = db.scalar(
            select(Review).where(
                Review.project_id == persisted_project
            )
        )

        assert review is not None
        assert review.id == uuid.UUID(result["review_id"])
        assert review.review_type == ReviewType.INITIAL
        assert review.review_number == 1

    finally:
        db.close()