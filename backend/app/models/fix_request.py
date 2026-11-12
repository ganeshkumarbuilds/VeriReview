from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class FixRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FixRequest(Base):
    __tablename__ = "fix_requests"

    __table_args__ = (
        Index(
            "ix_fix_requests_project_created",
            "project_id",
            "created_at",
        ),
        ForeignKeyConstraint(
            ["finding_id", "project_id"],
            ["findings.id", "findings.project_id"],
            name="fk_fix_requests_finding_project",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status NOT IN ('IN_PROGRESS', 'COMPLETED') "
            "OR approved_at IS NOT NULL",
            name="ck_fix_requests_execution_requires_approval",
        ),
        CheckConstraint(
            "started_at IS NULL OR approved_at IS NOT NULL",
            name="ck_fix_requests_start_requires_approval",
        ),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NOT NULL",
            name="ck_fix_requests_completion_requires_start",
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

    finding_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )

    status: Mapped[FixRequestStatus] = mapped_column(
        SQLAlchemyEnum(
            FixRequestStatus,
            name="fix_request_status",
        ),
        default=FixRequestStatus.REQUESTED,
        nullable=False,
    )

    user_instruction: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="fix_requests",
    )

    finding: Mapped["Finding"] = relationship(
        "Finding",
        back_populates="fix_requests",
        foreign_keys=[finding_id],
    )
    