from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class GenerationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GenerationPlan(Base):
    __tablename__ = "generation_plans"

    __table_args__ = (
        CheckConstraint(
            "estimated_files >= 0",
            name="ck_generation_plans_estimated_files_nonnegative",
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
        unique=True,
        nullable=False,
    )

    requirements: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    architecture: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    folder_structure: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    implementation_plan: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    estimated_files: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    status: Mapped[GenerationPlanStatus] = mapped_column(
        SQLAlchemyEnum(
            GenerationPlanStatus,
            name="generation_plan_status",
        ),
        default=GenerationPlanStatus.DRAFT,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="generation_plan",
    )