import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.database.connection import SessionLocal
from app.models.agent_execution import (
    AgentExecution,
    AgentExecutionStatus,
    AgentType,
)
from app.models.execution_event import (
    ExecutionEvent,
    ExecutionEventType,
)
from app.models.project import Project, ProjectType
from app.models.user import User
from app.workflows.generation_lifecycle import GenerationLifecycle


def run_async(coroutine):
    return asyncio.run(
        coroutine,
        loop_factory=asyncio.SelectorEventLoop,
    )


@pytest.fixture
def test_project():
    """
    Create a committed project because GenerationLifecycle
    uses independent database sessions.
    """

    db = SessionLocal()
    unique_id = uuid.uuid4().hex

    user = User(
        email=f"lifecycle-{unique_id}@example.com",
        username=f"lifecycle_{unique_id[:20]}",
        hashed_password="test-only-password-hash",
    )

    db.add(user)
    db.flush()

    project = Project(
        user_id=user.id,
        name=f"Lifecycle Test {unique_id[:8]}",
        project_type=ProjectType.GENERATED,
        technology_stack="Python, FastAPI",
    )

    db.add(project)
    db.commit()

    project_id = project.id
    user_id = user.id

    db.close()

    yield project_id

    cleanup_db = SessionLocal()

    try:
        cleanup_db.query(Project).filter(
            Project.id == project_id
        ).delete(synchronize_session=False)

        cleanup_db.query(User).filter(
            User.id == user_id
        ).delete(synchronize_session=False)

        cleanup_db.commit()

    except Exception:
        cleanup_db.rollback()
        raise

    finally:
        cleanup_db.close()


def get_execution(execution_id):
    db = SessionLocal()

    try:
        return db.get(
            AgentExecution,
            uuid.UUID(str(execution_id)),
        )

    finally:
        db.close()


def get_events(execution_id):
    db = SessionLocal()

    try:
        statement = (
            select(ExecutionEvent)
            .where(
                ExecutionEvent.agent_execution_id
                == uuid.UUID(str(execution_id))
            )
            .order_by(ExecutionEvent.created_at)
        )

        return list(db.scalars(statement).all())

    finally:
        db.close()


def test_agent_started_creates_execution_and_event(test_project):
    lifecycle = GenerationLifecycle(test_project)

    execution_id = run_async(
        lifecycle.agent_started(
            agent_type="PLANNING",
            input_data={
                "requirements": "Build a Python application",
            },
        )
    )

    execution = get_execution(execution_id)
    events = get_events(execution_id)

    assert execution is not None
    assert execution.project_id == test_project
    assert execution.agent_type == AgentType.PLANNING
    assert execution.status == AgentExecutionStatus.RUNNING
    assert execution.started_at is not None

    assert len(events) == 1
    assert events[0].event_type == ExecutionEventType.AGENT_STARTED


def test_agent_progress_updates_execution_and_event(test_project):
    lifecycle = GenerationLifecycle(test_project)

    execution_id = run_async(
        lifecycle.agent_started(
            agent_type="CODING",
            input_data={"requirements": "Build an application"},
        )
    )

    run_async(
        lifecycle.agent_progress(
            agent_type="CODING",
            execution_id=execution_id,
            progress=50,
            output_data={
                "generated_files": 2,
                "latest_file": "main.py",
            },
        )
    )

    execution = get_execution(execution_id)
    events = get_events(execution_id)

    assert execution.progress_percentage == 50
    assert execution.output_data["generated_files"] == 2

    assert len(events) == 2
    assert events[1].event_type == ExecutionEventType.AGENT_PROGRESS
    assert events[1].event_data["progress"] == 50


def test_agent_completed_updates_execution_and_event(test_project):
    lifecycle = GenerationLifecycle(test_project)

    execution_id = run_async(
        lifecycle.agent_started(
            agent_type="PLANNING",
            input_data={"requirements": "Build an application"},
        )
    )

    output_data = {
        "architecture": {"overview": "Modular"},
        "estimated_files": 3,
    }

    run_async(
        lifecycle.agent_completed(
            agent_type="PLANNING",
            execution_id=execution_id,
            output_data=output_data,
        )
    )

    execution = get_execution(execution_id)
    events = get_events(execution_id)

    assert execution.status == AgentExecutionStatus.COMPLETED
    assert execution.progress_percentage == 100
    assert execution.completed_at is not None
    assert execution.output_data == output_data

    assert events[-1].event_type == ExecutionEventType.AGENT_COMPLETED


def test_agent_failed_updates_execution_and_event(test_project):
    lifecycle = GenerationLifecycle(test_project)

    execution_id = run_async(
        lifecycle.agent_started(
            agent_type="VERIFYING",
            input_data={"files": ["main.py"]},
        )
    )

    error_message = "Verification process failed."

    run_async(
        lifecycle.agent_failed(
            agent_type="VERIFYING",
            execution_id=execution_id,
            error_message=error_message,
        )
    )

    execution = get_execution(execution_id)
    events = get_events(execution_id)

    assert execution.status == AgentExecutionStatus.FAILED
    assert execution.error_message == error_message
    assert execution.completed_at is not None

    assert events[-1].event_type == ExecutionEventType.AGENT_FAILED
    assert events[-1].event_data["error"] == error_message


def test_agent_execution_numbers_increase(test_project):
    lifecycle = GenerationLifecycle(test_project)

    first_id = run_async(
        lifecycle.agent_started(
            agent_type="CODING",
            input_data={"attempt": 1},
        )
    )

    second_id = run_async(
        lifecycle.agent_started(
            agent_type="CODING",
            input_data={"attempt": 2},
        )
    )

    first = get_execution(first_id)
    second = get_execution(second_id)

    assert second.execution_number == first.execution_number + 1


def test_different_agent_types_have_independent_execution_numbers(
    test_project,
):
    lifecycle = GenerationLifecycle(test_project)

    planning_id = run_async(
        lifecycle.agent_started(
            agent_type="PLANNING",
            input_data={},
        )
    )

    coding_id = run_async(
        lifecycle.agent_started(
            agent_type="CODING",
            input_data={},
        )
    )

    planning = get_execution(planning_id)
    coding = get_execution(coding_id)

    assert planning.execution_number == 1
    assert coding.execution_number == 1