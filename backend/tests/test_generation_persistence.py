import uuid

import pytest

from app.database.connection import SessionLocal
from app.models.agent_execution import (
    AgentExecutionStatus,
    AgentType,
)
from app.models.execution_event import ExecutionEventType
from app.models.generation_plan import (
    GenerationPlanStatus,
)
from app.models.project import (
    Project,
    ProjectStatus,
    ProjectType,
)
from app.models.user import User
from app.services import generated_files
from app.services.generation_persistence import (
    save_generation_plan,
    update_generation_plan_status,
    update_project_status,
    record_agent_started,
    record_agent_completed,
    record_agent_failed,
    persist_generated_files,
)


@pytest.fixture
def db_session():
    db = SessionLocal()
    transaction = db.begin()

    try:
        yield db
    finally:
        transaction.rollback()
        db.close()


@pytest.fixture
def test_project(db_session):
    unique_id = uuid.uuid4().hex

    user = User(
        email=f"generation-test-{unique_id}@example.com",
        username=f"gentest_{unique_id[:20]}",
        hashed_password="test-only-password-hash",
    )

    db_session.add(user)
    db_session.flush()

    project = Project(
        user_id=user.id,
        name=f"Generation Test {unique_id[:8]}",
        project_type=ProjectType.GENERATED,
        technology_stack="Python, FastAPI",
    )

    db_session.add(project)
    db_session.flush()

    return {
        "user": user,
        "project": project,
    }


@pytest.fixture
def plan_data():
    return {
        "architecture": {
            "backend": "FastAPI",
            "database": "PostgreSQL",
        },
        "folder_structure": {
            "files": [
                {
                    "path": "main.py",
                    "purpose": "Application entry point",
                }
            ]
        },
        "implementation_plan": {
            "steps": [
                "Create FastAPI application",
                "Configure database",
            ]
        },
        "estimated_files": 1,
    }


def test_save_generation_plan(
    db_session,
    test_project,
    plan_data,
):
    project = test_project["project"]

    plan = save_generation_plan(
        db=db_session,
        project_id=project.id,
        requirements="Create a task management application",
        plan_data=plan_data,
    )

    assert plan.id is not None
    assert plan.project_id == project.id
    assert plan.requirements == (
        "Create a task management application"
    )
    assert plan.architecture == plan_data["architecture"]
    assert plan.folder_structure == plan_data["folder_structure"]
    assert plan.implementation_plan == plan_data["implementation_plan"]
    assert plan.estimated_files == 1
    assert plan.status == GenerationPlanStatus.IN_PROGRESS


def test_save_generation_plan_updates_existing_plan(
    db_session,
    test_project,
    plan_data,
):
    project = test_project["project"]

    first_plan = save_generation_plan(
        db_session,
        project.id,
        "Original requirements",
        plan_data,
    )

    original_id = first_plan.id

    updated_data = {
        **plan_data,
        "estimated_files": 3,
    }

    updated_plan = save_generation_plan(
        db_session,
        project.id,
        "Updated requirements",
        updated_data,
    )

    assert updated_plan.id == original_id
    assert updated_plan.requirements == "Updated requirements"
    assert updated_plan.estimated_files == 3


def test_update_generation_plan_status(
    db_session,
    test_project,
    plan_data,
):
    project = test_project["project"]

    save_generation_plan(
        db_session,
        project.id,
        "Create an application",
        plan_data,
    )

    updated = update_generation_plan_status(
        db_session,
        project.id,
        GenerationPlanStatus.COMPLETED,
    )

    assert updated.status == GenerationPlanStatus.COMPLETED


def test_update_generation_plan_status_rejects_missing_plan(
    db_session,
    test_project,
):
    with pytest.raises(
        ValueError,
        match="Generation plan not found",
    ):
        update_generation_plan_status(
            db_session,
            test_project["project"].id,
            GenerationPlanStatus.COMPLETED,
        )


def test_update_project_status(
    db_session,
    test_project,
):
    project = test_project["project"]

    updated = update_project_status(
        db_session,
        project.id,
        ProjectStatus.GENERATING,
    )

    assert updated.status == ProjectStatus.GENERATING


def test_record_agent_started(
    db_session,
    test_project,
):
    project = test_project["project"]

    execution = record_agent_started(
        db=db_session,
        project_id=project.id,
        agent_type=AgentType.PLANNING,
        input_data={
            "requirements": "Create an application",
        },
        model_name="test-model",
    )

    assert execution.id is not None
    assert execution.project_id == project.id
    assert execution.agent_type == AgentType.PLANNING
    assert execution.status == AgentExecutionStatus.RUNNING
    assert execution.started_at is not None

    assert execution.input_data == {
        "requirements": "Create an application",
    }

    assert execution.model_name == "test-model"

    events = list(
        execution.events
    )

    assert any(
        event.event_type == ExecutionEventType.AGENT_STARTED
        for event in events
    )


def test_record_agent_completed(
    db_session,
    test_project,
):
    project = test_project["project"]

    execution = record_agent_started(
        db_session,
        project.id,
        AgentType.PLANNING,
    )

    completed = record_agent_completed(
        db=db_session,
        execution_id=execution.id,
        output_data={
            "architecture": "FastAPI application",
        },
    )

    assert completed.status == AgentExecutionStatus.COMPLETED
    assert completed.progress_percentage == 100
    assert completed.completed_at is not None

    assert completed.output_data == {
        "architecture": "FastAPI application",
    }

    assert any(
        event.event_type == ExecutionEventType.AGENT_COMPLETED
        for event in completed.events
    )


def test_record_agent_failed(
    db_session,
    test_project,
):
    project = test_project["project"]

    execution = record_agent_started(
        db_session,
        project.id,
        AgentType.CODING,
    )

    failed = record_agent_failed(
        db=db_session,
        execution_id=execution.id,
        error_message="Code generation failed",
    )

    assert failed.status == AgentExecutionStatus.FAILED
    assert failed.error_message == "Code generation failed"
    assert failed.completed_at is not None

    assert any(
        event.event_type == ExecutionEventType.AGENT_FAILED
        for event in failed.events
    )


def test_persist_generated_files(
    db_session,
    test_project,
    tmp_path,
    monkeypatch,
):
    project = test_project["project"]
    user = test_project["user"]

    project_directory = tmp_path / str(project.id)
    project_directory.mkdir()

    monkeypatch.setattr(
        generated_files,
        "get_project_directory",
        lambda project_id: project_directory,
    )

    files = [
        {
            "file_path": "main.py",
            "content": "print('VeriReview')",
        },
        {
            "file_path": "src/config.py",
            "content": "DEBUG = True",
        },
    ]

    persisted = persist_generated_files(
        db=db_session,
        user_id=user.id,
        project_id=project.id,
        generated_files=files,
    )

    assert len(persisted) == 2

    assert (
        project_directory / "main.py"
    ).read_text(encoding="utf-8") == "print('VeriReview')"

    assert (
        project_directory / "src" / "config.py"
    ).read_text(encoding="utf-8") == "DEBUG = True"

    assert all(
        item.project_id == project.id
        for item in persisted
    )

    assert all(
        item.file_size > 0
        for item in persisted
    )


def test_persist_generated_files_rejects_invalid_content(
    db_session,
    test_project,
):
    project = test_project["project"]
    user = test_project["user"]

    with pytest.raises(
        ValueError,
        match="content must be text",
    ):
        persist_generated_files(
            db=db_session,
            user_id=user.id,
            project_id=project.id,
            generated_files=[
                {
                    "file_path": "main.py",
                    "content": b"invalid",
                }
            ],
        )