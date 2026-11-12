from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent_execution import (
    AgentExecution,
    AgentExecutionStatus,
    AgentType,
)
from app.models.execution_event import (
    ExecutionEvent,
    ExecutionEventType,
)
from app.models.generation_plan import (
    GenerationPlan,
    GenerationPlanStatus,
)
from app.models.project import Project, ProjectStatus
from app.services.generated_files import create_generated_file


def save_generation_plan(
    db: Session,
    project_id: UUID,
    requirements: str,
    plan_data: dict,
    status: GenerationPlanStatus = GenerationPlanStatus.IN_PROGRESS,
) -> GenerationPlan:
    """Create or update the generation plan for a project."""

    plan = db.scalar(
        select(GenerationPlan).where(
            GenerationPlan.project_id == project_id
        )
    )

    if plan is None:
        plan = GenerationPlan(
            project_id=project_id,
            requirements=requirements,
            architecture=plan_data["architecture"],
            folder_structure=plan_data["folder_structure"],
            implementation_plan=plan_data["implementation_plan"],
            estimated_files=plan_data["estimated_files"],
            status=status,
        )
        db.add(plan)
    else:
        plan.requirements = requirements
        plan.architecture = plan_data["architecture"]
        plan.folder_structure = plan_data["folder_structure"]
        plan.implementation_plan = plan_data["implementation_plan"]
        plan.estimated_files = plan_data["estimated_files"]
        plan.status = status

    db.flush()
    db.refresh(plan)

    return plan


def update_generation_plan_status(
    db: Session,
    project_id: UUID,
    status: GenerationPlanStatus,
) -> GenerationPlan:
    """Update the status of an existing generation plan."""

    plan = db.scalar(
        select(GenerationPlan).where(
            GenerationPlan.project_id == project_id
        )
    )

    if plan is None:
        raise ValueError("Generation plan not found")

    plan.status = status

    db.flush()
    db.refresh(plan)

    return plan


def update_project_status(
    db: Session,
    project_id: UUID,
    status: ProjectStatus,
) -> Project:
    """Update the project lifecycle status."""

    project = db.scalar(
        select(Project).where(
            Project.id == project_id
        )
    )

    if project is None:
        raise ValueError("Project not found")

    project.status = status

    db.flush()
    db.refresh(project)

    return project


def record_agent_started(
    db: Session,
    project_id: UUID,
    agent_type: AgentType,
    execution_number: int = 1,
    input_data: dict | None = None,
    model_name: str | None = None,
) -> AgentExecution:
    """Create and start an agent execution with an event."""

    execution = AgentExecution(
        project_id=project_id,
        agent_type=agent_type,
        status=AgentExecutionStatus.RUNNING,
        execution_number=execution_number,
        progress_percentage=0,
        input_data=input_data,
        model_name=model_name,
    )

    from datetime import datetime, timezone

    execution.started_at = datetime.now(timezone.utc)

    db.add(execution)
    db.flush()
    db.refresh(execution)

    create_execution_event(
        db=db,
        project_id=project_id,
        agent_execution_id=execution.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message=f"{agent_type.value} agent started.",
        event_data={
            "agent_type": agent_type.value,
            "execution_number": execution_number,
        },
    )

    return execution


def record_agent_completed(
    db: Session,
    execution_id: UUID,
    output_data: dict | None = None,
) -> AgentExecution:
    """Complete an agent execution and record its event."""

    execution = db.scalar(
        select(AgentExecution).where(
            AgentExecution.id == execution_id
        )
    )

    if execution is None:
        raise ValueError("Agent execution not found")

    if execution.status != AgentExecutionStatus.RUNNING:
        raise ValueError("Only running executions can be completed")

    from datetime import datetime, timezone

    execution.status = AgentExecutionStatus.COMPLETED
    execution.progress_percentage = 100
    execution.output_data = output_data
    execution.completed_at = datetime.now(timezone.utc)

    db.flush()
    db.refresh(execution)

    create_execution_event(
        db=db,
        project_id=execution.project_id,
        agent_execution_id=execution.id,
        event_type=ExecutionEventType.AGENT_COMPLETED,
        message=f"{execution.agent_type.value} agent completed.",
        event_data={
            "agent_type": execution.agent_type.value,
            "execution_number": execution.execution_number,
        },
    )

    return execution


def record_agent_failed(
    db: Session,
    execution_id: UUID,
    error_message: str,
) -> AgentExecution:
    """Mark an agent execution as failed and record its event."""

    execution = db.scalar(
        select(AgentExecution).where(
            AgentExecution.id == execution_id
        )
    )

    if execution is None:
        raise ValueError("Agent execution not found")

    if execution.status != AgentExecutionStatus.RUNNING:
        raise ValueError("Only running executions can be failed")

    if not error_message or not error_message.strip():
        raise ValueError("An error message is required")

    from datetime import datetime, timezone

    execution.status = AgentExecutionStatus.FAILED
    execution.error_message = error_message.strip()
    execution.completed_at = datetime.now(timezone.utc)

    db.flush()
    db.refresh(execution)

    create_execution_event(
        db=db,
        project_id=execution.project_id,
        agent_execution_id=execution.id,
        event_type=ExecutionEventType.AGENT_FAILED,
        message=f"{execution.agent_type.value} agent failed.",
        event_data={
            "agent_type": execution.agent_type.value,
            "error": error_message.strip(),
        },
    )

    return execution


def persist_generated_files(
    db: Session,
    user_id: UUID,
    project_id: UUID,
    generated_files: list[dict],
) -> list:
    """Persist generated file contents and their database metadata."""

    persisted_files = []

    for item in generated_files:
        file_path = item.get("file_path")
        content = item.get("content")

        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("Generated file path is missing")

        if not isinstance(content, str):
            raise ValueError(
                f"Generated file content must be text: {file_path}"
            )

        project_file = create_generated_file(
            db=db,
            user_id=user_id,
            project_id=project_id,
            file_path=file_path,
            content=content.encode("utf-8"),
        )

        persisted_files.append(project_file)

        create_execution_event(
            db=db,
            project_id=project_id,
            event_type=ExecutionEventType.FILE_CREATED,
            message=f"Generated file created: {file_path}",
            event_data={
                "file_path": file_path,
                "file_size": project_file.file_size,
                "checksum": project_file.checksum,
            },
        )

    return persisted_files


def create_execution_event(
    db: Session,
    project_id: UUID,
    event_type: ExecutionEventType,
    message: str,
    agent_execution_id: UUID | None = None,
    event_data: dict | None = None,
) -> ExecutionEvent:
    """Create an execution event."""

    event = ExecutionEvent(
        project_id=project_id,
        agent_execution_id=agent_execution_id,
        event_type=event_type,
        message=message,
        event_data=event_data,
    )

    db.add(event)
    db.flush()
    db.refresh(event)

    return event