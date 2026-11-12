from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.execution_event import ExecutionEventType
from app.models.user import User
from app.schemas.agent_execution import (
    AgentExecutionListResponse,
    AgentExecutionResponse,
)
from app.schemas.execution_event import (
    ExecutionEventListResponse,
)
from app.services.agent_executions import (
    get_agent_execution,
    list_agent_executions,
)
from app.services.execution_events import (
    list_execution_events,
)
from app.services.projects import get_project


router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["Agent Executions"],
)


def verify_project_ownership(
    db: Session,
    user_id: UUID,
    project_id: UUID,
):
    project = get_project(
        db=db,
        user_id=user_id,
        project_id=project_id,
    )

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    return project


@router.get(
    "/executions",
    response_model=AgentExecutionListResponse,
)
def get_project_executions(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_project_ownership(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    executions = list_agent_executions(
        db=db,
        project_id=project_id,
    )

    return {
        "executions": executions,
        "total": len(executions),
    }


@router.get(
    "/executions/{execution_id}",
    response_model=AgentExecutionResponse,
)
def get_project_execution_details(
    project_id: UUID,
    execution_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_project_ownership(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    execution = get_agent_execution(
        db=db,
        execution_id=execution_id,
    )

    if execution is None or execution.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent execution not found",
        )

    return execution


@router.get(
    "/events",
    response_model=ExecutionEventListResponse,
)
def get_project_execution_events(
    project_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    event_type: ExecutionEventType | None = Query(default=None),
    agent_execution_id: UUID | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_project_ownership(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    try:
        return list_execution_events(
            db=db,
            project_id=project_id,
            page=page,
            page_size=page_size,
            event_type=event_type,
            agent_execution_id=agent_execution_id,
        )

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent execution not found in this project",
        )