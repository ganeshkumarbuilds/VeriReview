from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReviewType(str, Enum):
    INITIAL = "INITIAL"
    POST_FIX = "POST_FIX"


class Review(Base):
    __tablename__ = "reviews"

    __table_args__ = (
        Index(
            "ix_reviews_project_created",
            "project_id",
            "created_at",
        ),
        UniqueConstraint(
            "project_id",
            "review_number",
            name="uq_reviews_project_number",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_reviews_id_project",
        ),
        CheckConstraint(
            "review_number >= 1",
            name="ck_reviews_review_number_positive",
        ),
        CheckConstraint(
            "total_findings >= 0 AND critical_count >= 0 "
            "AND high_count >= 0 AND medium_count >= 0 "
            "AND low_count >= 0",
            name="ck_reviews_finding_counts_nonnegative",
        ),
        CheckConstraint(
            "total_findings = critical_count + high_count "
            "+ medium_count + low_count",
            name="ck_reviews_finding_counts_consistent",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    review_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    review_type: Mapped[ReviewType] = mapped_column(
        SQLAlchemyEnum(ReviewType, name="review_type"),
        nullable=False,
    )

    status: Mapped[ReviewStatus] = mapped_column(
        SQLAlchemyEnum(ReviewStatus, name="review_status"),
        default=ReviewStatus.PENDING,
        nullable=False,
    )

    total_findings: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    critical_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    high_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    medium_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    low_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="reviews",
    )

    findings: Mapped[list["Finding"]] = relationship(
        "Finding",
        back_populates="review",
        cascade="all, delete-orphan",
    )