import uuid

import pytest

from app.database.connection import SessionLocal
from app.models.agent_execution import (
    AgentExecutionStatus,
    AgentType,
)
from app.models.project import Project, ProjectType
from app.models.user import User
from app.services.agent_executions import (
    AgentExecutionNotFoundError,
    InvalidExecutionStateError,
    cancel_agent_execution,
    complete_agent_execution,
    create_agent_execution,
    fail_agent_execution,
    get_agent_execution,
    list_agent_executions,
    start_agent_execution,
    update_agent_execution_progress,
)


@pytest.fixture
def db_session():
    """Provide a database session with automatic rollback."""

    db = SessionLocal()
    transaction = db.begin()

    try:
        yield db
    finally:
        transaction.rollback()
        db.close()


@pytest.fixture
def test_project(db_session):
    """Create a temporary user and project."""

    unique_id = uuid.uuid4().hex

    user = User(
        email=f"agent-test-{unique_id}@example.com",
        username=f"agenttest_{unique_id[:20]}",
        hashed_password="test-only-password-hash",
    )

    db_session.add(user)
    db_session.flush()

    project = Project(
        user_id=user.id,
        name=f"Agent Test Project {unique_id[:8]}",
        project_type=ProjectType.GENERATED,
        technology_stack="Python, FastAPI",
    )

    db_session.add(project)
    db_session.flush()

    return project


def test_create_agent_execution(db_session, test_project):
    execution = create_agent_execution(
        db=db_session,
        project_id=test_project.id,
        agent_type=AgentType.PLANNING,
        input_data={"requirements": "Create a music application"},
        model_name="test-model",
    )

    assert execution.id is not None
    assert execution.project_id == test_project.id
    assert execution.agent_type == AgentType.PLANNING
    assert execution.status == AgentExecutionStatus.PENDING
    assert execution.progress_percentage == 0
    assert execution.model_name == "test-model"


def test_create_execution_rejects_missing_project(db_session):
    with pytest.raises(ValueError, match="Project does not exist"):
        create_agent_execution(
            db=db_session,
            project_id=uuid.uuid4(),
            agent_type=AgentType.CODING,
        )


def test_execution_number_must_be_positive(db_session, test_project):
    with pytest.raises(ValueError, match="at least 1"):
        create_agent_execution(
            db=db_session,
            project_id=test_project.id,
            agent_type=AgentType.CODING,
            execution_number=0,
        )


def test_start_agent_execution(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.PLANNING,
    )

    started = start_agent_execution(db_session, execution.id)

    assert started.status == AgentExecutionStatus.RUNNING
    assert started.started_at is not None


def test_execution_cannot_be_started_twice(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.PLANNING,
    )

    start_agent_execution(db_session, execution.id)

    with pytest.raises(InvalidExecutionStateError):
        start_agent_execution(db_session, execution.id)


def test_update_execution_progress(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    start_agent_execution(db_session, execution.id)

    updated = update_agent_execution_progress(
        db_session,
        execution.id,
        50,
        output_data={"files_created": 5},
    )

    assert updated.progress_percentage == 50
    assert updated.output_data == {"files_created": 5}


def test_execution_progress_cannot_decrease(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    start_agent_execution(db_session, execution.id)

    update_agent_execution_progress(
        db_session,
        execution.id,
        60,
    )

    with pytest.raises(ValueError, match="cannot decrease"):
        update_agent_execution_progress(
            db_session,
            execution.id,
            40,
        )


@pytest.mark.parametrize("progress", [-1, 101, True, 25.5])
def test_invalid_progress_is_rejected(
    db_session,
    test_project,
    progress,
):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    start_agent_execution(db_session, execution.id)

    with pytest.raises(ValueError):
        update_agent_execution_progress(
            db_session,
            execution.id,
            progress,
        )


def test_progress_requires_running_execution(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    with pytest.raises(InvalidExecutionStateError):
        update_agent_execution_progress(
            db_session,
            execution.id,
            30,
        )


def test_complete_agent_execution(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.PLANNING,
    )

    start_agent_execution(db_session, execution.id)

    completed = complete_agent_execution(
        db_session,
        execution.id,
        output_data={"plan": "Application architecture"},
    )

    assert completed.status == AgentExecutionStatus.COMPLETED
    assert completed.progress_percentage == 100
    assert completed.completed_at is not None
    assert completed.output_data == {
        "plan": "Application architecture"
    }


def test_completed_execution_cannot_be_restarted(
    db_session,
    test_project,
):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.PLANNING,
    )

    start_agent_execution(db_session, execution.id)
    complete_agent_execution(db_session, execution.id)

    with pytest.raises(InvalidExecutionStateError):
        start_agent_execution(db_session, execution.id)


def test_fail_agent_execution(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.VERIFYING,
    )

    start_agent_execution(db_session, execution.id)

    failed = fail_agent_execution(
        db_session,
        execution.id,
        "Verification process encountered an error.",
    )

    assert failed.status == AgentExecutionStatus.FAILED
    assert failed.error_message == (
        "Verification process encountered an error."
    )
    assert failed.completed_at is not None


def test_failure_requires_error_message(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.VERIFYING,
    )

    start_agent_execution(db_session, execution.id)

    with pytest.raises(ValueError):
        fail_agent_execution(
            db_session,
            execution.id,
            "   ",
        )


def test_failed_execution_cannot_be_modified(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.VERIFYING,
    )

    start_agent_execution(db_session, execution.id)
    fail_agent_execution(db_session, execution.id, "Test failure")

    with pytest.raises(InvalidExecutionStateError):
        complete_agent_execution(db_session, execution.id)


def test_cancel_pending_execution(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    cancelled = cancel_agent_execution(
        db_session,
        execution.id,
    )

    assert cancelled.status == AgentExecutionStatus.CANCELLED
    assert cancelled.completed_at is not None


def test_cancel_running_execution(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    start_agent_execution(db_session, execution.id)

    cancelled = cancel_agent_execution(
        db_session,
        execution.id,
    )

    assert cancelled.status == AgentExecutionStatus.CANCELLED


def test_cancelled_execution_cannot_be_restarted(
    db_session,
    test_project,
):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    cancel_agent_execution(db_session, execution.id)

    with pytest.raises(InvalidExecutionStateError):
        start_agent_execution(db_session, execution.id)


def test_get_agent_execution(db_session, test_project):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.REVIEW,
    )

    retrieved = get_agent_execution(db_session, execution.id)

    assert retrieved is not None
    assert retrieved.id == execution.id


def test_get_missing_execution_returns_none(db_session):
    retrieved = get_agent_execution(
        db_session,
        uuid.uuid4(),
    )

    assert retrieved is None


def test_list_agent_executions(db_session, test_project):
    first = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.PLANNING,
    )

    second = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    executions = list_agent_executions(
        db_session,
        test_project.id,
    )

    execution_ids = {item.id for item in executions}

    assert first.id in execution_ids
    assert second.id in execution_ids


def test_missing_execution_raises_not_found(db_session):
    with pytest.raises(AgentExecutionNotFoundError):
        start_agent_execution(
            db_session,
            uuid.uuid4(),
        )