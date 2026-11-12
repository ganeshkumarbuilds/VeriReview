import os
import uuid

import httpx
import pytest

from app.database.connection import SessionLocal
from app.models.review import ReviewType
from app.services.review_persistence import persist_review


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
            "name": f"Review API Test {uuid.uuid4().hex[:8]}",
            "description": "Review API integration test project.",
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
def review_records(api_project):
    """Create persisted reviews and findings for API tests."""

    db = SessionLocal()

    try:
        project_uuid = uuid.UUID(api_project)

        verification_findings = [
            {
                "file_path": "app/main.py",
                "title": "Potential SQL injection",
                "description": (
                    "User input is directly interpolated into SQL."
                ),
                "severity": "HIGH",
                "category": "SECURITY",
                "line_number": 25,
                "suggested_fix": (
                    "Use parameterized SQL queries."
                ),
            },
            {
                "file_path": "app/config.py",
                "title": "Missing configuration validation",
                "description": (
                    "Required environment variables are not validated."
                ),
                "severity": "MEDIUM",
                "category": "CONFIGURATION",
                "line_number": 12,
                "suggested_fix": (
                    "Validate required environment variables."
                ),
            },
            {
                "file_path": "app/utils.py",
                "title": "Code quality issue",
                "description": (
                    "The function contains unnecessary complexity."
                ),
                "severity": "LOW",
                "category": "CODE_QUALITY",
                "line_number": 40,
                "suggested_fix": None,
            },
        ]

        verification_results = {
            "passed": False,
            "summary": "Three findings detected.",
            "findings": verification_findings,
        }

        reviewed_findings = [
            {
                **finding,
                "recommended_action": "Review and approve the fix.",
            }
            for finding in verification_findings
        ]

        review_data = {
            "summary": "Three issues require attention.",
            "total_findings": 3,
            "critical_count": 0,
            "high_count": 1,
            "medium_count": 1,
            "low_count": 1,
            "requires_user_approval": True,
            "findings": reviewed_findings,
        }

        first_review = persist_review(
            db=db,
            project_id=project_uuid,
            verification_results=verification_results,
            review_data=review_data,
            review_type=ReviewType.INITIAL,
        )

        second_review = persist_review(
            db=db,
            project_id=project_uuid,
            verification_results=verification_results,
            review_data=review_data,
            review_type=ReviewType.POST_FIX,
        )

        db.commit()

        return {
            "first_review_id": str(first_review.id),
            "second_review_id": str(second_review.id),
            "first_review_number": first_review.review_number,
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def test_review_api_requires_authentication():
    project_id = str(uuid.uuid4())
    review_id = str(uuid.uuid4())
    finding_id = str(uuid.uuid4())

    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
    ) as client:

        responses = [
            client.get(
                f"/api/v1/projects/{project_id}/reviews"
            ),
            client.get(
                f"/api/v1/projects/{project_id}/reviews/{review_id}"
            ),
            client.get(
                f"/api/v1/projects/{project_id}/findings"
            ),
            client.get(
                f"/api/v1/projects/{project_id}/findings/{finding_id}"
            ),
        ]

        assert all(
            response.status_code in (401, 403)
            for response in responses
        )


def test_reviews_reject_unowned_project(api_client):
    project_id = str(uuid.uuid4())

    response = api_client.get(
        f"/api/v1/projects/{project_id}/reviews"
    )

    assert response.status_code == 404


def test_findings_reject_unowned_project(api_client):
    project_id = str(uuid.uuid4())

    response = api_client.get(
        f"/api/v1/projects/{project_id}/findings"
    )

    assert response.status_code == 404


def test_list_reviews_without_reviews(
    api_client,
    api_project,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/reviews"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["reviews"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20


def test_list_project_reviews(
    api_client,
    api_project,
    review_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/reviews"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2
    assert len(data["reviews"]) == 2

    reviews = data["reviews"]

    assert reviews[0]["review_id"] if "review_id" in reviews[0] else reviews[0]["id"]

    assert reviews[0]["review_number"] == 2
    assert reviews[0]["review_type"] == "POST_FIX"

    assert reviews[1]["review_number"] == 1
    assert reviews[1]["review_type"] == "INITIAL"


def test_list_reviews_pagination(
    api_client,
    api_project,
    review_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/reviews",
        params={
            "page": 1,
            "page_size": 1,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2
    assert len(data["reviews"]) == 1
    assert data["page"] == 1
    assert data["page_size"] == 1


def test_get_review_details(
    api_client,
    api_project,
    review_records,
):
    review_id = review_records["first_review_id"]

    response = api_client.get(
        f"/api/v1/projects/{api_project}/reviews/{review_id}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == review_id
    assert data["project_id"] == api_project
    assert data["review_number"] == 1
    assert data["review_type"] == "INITIAL"
    assert data["status"] == "COMPLETED"

    assert data["total_findings"] == 3
    assert data["critical_count"] == 0
    assert data["high_count"] == 1
    assert data["medium_count"] == 1
    assert data["low_count"] == 1

    assert len(data["findings"]) == 3


def test_get_nonexistent_review_returns_404(
    api_client,
    api_project,
):
    review_id = str(uuid.uuid4())

    response = api_client.get(
        f"/api/v1/projects/{api_project}/reviews/{review_id}"
    )

    assert response.status_code == 404


def test_list_project_findings(
    api_client,
    api_project,
    review_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 6
    assert len(data["findings"]) == 6

    assert data["page"] == 1
    assert data["page_size"] == 50


def test_filter_findings_by_severity(
    api_client,
    api_project,
    review_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings",
        params={
            "severity": "HIGH",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2

    assert all(
        finding["severity"] == "HIGH"
        for finding in data["findings"]
    )


def test_filter_findings_by_status(
    api_client,
    api_project,
    review_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings",
        params={
            "status": "OPEN",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 6

    assert all(
        finding["status"] == "OPEN"
        for finding in data["findings"]
    )


def test_filter_findings_by_severity_and_status(
    api_client,
    api_project,
    review_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings",
        params={
            "severity": "MEDIUM",
            "status": "OPEN",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2

    assert all(
        finding["severity"] == "MEDIUM"
        and finding["status"] == "OPEN"
        for finding in data["findings"]
    )


def test_findings_reject_invalid_severity(
    api_client,
    api_project,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings",
        params={
            "severity": "INVALID",
        },
    )

    assert response.status_code == 400


def test_findings_reject_invalid_status(
    api_client,
    api_project,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings",
        params={
            "status": "INVALID",
        },
    )

    assert response.status_code == 400


def test_findings_pagination(
    api_client,
    api_project,
    review_records,
):
    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings",
        params={
            "page": 1,
            "page_size": 2,
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 6
    assert len(data["findings"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


def test_get_finding_details(
    api_client,
    api_project,
    review_records,
):
    review_id = review_records["first_review_id"]

    review_response = api_client.get(
        f"/api/v1/projects/{api_project}/reviews/{review_id}"
    )

    assert review_response.status_code == 200

    finding_id = review_response.json()["findings"][0]["id"]

    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings/{finding_id}"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == finding_id
    assert data["project_id"] == api_project
    assert data["review_id"] == review_id
    assert data["status"] == "OPEN"


def test_get_nonexistent_finding_returns_404(
    api_client,
    api_project,
):
    finding_id = str(uuid.uuid4())

    response = api_client.get(
        f"/api/v1/projects/{api_project}/findings/{finding_id}"
    )

    assert response.status_code == 404


def test_review_details_reject_finding_from_another_project(
    api_client,
    api_project,
    review_records,
):
    other_project_response = api_client.post(
        "/api/v1/projects",
        json={
            "name": f"Other Project {uuid.uuid4().hex[:8]}",
            "description": "Another project for isolation testing.",
            "project_type": "GENERATED",
            "technology_stack": "Python",
        },
    )

    assert other_project_response.status_code == 201

    other_project_id = other_project_response.json()["id"]

    try:
        finding_id = str(uuid.uuid4())

        response = api_client.get(
            f"/api/v1/projects/{other_project_id}/findings/{finding_id}"
        )

        assert response.status_code == 404

    finally:
        delete_response = api_client.delete(
            f"/api/v1/projects/{other_project_id}"
        )

        assert delete_response.status_code == 204