from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingCategory(str, Enum):
    BUG = "BUG"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"
    CODE_QUALITY = "CODE_QUALITY"
    CONFIGURATION = "CONFIGURATION"
    DEPENDENCY = "DEPENDENCY"
    OTHER = "OTHER"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    FIXED = "FIXED"
    ACCEPTED = "ACCEPTED"
    WONT_FIX = "WONT_FIX"


class Finding(Base):
    __tablename__ = "findings"

    __table_args__ = (
        Index("ix_findings_review_severity", "review_id", "severity"),
        ForeignKeyConstraint(
            ["review_id", "project_id"],
            ["reviews.id", "reviews.project_id"],
            name="fk_findings_review_project",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "project_id",
            name="uq_findings_id_project",
        ),
        CheckConstraint(
            "line_number IS NULL OR line_number >= 1",
            name="ck_findings_line_number_positive",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_findings_title_not_empty",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    review_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )

    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    severity: Mapped[FindingSeverity] = mapped_column(
        SQLAlchemyEnum(FindingSeverity, name="finding_severity"),
        nullable=False,
    )

    category: Mapped[FindingCategory] = mapped_column(
        SQLAlchemyEnum(FindingCategory, name="finding_category"),
        nullable=False,
    )

    status: Mapped[FindingStatus] = mapped_column(
        SQLAlchemyEnum(FindingStatus, name="finding_status"),
        default=FindingStatus.OPEN,
        nullable=False,
    )

    file_path: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    line_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    code_snippet: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    suggested_fix: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_auto_fixable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    review: Mapped["Review"] = relationship(
        "Review",
        back_populates="findings",
    )

    fix_requests: Mapped[list["FixRequest"]] = relationship(
        "FixRequest",
        back_populates="finding",
        foreign_keys="FixRequest.finding_id",
    )