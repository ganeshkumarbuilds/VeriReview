from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.finding import Finding
from app.models.review import Review
from app.models.user import User
from app.services.projects import get_project


router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["Project Reviews"],
)


def verify_project_ownership(
    db: Session,
    user_id: UUID,
    project_id: UUID,
):
    """Verify that the authenticated user owns the project."""

    project = get_project(
        db=db,
        user_id=user_id,
        project_id=project_id,
    )

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found.",
        )

    return project


def serialize_finding(finding: Finding) -> dict:
    """Convert a Finding model into an API response."""

    return {
        "id": str(finding.id),
        "review_id": str(finding.review_id),
        "project_id": str(finding.project_id),
        "title": finding.title,
        "description": finding.description,
        "severity": finding.severity.value,
        "category": finding.category.value,
        "status": finding.status.value,
        "file_path": finding.file_path,
        "line_number": finding.line_number,
        "code_snippet": finding.code_snippet,
        "suggested_fix": finding.suggested_fix,
        "is_auto_fixable": finding.is_auto_fixable,
        "detected_at": finding.detected_at,
    }


def serialize_review(review: Review) -> dict:
    """Convert a Review model into an API response."""

    return {
        "id": str(review.id),
        "project_id": str(review.project_id),
        "review_number": review.review_number,
        "review_type": review.review_type.value,
        "status": review.status.value,
        "total_findings": review.total_findings,
        "critical_count": review.critical_count,
        "high_count": review.high_count,
        "medium_count": review.medium_count,
        "low_count": review.low_count,
        "started_at": review.started_at,
        "completed_at": review.completed_at,
        "created_at": review.created_at,
    }


@router.get("/reviews")
def get_project_reviews(
    project_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List reviews belonging to a project."""

    verify_project_ownership(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    total = db.scalar(
        select(func.count())
        .select_from(Review)
        .where(Review.project_id == project_id)
    ) or 0

    reviews = db.scalars(
        select(Review)
        .where(Review.project_id == project_id)
        .order_by(
            Review.review_number.desc(),
            Review.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "reviews": [
            serialize_review(review)
            for review in reviews
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/reviews/{review_id}")
def get_project_review_details(
    project_id: UUID,
    review_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve a review and all its findings."""

    verify_project_ownership(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    review = db.scalar(
        select(Review)
        .options(selectinload(Review.findings))
        .where(
            Review.id == review_id,
            Review.project_id == project_id,
        )
    )

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )

    return {
        **serialize_review(review),
        "findings": [
            serialize_finding(finding)
            for finding in review.findings
        ],
    }


@router.get("/findings")
def get_project_findings(
    project_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    severity: str | None = Query(default=None),
    finding_status: str | None = Query(
        default=None,
        alias="status",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List findings belonging to a project."""

    from app.models.finding import (
        FindingSeverity,
        FindingStatus,
    )

    verify_project_ownership(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    query = select(Finding).where(
        Finding.project_id == project_id
    )

    if severity is not None:
        try:
            selected_severity = FindingSeverity(severity.upper())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid finding severity.",
            )

        query = query.where(
            Finding.severity == selected_severity
        )

    if finding_status is not None:
        try:
            selected_status = FindingStatus(
                finding_status.upper()
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid finding status.",
            )

        query = query.where(
            Finding.status == selected_status
        )

    total = db.scalar(
        select(func.count()).select_from(
            query.order_by(None).subquery()
        )
    ) or 0

    findings = db.scalars(
        query.order_by(
            Finding.detected_at.desc(),
            Finding.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return {
        "findings": [
            serialize_finding(finding)
            for finding in findings
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/findings/{finding_id}")
def get_project_finding_details(
    project_id: UUID,
    finding_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve an individual finding."""

    verify_project_ownership(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    finding = db.scalar(
        select(Finding).where(
            Finding.id == finding_id,
            Finding.project_id == project_id,
        )
    )

    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found.",
        )

    return serialize_finding(finding)