from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class ProjectType(str, Enum):
    GENERATED = "GENERATED"
    UPLOADED = "UPLOADED"


class ProjectStatus(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    GENERATING = "GENERATING"
    VERIFYING = "VERIFYING"
    REVIEWING = "REVIEWING"
    FIXING = "FIXING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Project(Base):
    __tablename__ = "projects"

    __table_args__ = (
        Index("ix_projects_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    user_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    project_type: Mapped[ProjectType] = mapped_column(
        SQLAlchemyEnum(ProjectType, name="project_type"),
        nullable=False,
    )

    status: Mapped[ProjectStatus] = mapped_column(
        SQLAlchemyEnum(ProjectStatus, name="project_status"),
        default=ProjectStatus.CREATED,
        nullable=False,
    )

    technology_stack: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source_location: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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

    owner: Mapped["User"] = relationship(
        "User",
        back_populates="projects",
    )

    files: Mapped[list["ProjectFile"]] = relationship(
        "ProjectFile",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    generation_plan: Mapped["GenerationPlan | None"] = relationship(
        "GenerationPlan",
        back_populates="project",
        cascade="all, delete-orphan",
        uselist=False,
    )

    agent_executions: Mapped[list["AgentExecution"]] = relationship(
        "AgentExecution",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    fix_requests: Mapped[list["FixRequest"]] = relationship(
        "FixRequest",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    execution_events: Mapped[list["ExecutionEvent"]] = relationship(
        "ExecutionEvent",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    artifacts: Mapped[list["ProjectArtifact"]] = relationship(
        "ProjectArtifact",
        back_populates="project",
        cascade="all, delete-orphan",
    )