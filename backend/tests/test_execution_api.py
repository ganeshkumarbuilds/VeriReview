import os
import uuid

import httpx
import pytest

from sqlalchemy import select

from app.database.connection import SessionLocal
from app.models.agent_execution import AgentType
from app.models.generation_plan import (
    GenerationPlanStatus,
)
from app.models.project import (
    Project,
    ProjectStatus,
    ProjectType,
)
from app.models.user import User
from app.services.agent_executions import create_agent_execution
from app.services.generation_persistence import (
    save_generation_plan,
    update_project_status,
)


BASE_URL = "http://127.0.0.1:8000"

EMAIL = os.getenv("VERIREVIEW_TEST_EMAIL")
PASSWORD = os.getenv("VERIREVIEW_TEST_PASSWORD")


@pytest.fixture
def api_client():
    if not EMAIL or not PASSWORD:
        pytest.fail(
            "Test credentials are missing from environment variables."
        )

    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
    ) as client:

        response = client.post(
            "/api/v1/auth/login",
            json={
                "identifier": EMAIL,
                "password": PASSWORD,
            },
        )

        assert response.status_code == 200

        token = response.json()["access_token"]

        client.headers.update({
            "Authorization": f"Bearer {token}"
        })

        yield client


@pytest.fixture
def api_project(api_client):
    response = api_client.post(
        "/api/v1/projects",
        json={
            "name": f"Generation API Test {uuid.uuid4().hex[:8]}",
            "description": "Create a simple FastAPI task management application.",
            "project_type": "GENERATED",
            "technology_stack": "Python, FastAPI, PostgreSQL",
        },
    )

    assert response.status_code == 201

    project_id = response.json()["id"]

    try:
        yield project_id

    finally:
        response = api_client.delete(
            f"/api/v1/projects/{project_id}"
        )

        assert response.status_code == 204


@pytest.fixture
def uploaded_project(api_client):
    response = api_client.post(
        "/api/v1/projects",
        json={
            "name": f"Uploaded Project {uuid.uuid4().hex[:8]}",
            "description": "Existing uploaded application.",
            "project_type": "UPLOADED",
            "technology_stack": "Python",
        },
    )

    assert response.status_code == 201

    project_id = response.json()["id"]

    try:
        yield project_id

    finally:
        response = api_client.delete(
            f"/api/v1/projects/{project_id}"
        )

        assert response.status_code == 204


@pytest.fixture
def project_without_requirements(api_client):
    response = api_client.post(
        "/api/v1/projects",
        json={
            "name": f"Missing Requirements {uuid.uuid4().hex[:8]}",
            "description": None,
            "project_type": "GENERATED",
            "technology_stack": "Python, FastAPI",
        },
    )

    assert response.status_code == 201

    project_id = response.json()["id"]

    try:
        yield project_id

    finally:
        response = api_client.delete(
            f"/api/v1/projects/{project_id}"
        )

        assert response.status_code == 204


@pytest.fixture
def project_without_stack(api_client):
    response = api_client.post(
        "/api/v1/projects",
        json={
            "name": f"Missing Stack {uuid.uuid4().hex[:8]}",
            "description": "Create a simple web application.",
            "project_type": "GENERATED",
            "technology_stack": None,
        },
    )

    assert response.status_code == 201

    project_id = response.json()["id"]

    try:
        yield project_id

    finally:
        response = api_client.delete(
            f"/api/v1/projects/{project_id}"
        )

        assert response.status_code == 204


@pytest.fixture
def generation_records(api_project):
    db = SessionLocal()

    try:
        project_uuid = uuid.UUID(api_project)

        plan = save_generation_plan(
            db=db,
            project_id=project_uuid,
            requirements="Create a FastAPI task management application.",
            plan_data={
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
                        "Configure PostgreSQL",
                    ]
                },
                "estimated_files": 1,
            },
            status=GenerationPlanStatus.IN_PROGRESS,
        )

        execution = create_agent_execution(
            db=db,
            project_id=project_uuid,
            agent_type=AgentType.PLANNING,
            input_data={
                "requirements": "Create a FastAPI application."
            },
            model_name="test-model",
        )

        db.commit()

        yield {
            "plan_id": str(plan.id),
            "execution_id": str(execution.id),
        }

    finally:
        db.close()


def test_generation_api_requires_authentication():
    project_id = str(uuid.uuid4())

    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
    ) as client:

        get_response = client.get(
            f"/api/v1/projects/{project_id}/generation"
        )

        post_response = client.post(
            f"/api/v1/projects/{project_id}/generate"
        )

        assert get_response.status_code in (401, 403)
        assert post_response.status_code in (401, 403)


def test_generation_rejects_unowned_project(api_client):
    project_id = str(uuid.uuid4())

    response = api_client.post(
        f"/api/v1/projects/{project_id}/generate"
    )

    assert response.status_code == 404


def test_generation_rejects_uploaded_project(
    api_client,
    uploaded_project,
):
    response = api_client.post(
        f"/api/v1/projects/{uploaded_project}/generate"
    )

    assert response.status_code == 400

    assert "generated projects" in response.json()["detail"].lower()


def test_generation_rejects_missing_requirements(
    api_client,
    project_without_requirements,
):
    response = api_client.post(
        f"/api/v1/projects/{project_without_requirements}/generate"
    )

    assert response.status_code == 400

    assert "requirements" in response.json()["detail"].lower()


def test_generation_rejects_missing_technology_stack(
    api_client,
    project_without_stack,
):
    response = api_client.post(
        f"/api/v1/projects/{project_without_stack}/generate"
    )

    assert response.status_code == 400

    assert "technology stack" in response.json()["detail"].lower()


def test_generation_rejects_duplicate_active_workflow(
    api_client,
    api_project,
):
    db = SessionLocal()

    try:
        update_project_status(
            db=db,
            project_id=uuid.UUID(api_project),
            status=ProjectStatus.GENERATING,
        )

        db.commit()

    finally:
        db.close()

    response = api_client.post(
        f"/api/v1/projects/{api_project}/generate"
    )

    assert response.status_code == 409

    assert "already active" in response.json()["detail"].lower()


def test_generation_status_rejects_unowned_project(api_client):
    response = api_client.get(
        f"/api/v1/projects/{uuid.uuid4()}/generation"
    )

    assert response.status_code == 404


def test_generation_status_without_plan(
    api_client,
    api_project,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/generation"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["project_id"] == api_project
    assert data["project_type"] == "GENERATED"
    assert data["project_status"] == "CREATED"
    assert data["generation_plan"] is None
    assert data["agent_executions"] == []


def test_generation_status_returns_plan_and_executions(
    api_client,
    api_project,
    generation_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/generation"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["project_id"] == api_project

    plan = data["generation_plan"]

    assert plan is not None
    assert plan["id"] == generation_records["plan_id"]
    assert plan["status"] == "IN_PROGRESS"
    assert plan["estimated_files"] == 1

    assert len(data["agent_executions"]) == 1

    execution = data["agent_executions"][0]

    assert execution["id"] == generation_records["execution_id"]
    assert execution["agent_type"] == "PLANNING"
    assert execution["status"] == "PENDING"
    assert execution["model_name"] == "test-model"