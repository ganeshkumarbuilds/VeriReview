import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.database.connection import SessionLocal
from app.models.agent_execution import AgentExecution, AgentType
from app.models.execution_event import ExecutionEventType
from app.models.finding import Finding
from app.models.generation_plan import (
    GenerationPlan,
    GenerationPlanStatus,
)
from app.models.project import ProjectStatus
from app.models.review import ReviewType
from app.services.agent_executions import (
    create_agent_execution,
    start_agent_execution,
    update_agent_execution_progress,
    complete_agent_execution,
    fail_agent_execution,
)
from app.services.execution_events import create_execution_event
from app.services.generation_persistence import (
    save_generation_plan,
    update_generation_plan_status,
    update_project_status,
    persist_generated_files,
)
from app.services.review_persistence import (
    persist_review as persist_review_record,
)


logger = logging.getLogger(__name__)


class GenerationLifecycle:
    """
    Persists agent executions and generation workflow changes.

    Every callback uses a fresh database session.
    No database session remains open while an LLM runs.
    """

    def __init__(
        self,
        project_id: UUID | str,
        user_id: UUID | str | None = None,
    ):
        self.project_id = UUID(str(project_id))
        self.user_id = (
            UUID(str(user_id))
            if user_id is not None
            else None
        )

    def _run_db(self, operation):
        """Execute one database operation in its own transaction."""

        db = SessionLocal()

        try:
            result = operation(db)
            db.commit()
            return result

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    async def _execute(self, operation):
        """Run synchronous SQLAlchemy work outside the event loop."""

        return await asyncio.to_thread(
            self._run_db,
            operation,
        )

    async def set_project_status(
        self,
        status: ProjectStatus | str,
    ) -> None:
        """Persist the current generation workflow status."""

        project_status = ProjectStatus(status)

        def operation(db):
            update_project_status(
                db=db,
                project_id=self.project_id,
                status=project_status,
            )

        await self._execute(operation)

        logger.info(
            "Project %s status changed to %s",
            self.project_id,
            project_status.value,
        )

    async def save_plan(
        self,
        requirements: str,
        plan_data: dict[str, Any],
    ) -> str:
        """Persist the Planning Agent's generated plan."""

        def operation(db):
            plan = save_generation_plan(
                db=db,
                project_id=self.project_id,
                requirements=requirements,
                plan_data=plan_data,
                status=GenerationPlanStatus.IN_PROGRESS,
            )

            update_project_status(
                db=db,
                project_id=self.project_id,
                status=ProjectStatus.GENERATING,
            )

            return str(plan.id)

        plan_id = await self._execute(operation)

        logger.info(
            "Generation plan persisted for project %s: %s",
            self.project_id,
            plan_id,
        )

        return plan_id

    async def persist_files(
        self,
        generated_files: list[dict[str, Any]],
    ) -> list[str]:
        """Persist generated files and their database metadata."""

        if self.user_id is None:
            raise ValueError(
                "User ID is required to persist generated files."
            )

        def operation(db):
            files = persist_generated_files(
                db=db,
                user_id=self.user_id,
                project_id=self.project_id,
                generated_files=generated_files,
            )

            return [str(file.id) for file in files]

        file_ids = await self._execute(operation)

        logger.info(
            "Persisted %s generated files for project %s",
            len(file_ids),
            self.project_id,
        )

        return file_ids

    async def persist_review(
        self,
        verification_results: dict[str, Any],
        review_data: dict[str, Any],
        review_type: ReviewType | str = ReviewType.INITIAL,
    ) -> dict[str, Any]:
        """Persist a review and its findings in one transaction."""

        selected_review_type = ReviewType(review_type)

        def operation(db):
            review = persist_review_record(
                db=db,
                project_id=self.project_id,
                verification_results=verification_results,
                review_data=review_data,
                review_type=selected_review_type,
            )

            findings = db.scalars(
                select(Finding).where(
                    Finding.review_id == review.id
                )
            ).all()

            return {
                "review_id": str(review.id),
                "finding_ids": [
                    str(finding.id)
                    for finding in findings
                ],
            }

        result = await self._execute(operation)

        logger.info(
            "Persisted review %s with %s findings for project %s",
            result["review_id"],
            len(result["finding_ids"]),
            self.project_id,
        )

        return result

    async def complete_workflow(self) -> None:
        """Mark the project and generation plan as completed."""

        def operation(db):
            update_generation_plan_status(
                db=db,
                project_id=self.project_id,
                status=GenerationPlanStatus.COMPLETED,
            )

            update_project_status(
                db=db,
                project_id=self.project_id,
                status=ProjectStatus.COMPLETED,
            )

        await self._execute(operation)

        logger.info(
            "Generation workflow completed for project %s",
            self.project_id,
        )

    async def fail_workflow(self) -> None:
        """Mark the project and existing plan as failed."""

        def operation(db):
            update_project_status(
                db=db,
                project_id=self.project_id,
                status=ProjectStatus.FAILED,
            )

            plan = db.scalar(
                select(GenerationPlan).where(
                    GenerationPlan.project_id == self.project_id
                )
            )

            if plan is not None:
                update_generation_plan_status(
                    db=db,
                    project_id=self.project_id,
                    status=GenerationPlanStatus.FAILED,
                )

        await self._execute(operation)

        logger.error(
            "Generation workflow failed for project %s",
            self.project_id,
        )

    async def agent_started(
        self,
        agent_type: str,
        input_data: dict[str, Any],
    ) -> str:
        """Create and start an agent execution."""

        agent = AgentType(agent_type)

        def operation(db):
            latest_number = db.scalar(
                select(func.max(AgentExecution.execution_number)).where(
                    AgentExecution.project_id == self.project_id,
                    AgentExecution.agent_type == agent,
                )
            )

            execution_number = (latest_number or 0) + 1

            execution = create_agent_execution(
                db=db,
                project_id=self.project_id,
                agent_type=agent,
                execution_number=execution_number,
                input_data=input_data,
            )

            started = start_agent_execution(
                db,
                execution.id,
            )

            create_execution_event(
                db=db,
                project_id=self.project_id,
                agent_execution_id=started.id,
                event_type=ExecutionEventType.AGENT_STARTED,
                message=f"{agent.value.title()} Agent started.",
                event_data={
                    "agent": agent.value,
                    "execution_number": execution_number,
                },
            )

            return str(started.id)

        execution_id = await self._execute(operation)

        logger.info(
            "%s Agent execution started: %s",
            agent.value,
            execution_id,
        )

        return execution_id

    async def agent_progress(
        self,
        agent_type: str,
        execution_id: str,
        progress: int,
        output_data: dict[str, Any] | None = None,
    ) -> None:
        """Persist execution progress and its event."""

        agent = AgentType(agent_type)
        execution_uuid = UUID(str(execution_id))

        def operation(db):
            update_agent_execution_progress(
                db=db,
                execution_id=execution_uuid,
                progress_percentage=progress,
                output_data=output_data,
            )

            create_execution_event(
                db=db,
                project_id=self.project_id,
                agent_execution_id=execution_uuid,
                event_type=ExecutionEventType.AGENT_PROGRESS,
                message=(
                    f"{agent.value.title()} Agent progress: "
                    f"{progress}%."
                ),
                event_data={
                    "agent": agent.value,
                    "progress": progress,
                    "details": output_data or {},
                },
            )

        await self._execute(operation)

        logger.info(
            "%s Agent progress: %s%%",
            agent.value,
            progress,
        )

    async def agent_completed(
        self,
        agent_type: str,
        execution_id: str | None,
        output_data: dict[str, Any],
    ) -> None:
        """Mark an execution as completed."""

        if execution_id is None:
            raise ValueError(
                "Execution ID is required to complete an agent."
            )

        agent = AgentType(agent_type)
        execution_uuid = UUID(str(execution_id))

        def operation(db):
            complete_agent_execution(
                db=db,
                execution_id=execution_uuid,
                output_data=output_data,
            )

            create_execution_event(
                db=db,
                project_id=self.project_id,
                agent_execution_id=execution_uuid,
                event_type=ExecutionEventType.AGENT_COMPLETED,
                message=f"{agent.value.title()} Agent completed.",
                event_data={
                    "agent": agent.value,
                },
            )

        await self._execute(operation)

        logger.info(
            "%s Agent execution completed: %s",
            agent.value,
            execution_id,
        )

    async def agent_failed(
        self,
        agent_type: str,
        execution_id: str,
        error_message: str,
    ) -> None:
        """Mark an execution as failed."""

        agent = AgentType(agent_type)
        execution_uuid = UUID(str(execution_id))

        def operation(db):
            fail_agent_execution(
                db=db,
                execution_id=execution_uuid,
                error_message=error_message,
            )

            create_execution_event(
                db=db,
                project_id=self.project_id,
                agent_execution_id=execution_uuid,
                event_type=ExecutionEventType.AGENT_FAILED,
                message=f"{agent.value.title()} Agent failed.",
                event_data={
                    "agent": agent.value,
                    "error": error_message,
                },
            )

        await self._execute(operation)

        logger.error(
            "%s Agent execution failed: %s",
            agent.value,
            execution_id,
        )