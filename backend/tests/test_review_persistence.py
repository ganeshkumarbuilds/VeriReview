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
from app.services.review_persistence import (
    ReviewPersistenceError,
    persist_review,
)


@pytest.fixture
def db_session():
    db = SessionLocal()
    transaction = db.begin()

    try:
        yield db
    finally:
        transaction.rollback()
        db.close()


@pytest.fixture
def test_project(db_session):
    unique_id = uuid.uuid4().hex

    user = User(
        email=f"review-test-{unique_id}@example.com",
        username=f"revtest_{unique_id[:20]}",
        hashed_password="test-only-password-hash",
    )

    db_session.add(user)
    db_session.flush()

    project = Project(
        user_id=user.id,
        name=f"Review Test {unique_id[:8]}",
        project_type=ProjectType.GENERATED,
        status=ProjectStatus.REVIEWING,
        technology_stack="Python",
    )

    db_session.add(project)
    db_session.flush()

    return project


def make_verification_findings():
    return [
        {
            "file_path": "src/main.py",
            "title": "SQL injection vulnerability",
            "description": "User input is interpolated into SQL.",
            "severity": "HIGH",
            "category": "SECURITY",
            "line_number": 12,
            "suggested_fix": "Use parameterized queries.",
        },
        {
            "file_path": "src/config.py",
            "title": "Missing configuration validation",
            "description": "Required configuration is not validated.",
            "severity": "INFO",
            "category": "CONFIGURATION",
            "line_number": 8,
            "suggested_fix": "Validate required settings.",
        },
    ]


def make_review_data(findings):
    reviewed = []

    for finding in findings:
        reviewed.append({
            **finding,
            "severity": (
                "LOW"
                if finding["severity"] == "INFO"
                else finding["severity"]
            ),
            "recommended_action": "Request user approval.",
        })

    return {
        "summary": "Two findings require attention.",
        "total_findings": len(reviewed),
        "critical_count": 0,
        "high_count": 1,
        "medium_count": 0,
        "low_count": 1,
        "requires_user_approval": True,
        "findings": reviewed,
    }


def test_persist_review_and_findings(db_session, test_project):
    verification = {
        "passed": False,
        "summary": "Findings detected.",
        "files_checked": 2,
        "checks_performed": ["Source inspection"],
        "findings": make_verification_findings(),
    }

    review = persist_review(
        db=db_session,
        project_id=test_project.id,
        verification_results=verification,
        review_data=make_review_data(verification["findings"]),
    )

    findings = db_session.scalars(
        select(Finding).where(Finding.review_id == review.id)
    ).all()

    assert review.status == ReviewStatus.COMPLETED
    assert review.review_type == ReviewType.INITIAL
    assert review.total_findings == 2
    assert review.high_count == 1
    assert review.low_count == 1

    assert len(findings) == 2

    security_finding = next(
        item for item in findings
        if item.file_path == "src/main.py"
    )

    assert security_finding.status == FindingStatus.OPEN
    assert security_finding.severity == FindingSeverity.HIGH
    assert security_finding.category == FindingCategory.SECURITY
    assert security_finding.is_auto_fixable is True

    config_finding = next(
        item for item in findings
        if item.file_path == "src/config.py"
    )

    assert config_finding.severity == FindingSeverity.LOW
    assert config_finding.category == FindingCategory.CONFIGURATION


def test_review_numbers_increment(db_session, test_project):
    verification = {
        "findings": [
            {
                "file_path": "main.py",
                "title": "Potential bug",
                "description": "Potential runtime issue.",
                "severity": "MEDIUM",
                "category": "BUG",
                "line_number": 4,
                "suggested_fix": "Validate the input.",
            }
        ]
    }

    review_data = {
        "summary": "One finding.",
        "total_findings": 1,
        "critical_count": 0,
        "high_count": 0,
        "medium_count": 1,
        "low_count": 0,
        "requires_user_approval": True,
        "findings": [
            {
                **verification["findings"][0],
                "recommended_action": "Request approval.",
            }
        ],
    }

    first = persist_review(
        db_session,
        test_project.id,
        verification,
        review_data,
    )

    second = persist_review(
        db_session,
        test_project.id,
        verification,
        review_data,
        review_type=ReviewType.POST_FIX,
    )

    assert first.review_number == 1
    assert second.review_number == 2
    assert second.review_type == ReviewType.POST_FIX


def test_rejects_mismatched_finding_count(
    db_session,
    test_project,
):
    verification = {
        "findings": make_verification_findings()
    }

    review_data = make_review_data(
        verification["findings"][:1]
    )

    with pytest.raises(ReviewPersistenceError):
        persist_review(
            db_session,
            test_project.id,
            verification,
            review_data,
        )


def test_rejects_modified_finding_identity(
    db_session,
    test_project,
):
    verification = {
        "findings": make_verification_findings()
    }

    review_data = make_review_data(
        verification["findings"]
    )

    review_data["findings"][0]["title"] = "Changed title"

    with pytest.raises(ReviewPersistenceError):
        persist_review(
            db_session,
            test_project.id,
            verification,
            review_data,
        )


def test_rejects_missing_project(db_session):
    verification = {"findings": []}

    review_data = {
        "findings": [],
        "total_findings": 0,
    }

    with pytest.raises(
        ReviewPersistenceError,
        match="Project not found",
    ):
        persist_review(
            db_session,
            uuid.uuid4(),
            verification,
            review_data,
        )