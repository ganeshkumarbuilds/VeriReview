from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_execution import (
    AgentExecution,
    AgentExecutionStatus,
    AgentType,
)
from app.models.project import Project


class AgentExecutionError(Exception):
    """Base exception for agent execution operations."""


class AgentExecutionNotFoundError(AgentExecutionError):
    """Raised when an agent execution cannot be found."""


class InvalidExecutionStateError(AgentExecutionError):
    """Raised when an operation is invalid for the current state."""


def create_agent_execution(
    db: Session,
    project_id: UUID,
    agent_type: AgentType,
    execution_number: int = 1,
    input_data: dict | None = None,
    model_name: str | None = None,
) -> AgentExecution:
    """Create a pending agent execution."""

    if execution_number < 1:
        raise ValueError("Execution number must be at least 1")

    project = db.scalar(
        select(Project).where(Project.id == project_id)
    )

    if project is None:
        raise ValueError("Project does not exist")

    execution = AgentExecution(
        project_id=project_id,
        agent_type=agent_type,
        status=AgentExecutionStatus.PENDING,
        execution_number=execution_number,
        progress_percentage=0,
        input_data=input_data,
        model_name=model_name,
    )

    db.add(execution)
    db.flush()
    db.refresh(execution)

    return execution


def get_agent_execution(
    db: Session,
    execution_id: UUID,
) -> AgentExecution | None:
    """Retrieve an agent execution by its ID."""

    return db.scalar(
        select(AgentExecution).where(
            AgentExecution.id == execution_id
        )
    )


def list_agent_executions(
    db: Session,
    project_id: UUID,
) -> list[AgentExecution]:
    """List all agent executions belonging to a project."""

    return list(
        db.scalars(
            select(AgentExecution)
            .where(AgentExecution.project_id == project_id)
            .order_by(
                AgentExecution.created_at.asc(),
                AgentExecution.id.asc(),
            )
        ).all()
    )


def start_agent_execution(
    db: Session,
    execution_id: UUID,
) -> AgentExecution:
    """Move a pending execution into the running state."""

    execution = get_agent_execution(db, execution_id)

    if execution is None:
        raise AgentExecutionNotFoundError(
            "Agent execution does not exist"
        )

    if execution.status != AgentExecutionStatus.PENDING:
        raise InvalidExecutionStateError(
            "Only pending executions can be started"
        )

    execution.status = AgentExecutionStatus.RUNNING
    execution.started_at = datetime.now(timezone.utc)
    execution.progress_percentage = 0

    db.flush()
    db.refresh(execution)

    return execution


def update_agent_execution_progress(
    db: Session,
    execution_id: UUID,
    progress_percentage: int,
    output_data: dict | None = None,
) -> AgentExecution:
    """Update the progress of a running execution."""

    if isinstance(progress_percentage, bool) or not isinstance(
        progress_percentage, int
    ):
        raise ValueError("Progress must be an integer")

    if not 0 <= progress_percentage <= 100:
        raise ValueError("Progress must be between 0 and 100")

    execution = get_agent_execution(db, execution_id)

    if execution is None:
        raise AgentExecutionNotFoundError(
            "Agent execution does not exist"
        )

    if execution.status != AgentExecutionStatus.RUNNING:
        raise InvalidExecutionStateError(
            "Progress can only be updated for running executions"
        )

    if progress_percentage < execution.progress_percentage:
        raise ValueError("Progress cannot decrease")

    execution.progress_percentage = progress_percentage

    if output_data is not None:
        execution.output_data = output_data

    db.flush()
    db.refresh(execution)

    return execution


def complete_agent_execution(
    db: Session,
    execution_id: UUID,
    output_data: dict | None = None,
) -> AgentExecution:
    """Mark a running execution as completed."""

    execution = get_agent_execution(db, execution_id)

    if execution is None:
        raise AgentExecutionNotFoundError(
            "Agent execution does not exist"
        )

    if execution.status != AgentExecutionStatus.RUNNING:
        raise InvalidExecutionStateError(
            "Only running executions can be completed"
        )

    execution.status = AgentExecutionStatus.COMPLETED
    execution.progress_percentage = 100
    execution.completed_at = datetime.now(timezone.utc)

    if output_data is not None:
        execution.output_data = output_data

    db.flush()
    db.refresh(execution)

    return execution


def fail_agent_execution(
    db: Session,
    execution_id: UUID,
    error_message: str,
) -> AgentExecution:
    """Mark a running execution as failed."""

    if not error_message or not error_message.strip():
        raise ValueError("An error message is required")

    execution = get_agent_execution(db, execution_id)

    if execution is None:
        raise AgentExecutionNotFoundError(
            "Agent execution does not exist"
        )

    if execution.status != AgentExecutionStatus.RUNNING:
        raise InvalidExecutionStateError(
            "Only running executions can be failed"
        )

    execution.status = AgentExecutionStatus.FAILED
    execution.error_message = error_message.strip()
    execution.completed_at = datetime.now(timezone.utc)

    db.flush()
    db.refresh(execution)

    return execution


def cancel_agent_execution(
    db: Session,
    execution_id: UUID,
) -> AgentExecution:
    """Cancel a pending or running execution."""

    execution = get_agent_execution(db, execution_id)

    if execution is None:
        raise AgentExecutionNotFoundError(
            "Agent execution does not exist"
        )

    if execution.status not in (
        AgentExecutionStatus.PENDING,
        AgentExecutionStatus.RUNNING,
    ):
        raise InvalidExecutionStateError(
            "Only pending or running executions can be cancelled"
        )

    execution.status = AgentExecutionStatus.CANCELLED
    execution.completed_at = datetime.now(timezone.utc)

    db.flush()
    db.refresh(execution)

    return execution