from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class ExecutionEventType(str, Enum):
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_PROGRESS = "AGENT_PROGRESS"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    AGENT_FAILED = "AGENT_FAILED"
    FILE_CREATED = "FILE_CREATED"
    FILE_UPDATED = "FILE_UPDATED"
    TEST_STARTED = "TEST_STARTED"
    TEST_COMPLETED = "TEST_COMPLETED"
    FINDING_DETECTED = "FINDING_DETECTED"
    FIX_APPROVED = "FIX_APPROVED"
    FIX_COMPLETED = "FIX_COMPLETED"
    FIX_FAILED = "FIX_FAILED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"


class ExecutionEvent(Base):
    __tablename__ = "execution_events"

    __table_args__ = (
        Index(
            "ix_execution_events_project_created",
            "project_id",
            "created_at",
        ),
        CheckConstraint(
            "length(trim(message)) > 0",
            name="ck_execution_events_message_not_empty",
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

    agent_execution_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("agent_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    event_type: Mapped[ExecutionEventType] = mapped_column(
        SQLAlchemyEnum(
            ExecutionEventType,
            name="execution_event_type",
        ),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    event_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="execution_events",
    )

    agent_execution: Mapped["AgentExecution | None"] = relationship(
        "AgentExecution",
        back_populates="events",
    )