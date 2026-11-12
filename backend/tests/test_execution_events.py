import uuid

import pytest

from app.database.connection import SessionLocal
from app.models.agent_execution import AgentType
from app.models.execution_event import ExecutionEventType
from app.models.project import Project, ProjectType
from app.models.user import User
from app.services.agent_executions import create_agent_execution
from app.services.execution_events import (
    create_execution_event,
    get_execution_event,
    list_execution_events,
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
        email=f"event-test-{unique_id}@example.com",
        username=f"eventtest_{unique_id[:20]}",
        hashed_password="test-only-password-hash",
    )

    db_session.add(user)
    db_session.flush()

    project = Project(
        user_id=user.id,
        name=f"Event Test Project {unique_id[:8]}",
        project_type=ProjectType.GENERATED,
        technology_stack="Python, FastAPI",
    )

    db_session.add(project)
    db_session.flush()

    return project


def create_another_project(db_session):
    """Create another project belonging to a different user."""

    unique_id = uuid.uuid4().hex

    user = User(
        email=f"another-event-{unique_id}@example.com",
        username=f"another_{unique_id[:20]}",
        hashed_password="test-only-password-hash",
    )

    db_session.add(user)
    db_session.flush()

    project = Project(
        user_id=user.id,
        name=f"Another Project {unique_id[:8]}",
        project_type=ProjectType.UPLOADED,
    )

    db_session.add(project)
    db_session.flush()

    return project


def test_create_execution_event(db_session, test_project):
    event = create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message="Planning Agent started.",
        event_data={"agent": "PLANNING"},
    )

    assert event.id is not None
    assert event.project_id == test_project.id
    assert event.event_type == ExecutionEventType.AGENT_STARTED
    assert event.message == "Planning Agent started."
    assert event.event_data == {"agent": "PLANNING"}


def test_create_event_with_agent_execution(
    db_session,
    test_project,
):
    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.PLANNING,
    )

    event = create_execution_event(
        db=db_session,
        project_id=test_project.id,
        agent_execution_id=execution.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message="Planning started.",
    )

    assert event.agent_execution_id == execution.id


def test_event_message_is_trimmed(db_session, test_project):
    event = create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_PROGRESS,
        message="  Agent progress updated.  ",
    )

    assert event.message == "Agent progress updated."


@pytest.mark.parametrize("message", ["", "   ", "\n\t"])
def test_empty_event_message_is_rejected(
    db_session,
    test_project,
    message,
):
    with pytest.raises(ValueError, match="cannot be empty"):
        create_execution_event(
            db=db_session,
            project_id=test_project.id,
            event_type=ExecutionEventType.AGENT_STARTED,
            message=message,
        )


def test_invalid_event_type_is_rejected(db_session, test_project):
    with pytest.raises(ValueError, match="Invalid execution event type"):
        create_execution_event(
            db=db_session,
            project_id=test_project.id,
            event_type="INVALID_EVENT",
            message="Test event.",
        )


def test_missing_project_is_rejected(db_session):
    with pytest.raises(ValueError, match="Project does not exist"):
        create_execution_event(
            db=db_session,
            project_id=uuid.uuid4(),
            event_type=ExecutionEventType.AGENT_STARTED,
            message="Test event.",
        )


def test_missing_agent_execution_is_rejected(
    db_session,
    test_project,
):
    with pytest.raises(ValueError, match="Agent execution does not exist"):
        create_execution_event(
            db=db_session,
            project_id=test_project.id,
            agent_execution_id=uuid.uuid4(),
            event_type=ExecutionEventType.AGENT_STARTED,
            message="Test event.",
        )


def test_cross_project_agent_execution_is_rejected(
    db_session,
    test_project,
):
    another_project = create_another_project(db_session)

    execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    with pytest.raises(
        ValueError,
        match="does not belong to this project",
    ):
        create_execution_event(
            db=db_session,
            project_id=another_project.id,
            agent_execution_id=execution.id,
            event_type=ExecutionEventType.AGENT_STARTED,
            message="Cross-project event.",
        )


def test_get_execution_event(db_session, test_project):
    event = create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_COMPLETED,
        message="Planning completed.",
    )

    retrieved = get_execution_event(
        db_session,
        test_project.id,
        event.id,
    )

    assert retrieved is not None
    assert retrieved.id == event.id


def test_event_cannot_be_retrieved_from_another_project(
    db_session,
    test_project,
):
    another_project = create_another_project(db_session)

    event = create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message="Planning started.",
    )

    retrieved = get_execution_event(
        db_session,
        another_project.id,
        event.id,
    )

    assert retrieved is None


def test_get_missing_event_returns_none(db_session, test_project):
    retrieved = get_execution_event(
        db_session,
        test_project.id,
        uuid.uuid4(),
    )

    assert retrieved is None


def test_list_execution_events(db_session, test_project):
    create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message="Planning started.",
    )

    create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_COMPLETED,
        message="Planning completed.",
    )

    result = list_execution_events(
        db_session,
        test_project.id,
    )

    assert result["total"] == 2
    assert len(result["events"]) == 2
    assert result["page"] == 1
    assert result["page_size"] == 50
    assert result["total_pages"] == 1


def test_filter_events_by_type(db_session, test_project):
    create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message="Planning started.",
    )

    create_execution_event(
        db=db_session,
        project_id=test_project.id,
        event_type=ExecutionEventType.AGENT_COMPLETED,
        message="Planning completed.",
    )

    result = list_execution_events(
        db_session,
        test_project.id,
        event_type=ExecutionEventType.AGENT_STARTED,
    )

    assert result["total"] == 1
    assert (
        result["events"][0].event_type
        == ExecutionEventType.AGENT_STARTED
    )


def test_filter_events_by_agent_execution(
    db_session,
    test_project,
):
    first_execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.PLANNING,
    )

    second_execution = create_agent_execution(
        db_session,
        test_project.id,
        AgentType.CODING,
    )

    create_execution_event(
        db=db_session,
        project_id=test_project.id,
        agent_execution_id=first_execution.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message="Planning started.",
    )

    create_execution_event(
        db=db_session,
        project_id=test_project.id,
        agent_execution_id=second_execution.id,
        event_type=ExecutionEventType.AGENT_STARTED,
        message="Coding started.",
    )

    result = list_execution_events(
        db_session,
        test_project.id,
        agent_execution_id=first_execution.id,
    )

    assert result["total"] == 1
    assert (
        result["events"][0].agent_execution_id
        == first_execution.id
    )


def test_agent_execution_filter_rejects_another_project(
    db_session,
    test_project,
):
    another_project = create_another_project(db_session)

    execution = create_agent_execution(
        db_session,
        another_project.id,
        AgentType.CODING,
    )

    with pytest.raises(
        ValueError,
        match="does not belong to this project",
    ):
        list_execution_events(
            db_session,
            test_project.id,
            agent_execution_id=execution.id,
        )


def test_event_pagination(db_session, test_project):
    for index in range(5):
        create_execution_event(
            db=db_session,
            project_id=test_project.id,
            event_type=ExecutionEventType.AGENT_PROGRESS,
            message=f"Progress event {index}.",
        )

    first_page = list_execution_events(
        db_session,
        test_project.id,
        page=1,
        page_size=2,
    )

    second_page = list_execution_events(
        db_session,
        test_project.id,
        page=2,
        page_size=2,
    )

    assert first_page["total"] == 5
    assert first_page["total_pages"] == 3
    assert len(first_page["events"]) == 2
    assert len(second_page["events"]) == 2

    first_ids = {event.id for event in first_page["events"]}
    second_ids = {event.id for event in second_page["events"]}

    assert first_ids.isdisjoint(second_ids)


@pytest.mark.parametrize(
    ("page", "page_size"),
    [
        (0, 10),
        (-1, 10),
        (1, 0),
        (1, 101),
    ],
)
def test_invalid_pagination_is_rejected(
    db_session,
    test_project,
    page,
    page_size,
):
    with pytest.raises(ValueError):
        list_execution_events(
            db_session,
            test_project.id,
            page=page,
            page_size=page_size,
        )


def test_listing_events_for_missing_project_is_rejected(
    db_session,
):
    with pytest.raises(ValueError, match="Project does not exist"):
        list_execution_events(
            db_session,
            uuid.uuid4(),
        )