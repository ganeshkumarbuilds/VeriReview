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
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class AgentType(str, Enum):
    PLANNING = "PLANNING"
    CODING = "CODING"
    VERIFYING = "VERIFYING"
    REVIEW = "REVIEW"


class AgentExecutionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AgentExecution(Base):
    __tablename__ = "agent_executions"

    __table_args__ = (
        Index(
            "ix_agent_executions_project_created",
            "project_id",
            "created_at",
        ),
        CheckConstraint(
            "execution_number >= 1",
            name="ck_agent_executions_execution_number_positive",
        ),
        CheckConstraint(
            "progress_percentage >= 0 AND progress_percentage <= 100",
            name="ck_agent_executions_progress_percentage_range",
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

    agent_type: Mapped[AgentType] = mapped_column(
        SQLAlchemyEnum(AgentType, name="agent_type"),
        nullable=False,
    )

    status: Mapped[AgentExecutionStatus] = mapped_column(
        SQLAlchemyEnum(
            AgentExecutionStatus,
            name="agent_execution_status",
        ),
        default=AgentExecutionStatus.PENDING,
        nullable=False,
    )

    execution_number: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    progress_percentage: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    input_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    output_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(150),
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="agent_executions",
    )

    events: Mapped[list["ExecutionEvent"]] = relationship(
        "ExecutionEvent",
        back_populates="agent_execution",
    )