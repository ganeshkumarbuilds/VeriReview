import logging
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.auth import get_current_user
from app.database.connection import SessionLocal, get_db
from app.models.agent_execution import AgentExecution
from app.models.generation_plan import GenerationPlan
from app.models.project import ProjectStatus, ProjectType
from app.models.user import User
from app.services.generation_persistence import update_project_status
from app.services.projects import get_project
from app.workflows.generation import build_generation_graph
from app.workflows.generation_lifecycle import GenerationLifecycle


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["Project Generation"],
)


ACTIVE_STATUSES = {
    ProjectStatus.PLANNING,
    ProjectStatus.GENERATING,
    ProjectStatus.VERIFYING,
    ProjectStatus.REVIEWING,
    ProjectStatus.FIXING,
}


def _get_owned_project(
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
            detail="Project not found.",
        )

    return project


async def _run_generation(
    project_id: UUID,
    user_id: UUID,
    requirements: str,
    technology_stack: str | None,
    workflow_id: str,
    checkpointer,
):
    """
    Execute the generation workflow in the background.

    Database sessions are opened only for short persistence
    operations. They are not held open during LLM requests.
    """

    lifecycle = GenerationLifecycle(
        project_id=project_id,
        user_id=user_id,
    )

    try:
        graph = build_generation_graph(
            checkpointer=checkpointer,
        )

        initial_state = {
            "workflow_id": workflow_id,
            "workflow_type": "GENERATION",
            "project_id": str(project_id),
            "current_agent": "PLANNING",
            "workflow_status": "RUNNING",
            "progress_percentage": 0,
            "iteration": 1,
            "requirements": requirements,
            "technology_stack": technology_stack,
            "estimated_files": 0,
            "generated_files": [],
            "project_file_ids": [],
            "finding_ids": [],
            "pending_fix_request_ids": [],
            "approved_fix_request_ids": [],
            "agent_execution_ids": {},
        }

        result = await graph.ainvoke(
            initial_state,
            config={
                "configurable": {
                    "thread_id": str(project_id),
                    "lifecycle": lifecycle,
                }
            },
        )

        logger.info(
            "Generation workflow finished for project %s. Status: %s",
            project_id,
            result.get("workflow_status"),
        )

    except Exception:
        logger.exception(
            "Generation workflow failed for project %s",
            project_id,
        )

        try:
            await lifecycle.fail_workflow()
        except Exception:
            logger.exception(
                "Could not persist workflow failure for project %s",
                project_id,
            )


@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
def start_project_generation(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start generation for an existing generated project.
    """

    project = _get_owned_project(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    if project.project_type != ProjectType.GENERATED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generation is only available for generated projects.",
        )

    if project.status in ACTIVE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A generation workflow is already active.",
        )

    # Initially, require a clean project.
    # Retrying failed or completed projects needs a separate
    # regeneration/cleanup workflow to avoid file collisions.
    if project.status != ProjectStatus.CREATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Generation can only be started for a newly created "
                "project. Regeneration is not yet supported."
            ),
        )

    if not project.description or not project.description.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project requirements are missing. Add a description first.",
        )

    if not project.technology_stack:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project technology stack is missing.",
        )

    if not hasattr(request.app.state, "checkpointer"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow checkpointing is not initialized.",
        )

    workflow_id = str(uuid4())

    # Mark the project before scheduling the background task.
    update_project_status(
        db=db,
        project_id=project_id,
        status=ProjectStatus.PLANNING,
    )

    db.commit()

    background_tasks.add_task(
        _run_generation,
        project_id=project_id,
        user_id=current_user.id,
        requirements=project.description,
        technology_stack=project.technology_stack,
        workflow_id=workflow_id,
        checkpointer=request.app.state.checkpointer,
    )

    return {
        "message": "Project generation has been accepted.",
        "project_id": str(project_id),
        "workflow_id": workflow_id,
        "status": ProjectStatus.PLANNING.value,
    }


@router.get("/generation")
def get_project_generation(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve the current generation plan and agent executions.
    """

    project = _get_owned_project(
        db=db,
        user_id=current_user.id,
        project_id=project_id,
    )

    plan = db.scalar(
        select(GenerationPlan).where(
            GenerationPlan.project_id == project_id
        )
    )

    executions = db.scalars(
        select(AgentExecution)
        .where(AgentExecution.project_id == project_id)
        .order_by(AgentExecution.created_at.asc())
    ).all()

    plan_data = None

    if plan is not None:
        plan_data = {
            "id": str(plan.id),
            "requirements": plan.requirements,
            "architecture": plan.architecture,
            "folder_structure": plan.folder_structure,
            "implementation_plan": plan.implementation_plan,
            "estimated_files": plan.estimated_files,
            "status": plan.status.value,
            "created_at": plan.created_at,
            "updated_at": plan.updated_at,
        }

    execution_data = [
        {
            "id": str(execution.id),
            "agent_type": execution.agent_type.value,
            "status": execution.status.value,
            "execution_number": execution.execution_number,
            "progress_percentage": execution.progress_percentage,
            "input_data": execution.input_data,
            "output_data": execution.output_data,
            "error_message": execution.error_message,
            "model_name": execution.model_name,
            "started_at": execution.started_at,
            "completed_at": execution.completed_at,
            "created_at": execution.created_at,
        }
        for execution in executions
    ]

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "project_status": project.status.value,
        "project_type": project.project_type.value,
        "generation_plan": plan_data,
        "agent_executions": execution_data,
    }