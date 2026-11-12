import os
import uuid

import httpx
import pytest

from sqlalchemy import select

from app.database.connection import SessionLocal
from app.models.finding import Finding
from app.models.fix_request import FixRequest, FixRequestStatus
from app.models.review import ReviewType
from app.services.review_persistence import persist_review


BASE_URL = "http://127.0.0.1:8000"

EMAIL = os.getenv("VERIREVIEW_TEST_EMAIL")
PASSWORD = os.getenv("VERIREVIEW_TEST_PASSWORD")


@pytest.fixture
def api_client():
    if not EMAIL or not PASSWORD:
        pytest.fail("Test credentials are missing.")

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

        client.headers.update({
            "Authorization": (
                f"Bearer {response.json()['access_token']}"
            )
        })

        yield client


@pytest.fixture
def api_project(api_client):
    response = api_client.post(
        "/api/v1/projects",
        json={
            "name": f"Fix API Test {uuid.uuid4().hex[:8]}",
            "description": "Fix approval integration test.",
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
def finding_record(api_project):
    db = SessionLocal()

    try:
        project_uuid = uuid.UUID(api_project)

        verification_results = {
            "passed": False,
            "summary": "Security issue detected.",
            "findings": [
                {
                    "file_path": "app/main.py",
                    "title": "Potential SQL injection",
                    "description": "Unsafe SQL query construction.",
                    "severity": "HIGH",
                    "category": "SECURITY",
                    "line_number": 25,
                    "suggested_fix": "Use parameterized SQL queries.",
                }
            ],
        }

        review_data = {
            "summary": "One security issue detected.",
            "total_findings": 1,
            "critical_count": 0,
            "high_count": 1,
            "medium_count": 0,
            "low_count": 0,
            "requires_user_approval": True,
            "findings": [
                {
                    **verification_results["findings"][0],
                    "recommended_action": "Use parameterized queries.",
                }
            ],
        }

        review = persist_review(
            db=db,
            project_id=project_uuid,
            verification_results=verification_results,
            review_data=review_data,
            review_type=ReviewType.INITIAL,
        )

        db.commit()

        finding = db.scalar(
            select(Finding).where(
                Finding.review_id == review.id
            )
        )

        return {
            "finding_id": str(finding.id),
            "review_id": str(review.id),
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def approve_finding(api_client, api_project, finding_id):
    return api_client.post(
        f"/api/v1/projects/{api_project}/findings/"
        f"{finding_id}/approve-fix",
        json={},
    )


def test_fix_api_requires_authentication():
    project_id = str(uuid.uuid4())
    finding_id = str(uuid.uuid4())
    fix_request_id = str(uuid.uuid4())

    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
    ) as client:
        responses = [
            client.post(
                f"/api/v1/projects/{project_id}/findings/"
                f"{finding_id}/approve-fix",
                json={},
            ),
            client.post(
                f"/api/v1/projects/{project_id}/fix-requests/"
                f"{fix_request_id}/execute",
            ),
            client.get(
                f"/api/v1/projects/{project_id}/fix-requests/"
                f"{fix_request_id}"
            ),
            client.post(
                f"/api/v1/projects/{project_id}/fix-requests/"
                f"{fix_request_id}/cancel"
            ),
        ]

        assert all(
            response.status_code in (401, 403)
            for response in responses
        )


def test_approve_fix_for_finding(
    api_client,
    api_project,
    finding_record,
):
    response = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert response.status_code == 201

    data = response.json()

    assert data["project_id"] == api_project
    assert data["finding_id"] == finding_record["finding_id"]
    assert data["status"] == "REQUESTED"
    assert data["approved_at"] is not None
    assert data["started_at"] is None
    assert data["completed_at"] is None


def test_approve_fix_with_user_instruction(
    api_client,
    api_project,
    finding_record,
):
    response = api_client.post(
        f"/api/v1/projects/{api_project}/findings/"
        f"{finding_record['finding_id']}/approve-fix",
        json={
            "user_instruction": "Use parameterized SQL queries.",
        },
    )

    assert response.status_code == 201
    assert response.json()["user_instruction"] == (
        "Use parameterized SQL queries."
    )


def test_approve_fix_without_user_instruction(
    api_client,
    api_project,
    finding_record,
):
    response = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert response.status_code == 201
    assert response.json()["user_instruction"] is None


def test_approve_fix_rejects_unowned_project(api_client):
    response = approve_finding(
        api_client,
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    )

    assert response.status_code == 404


def test_approve_fix_rejects_nonexistent_finding(
    api_client,
    api_project,
):
    response = approve_finding(
        api_client,
        api_project,
        str(uuid.uuid4()),
    )

    assert response.status_code == 404


def test_approve_fix_rejects_duplicate_active_request(
    api_client,
    api_project,
    finding_record,
):
    first = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert first.status_code == 201

    second = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert second.status_code == 409


def test_approved_fix_is_persisted(
    api_client,
    api_project,
    finding_record,
):
    response = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert response.status_code == 201

    fix_request_id = response.json()["id"]

    db = SessionLocal()

    try:
        fix_request = db.get(
            FixRequest,
            uuid.UUID(fix_request_id),
        )

        assert fix_request is not None
        assert fix_request.status == FixRequestStatus.REQUESTED
        assert fix_request.approved_at is not None
        assert fix_request.started_at is None

    finally:
        db.close()


def test_approval_does_not_modify_finding(
    api_client,
    api_project,
    finding_record,
):
    response = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert response.status_code == 201

    db = SessionLocal()

    try:
        finding = db.get(
            Finding,
            uuid.UUID(finding_record["finding_id"]),
        )

        assert finding.status.value == "OPEN"

    finally:
        db.close()


def test_get_fix_request(
    api_client,
    api_project,
    finding_record,
):
    approval = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert approval.status_code == 201

    fix_request_id = approval.json()["id"]

    response = api_client.get(
        f"/api/v1/projects/{api_project}/fix-requests/"
        f"{fix_request_id}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == fix_request_id
    assert data["status"] == "REQUESTED"
    assert data["approved_at"] is not None


def test_get_nonexistent_fix_request(
    api_client,
    api_project,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/fix-requests/"
        f"{uuid.uuid4()}"
    )

    assert response.status_code == 404


def test_execute_rejects_nonexistent_fix_request(
    api_client,
    api_project,
):
    response = api_client.post(
        f"/api/v1/projects/{api_project}/fix-requests/"
        f"{uuid.uuid4()}/execute"
    )

    assert response.status_code == 404


def test_execute_rejects_unapproved_fix_request(
    api_client,
    api_project,
    finding_record,
):
    db = SessionLocal()

    try:
        fix_request = FixRequest(
            project_id=uuid.UUID(api_project),
            finding_id=uuid.UUID(finding_record["finding_id"]),
            status=FixRequestStatus.REQUESTED,
            approved_at=None,
        )

        db.add(fix_request)
        db.commit()
        db.refresh(fix_request)

        fix_request_id = str(fix_request.id)

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    response = api_client.post(
        f"/api/v1/projects/{api_project}/fix-requests/"
        f"{fix_request_id}/execute"
    )

    assert response.status_code == 403
    assert "approval" in response.json()["detail"].lower()


def test_cancel_pending_fix_request(
    api_client,
    api_project,
    finding_record,
):
    approval = approve_finding(
        api_client,
        api_project,
        finding_record["finding_id"],
    )

    assert approval.status_code == 201

    fix_request_id = approval.json()["id"]

    response = api_client.post(
        f"/api/v1/projects/{api_project}/fix-requests/"
        f"{fix_request_id}/cancel"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


def test_cancel_rejects_nonexistent_fix_request(
    api_client,
    api_project,
):
    response = api_client.post(
        f"/api/v1/projects/{api_project}/fix-requests/"
        f"{uuid.uuid4()}/cancel"
    )

    assert response.status_code == 409