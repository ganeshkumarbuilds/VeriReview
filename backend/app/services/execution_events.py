from math import ceil
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent_execution import AgentExecution
from app.models.execution_event import (
    ExecutionEvent,
    ExecutionEventType,
)
from app.models.project import Project


class ExecutionEventError(Exception):
    """Base exception for execution event operations."""


class ExecutionEventNotFoundError(ExecutionEventError):
    """Raised when an execution event cannot be found."""


def create_execution_event(
    db: Session,
    project_id: UUID,
    event_type: ExecutionEventType,
    message: str,
    agent_execution_id: UUID | None = None,
    event_data: dict | None = None,
) -> ExecutionEvent:
    """Create an event associated with a project and optionally an agent."""

    if not isinstance(event_type, ExecutionEventType):
        raise ValueError("Invalid execution event type")

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Event message cannot be empty")

    project = db.scalar(
        select(Project).where(Project.id == project_id)
    )

    if project is None:
        raise ValueError("Project does not exist")

    if agent_execution_id is not None:
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.id == agent_execution_id
            )
        )

        if execution is None:
            raise ValueError("Agent execution does not exist")

        if execution.project_id != project_id:
            raise ValueError(
                "Agent execution does not belong to this project"
            )

    event = ExecutionEvent(
        project_id=project_id,
        agent_execution_id=agent_execution_id,
        event_type=event_type,
        message=message.strip(),
        event_data=event_data,
    )

    db.add(event)
    db.flush()
    db.refresh(event)

    return event


def get_execution_event(
    db: Session,
    project_id: UUID,
    event_id: UUID,
) -> ExecutionEvent | None:
    """Retrieve an event belonging to a specific project."""

    return db.scalar(
        select(ExecutionEvent).where(
            ExecutionEvent.id == event_id,
            ExecutionEvent.project_id == project_id,
        )
    )


def list_execution_events(
    db: Session,
    project_id: UUID,
    page: int = 1,
    page_size: int = 50,
    event_type: ExecutionEventType | None = None,
    agent_execution_id: UUID | None = None,
) -> dict:
    """List project events with optional filters and pagination."""

    if page < 1:
        raise ValueError("Page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise ValueError("Page size must be between 1 and 100")

    if event_type is not None and not isinstance(
        event_type,
        ExecutionEventType,
    ):
        raise ValueError("Invalid execution event type")

    project = db.scalar(
        select(Project).where(Project.id == project_id)
    )

    if project is None:
        raise ValueError("Project does not exist")

    filters = [
        ExecutionEvent.project_id == project_id,
    ]

    if event_type is not None:
        filters.append(
            ExecutionEvent.event_type == event_type
        )

    if agent_execution_id is not None:
        execution = db.scalar(
            select(AgentExecution).where(
                AgentExecution.id == agent_execution_id,
                AgentExecution.project_id == project_id,
            )
        )

        if execution is None:
            raise ValueError(
                "Agent execution does not belong to this project"
            )

        filters.append(
            ExecutionEvent.agent_execution_id == agent_execution_id
        )

    total = db.scalar(
        select(func.count())
        .select_from(ExecutionEvent)
        .where(*filters)
    ) or 0

    events = db.scalars(
        select(ExecutionEvent)
        .where(*filters)
        .order_by(
            ExecutionEvent.created_at.desc(),
            ExecutionEvent.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    total_pages = ceil(total / page_size) if total else 0

    return {
        "events": list(events),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }