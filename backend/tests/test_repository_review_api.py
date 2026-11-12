from types import SimpleNamespace
from uuid import uuid4

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import repository_review_api
from app.api.routes.auth import get_current_user
from app.database.connection import get_db
from app.models.project import ProjectStatus, ProjectType


@pytest.fixture
def api_setup(monkeypatch):
    app = FastAPI()
    app.include_router(repository_review_api.router)

    user_id = uuid4()
    project_id = uuid4()

    user = SimpleNamespace(id=user_id)

    class FakeDB:
        pass

    db = FakeDB()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db

    owned_project = SimpleNamespace(
        id=project_id,
        project_type=ProjectType.UPLOADED,
        status=ProjectStatus.CREATED,
    )

    monkeypatch.setattr(
        repository_review_api,
        "get_project",
        lambda **kwargs: owned_project,
    )

    scheduled_calls = []

    def fake_runner(received_user_id, received_project_id):
        scheduled_calls.append(
            (received_user_id, received_project_id)
        )

    monkeypatch.setattr(
        repository_review_api,
        "_run_repository_review",
        fake_runner,
    )

    with TestClient(app) as client:
        yield {
            "client": client,
            "app": app,
            "user": user,
            "project": owned_project,
            "project_id": project_id,
            "scheduled_calls": scheduled_calls,
        }


def test_review_endpoint_queues_background_review(api_setup):
    response = api_setup["client"].post(
        f"/api/v1/projects/{api_setup['project_id']}/review"
    )

    assert response.status_code == 202

    body = response.json()

    assert body["project_id"] == str(api_setup["project_id"])
    assert body["workflow_status"] == "QUEUED"
    assert "No project files will be modified" in body["message"]

    assert api_setup["scheduled_calls"] == [
        (
            api_setup["user"].id,
            api_setup["project_id"],
        )
    ]


def test_review_endpoint_rejects_project_not_owned(
    api_setup,
    monkeypatch,
):
    monkeypatch.setattr(
        repository_review_api,
        "get_project",
        lambda **kwargs: None,
    )

    response = api_setup["client"].post(
        f"/api/v1/projects/{api_setup['project_id']}/review"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"
    assert api_setup["scheduled_calls"] == []


def test_review_endpoint_rejects_generated_project(api_setup):
    api_setup["project"].project_type = ProjectType.GENERATED

    response = api_setup["client"].post(
        f"/api/v1/projects/{api_setup['project_id']}/review"
    )

    assert response.status_code == 400

    assert response.json()["detail"] == (
        "Repository review is only available "
        "for uploaded projects."
    )

    assert api_setup["scheduled_calls"] == []


@pytest.mark.parametrize(
    "active_status",
    [
        ProjectStatus.PLANNING,
        ProjectStatus.GENERATING,
        ProjectStatus.VERIFYING,
        ProjectStatus.REVIEWING,
        ProjectStatus.FIXING,
    ],
)
def test_review_endpoint_rejects_project_with_active_workflow(
    api_setup,
    active_status,
):
    api_setup["project"].status = active_status

    response = api_setup["client"].post(
        f"/api/v1/projects/{api_setup['project_id']}/review"
    )

    assert response.status_code == 409

    assert (
        "already has an active workflow"
        in response.json()["detail"]
    )

    assert api_setup["scheduled_calls"] == []


def test_review_endpoint_requires_authentication():
    app = FastAPI()
    app.include_router(repository_review_api.router)

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/projects/{uuid4()}/review"
        )

    assert response.status_code in (401, 403)


def test_review_endpoint_rejects_invalid_project_id(api_setup):
    response = api_setup["client"].post(
        "/api/v1/projects/not-a-uuid/review"
    )

    assert response.status_code == 422
    assert api_setup["scheduled_calls"] == []