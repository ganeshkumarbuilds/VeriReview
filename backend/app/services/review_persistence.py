from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.finding import (
    Finding,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
)
from app.models.project import Project
from app.models.review import (
    Review,
    ReviewStatus,
    ReviewType,
)


SEVERITY_MAP = {
    "CRITICAL": FindingSeverity.CRITICAL,
    "HIGH": FindingSeverity.HIGH,
    "MEDIUM": FindingSeverity.MEDIUM,
    "LOW": FindingSeverity.LOW,
}

CATEGORY_MAP = {
    "BUG": FindingCategory.BUG,
    "LOGIC": FindingCategory.BUG,
    "SECURITY": FindingCategory.SECURITY,
    "PERFORMANCE": FindingCategory.PERFORMANCE,
    "CODE_QUALITY": FindingCategory.CODE_QUALITY,
    "STYLE": FindingCategory.CODE_QUALITY,
    "CONFIGURATION": FindingCategory.CONFIGURATION,
    "DEPENDENCY": FindingCategory.DEPENDENCY,
    "OTHER": FindingCategory.OTHER,
}


class ReviewPersistenceError(Exception):
    """Raised when review persistence fails."""


def persist_review(
    db: Session,
    project_id: UUID,
    verification_results: dict,
    review_data: dict,
    review_type: ReviewType = ReviewType.INITIAL,
) -> Review:
    """Persist a completed agent review and its actionable findings."""

    project = db.scalar(
        select(Project)
        .where(Project.id == project_id)
        .with_for_update()
    )

    if project is None:
        raise ReviewPersistenceError("Project not found.")

    raw_findings = verification_results.get("findings")

    if not isinstance(raw_findings, list):
        raise ReviewPersistenceError(
            "Verification findings must be a list."
        )

    reviewed_findings = review_data.get("findings")

    if not isinstance(reviewed_findings, list):
        raise ReviewPersistenceError(
            "Reviewed findings must be a list."
        )

    if len(raw_findings) != len(reviewed_findings):
        raise ReviewPersistenceError(
            "Review Agent changed the number of findings."
        )

    if len(raw_findings) != len(set(
        (
            item.get("file_path"),
            item.get("title"),
            item.get("line_number"),
        )
        for item in raw_findings
    )):
        raise ReviewPersistenceError(
            "Verification contains duplicate findings."
        )

    review_number = (
        db.scalar(
            select(func.max(Review.review_number)).where(
                Review.project_id == project_id
            )
        )
        or 0
    ) + 1

    severity_counts = {
        severity: 0
        for severity in SEVERITY_MAP
    }

    normalized_findings = []

    for original, reviewed in zip(
        raw_findings,
        reviewed_findings,
        strict=True,
    ):
        if not isinstance(original, dict) or not isinstance(
            reviewed,
            dict,
        ):
            raise ReviewPersistenceError(
                "Finding entries must be objects."
            )

        severity = str(original.get("severity", "")).upper()
        category = str(original.get("category", "OTHER")).upper()

        if severity == "INFO":
            severity = "LOW"

        if severity not in SEVERITY_MAP:
            raise ReviewPersistenceError(
                f"Unsupported finding severity: {severity}"
            )

        if (
            original.get("file_path") != reviewed.get("file_path")
            or original.get("title") != reviewed.get("title")
            or original.get("line_number") != reviewed.get("line_number")
            or severity != str(reviewed.get("severity", "")).upper()
        ):
            raise ReviewPersistenceError(
                "Review Agent modified the identity or severity "
                "of a verification finding."
            )

        finding_category = CATEGORY_MAP.get(
            category,
            FindingCategory.OTHER,
        )

        severity_counts[severity] += 1

        normalized_findings.append(
            {
                "file_path": original.get("file_path"),
                "title": original.get("title"),
                "description": original.get("description"),
                "severity": SEVERITY_MAP[severity],
                "category": finding_category,
                "line_number": original.get("line_number"),
                "suggested_fix": original.get("suggested_fix"),
            }
        )

    review = Review(
        project_id=project_id,
        review_number=review_number,
        review_type=review_type,
        status=ReviewStatus.COMPLETED,
        total_findings=len(normalized_findings),
        critical_count=severity_counts["CRITICAL"],
        high_count=severity_counts["HIGH"],
        medium_count=severity_counts["MEDIUM"],
        low_count=severity_counts["LOW"],
    )

    db.add(review)
    db.flush()

    for item in normalized_findings:
        db.add(
            Finding(
                review_id=review.id,
                project_id=project_id,
                title=item["title"],
                description=item["description"],
                severity=item["severity"],
                category=item["category"],
                status=FindingStatus.OPEN,
                file_path=item["file_path"],
                line_number=item["line_number"],
                suggested_fix=item["suggested_fix"],
                is_auto_fixable=bool(item["suggested_fix"]),
            )
        )

    db.flush()
    db.refresh(review)

    return review