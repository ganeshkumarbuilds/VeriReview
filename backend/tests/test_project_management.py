import io
import os
import uuid
import zipfile

from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.services import file_storage, project_deletion
from app.services.file_storage import get_project_directory


BASE_URL = "http://127.0.0.1:8000"

EMAIL = os.getenv("VERIREVIEW_TEST_EMAIL")
PASSWORD = os.getenv("VERIREVIEW_TEST_PASSWORD")


@pytest.fixture
def api_client():
    if not EMAIL or not PASSWORD:
        pytest.fail("Test credentials are missing from environment variables.")

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


def test_project_and_file_management(api_client):
    client = api_client
    project_id = None

    try:
        # 1. Verify authentication.
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 200

        # 2. Create a project.
        response = client.post(
            "/api/v1/projects",
            json={
                "name": f"Automated Test {uuid.uuid4().hex[:8]}",
                "description": "Temporary integration test project",
                "project_type": "GENERATED",
                "technology_stack": "Python, FastAPI",
            },
        )

        assert response.status_code == 201

        project = response.json()
        project_id = project["id"]

        project_directory = get_project_directory(UUID(project_id))

        # 3. Retrieve the project.
        response = client.get(
            f"/api/v1/projects/{project_id}"
        )

        assert response.status_code == 200
        assert response.json()["id"] == project_id

        # 4. List projects.
        response = client.get("/api/v1/projects")

        assert response.status_code == 200
        assert any(
            item["id"] == project_id
            for item in response.json()["projects"]
        )

        # 5. Update the project.
        response = client.patch(
            f"/api/v1/projects/{project_id}",
            json={
                "description": "Updated integration test project"
            },
        )

        assert response.status_code == 200
        assert response.json()["description"] == (
            "Updated integration test project"
        )

        # 6. Upload an individual file.
        response = client.post(
            f"/api/v1/projects/{project_id}/files/upload",
            files={
                "file": (
                    "hello.txt",
                    b"VeriReview integration test",
                    "text/plain",
                )
            },
        )

        assert response.status_code == 201

        uploaded_file = response.json()
        file_id = uploaded_file["id"]

        assert project_directory.joinpath("hello.txt").is_file()

        # 7. Verify duplicate upload rejection.
        response = client.post(
            f"/api/v1/projects/{project_id}/files/upload",
            files={
                "file": (
                    "hello.txt",
                    b"Duplicate content",
                    "text/plain",
                )
            },
        )

        assert response.status_code == 409

        # 8. List project files.
        response = client.get(
            f"/api/v1/projects/{project_id}/files"
        )

        assert response.status_code == 200
        assert any(
            item["id"] == file_id
            for item in response.json()["files"]
        )

        # 9. Download the uploaded file.
        response = client.get(
            f"/api/v1/projects/{project_id}/files/{file_id}/download"
        )

        assert response.status_code == 200
        assert response.content == b"VeriReview integration test"

        # 10. Delete the uploaded file.
        response = client.delete(
            f"/api/v1/projects/{project_id}/files/{file_id}"
        )

        assert response.status_code == 204

        # 11. Create a valid ZIP archive.
        archive = io.BytesIO()

        with zipfile.ZipFile(
            archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zip_file:
            zip_file.writestr(
                "src/main.py",
                "print('VeriReview')",
            )
            zip_file.writestr(
                "README.md",
                "# VeriReview test",
            )

        archive.seek(0)

        # 12. Upload and extract the ZIP.
        response = client.post(
            f"/api/v1/projects/{project_id}/files/upload-zip",
            files={
                "file": (
                    "test-project.zip",
                    archive.getvalue(),
                    "application/zip",
                )
            },
        )

        assert response.status_code == 201

        extracted_files = response.json()

        assert len(extracted_files) == 2

        extracted_paths = {
            item["file_path"]
            for item in extracted_files
        }

        assert "src/main.py" in extracted_paths
        assert "README.md" in extracted_paths

        # 13. Test ZIP path traversal protection.
        malicious_archive = io.BytesIO()

        with zipfile.ZipFile(
            malicious_archive,
            mode="w",
        ) as zip_file:
            zip_file.writestr(
                "../verireview_test_escape.txt",
                "This file must never be extracted.",
            )

        malicious_archive.seek(0)

        response = client.post(
            f"/api/v1/projects/{project_id}/files/upload-zip",
            files={
                "file": (
                    "malicious.zip",
                    malicious_archive.getvalue(),
                    "application/zip",
                )
            },
        )

        assert response.status_code == 400

        # 14. Verify the project still exists before deletion.
        response = client.get(
            f"/api/v1/projects/{project_id}"
        )

        assert response.status_code == 200

    finally:
        # Let the API perform project and storage deletion.
        # Do not manually delete the directory: that would hide API failures.
        if project_id:
            response = client.delete(
                f"/api/v1/projects/{project_id}"
            )

            if response.status_code == 204:
                assert not get_project_directory(
                    UUID(project_id)
                ).exists()


def test_project_endpoints_require_authentication():
    with httpx.Client(
        base_url=BASE_URL,
        timeout=30.0,
    ) as client:

        response = client.get("/api/v1/projects")

        assert response.status_code in (401, 403)


def test_project_storage_can_be_restored_after_failed_deletion(
    tmp_path,
    monkeypatch,
):
    """
    Simulate a failed database deletion by staging the directory
    and then restoring it.
    """

    storage_root = tmp_path / "projects"
    project_id = uuid.uuid4()

    # Both modules must use the same temporary storage root.
    monkeypatch.setattr(
        file_storage,
        "STORAGE_ROOT",
        storage_root,
    )

    monkeypatch.setattr(
        project_deletion,
        "STORAGE_ROOT",
        storage_root,
    )

    original_directory = get_project_directory(project_id)
    original_directory.mkdir(parents=True)

    original_file = original_directory / "important.txt"
    original_file.write_text(
        "Project data must survive a failed deletion.",
        encoding="utf-8",
    )

    staged_directory = (
        project_deletion.stage_project_directory_deletion(
            project_id
        )
    )

    assert staged_directory is not None
    assert staged_directory.exists()
    assert not original_directory.exists()

    # Simulate database rollback recovery.
    project_deletion.restore_project_directory(
        project_id,
        staged_directory,
    )

    assert original_directory.exists()
    assert original_file.read_text(
        encoding="utf-8"
    ) == "Project data must survive a failed deletion."

    assert not staged_directory.exists()


def test_project_storage_deletion_can_be_finalized(
    tmp_path,
    monkeypatch,
):
    storage_root = tmp_path / "projects"
    project_id = uuid.uuid4()

    monkeypatch.setattr(
        file_storage,
        "STORAGE_ROOT",
        storage_root,
    )

    monkeypatch.setattr(
        project_deletion,
        "STORAGE_ROOT",
        storage_root,
    )

    project_directory = get_project_directory(project_id)
    project_directory.mkdir(parents=True)

    (project_directory / "test.txt").write_text(
        "Temporary project data",
        encoding="utf-8",
    )

    staged_directory = (
        project_deletion.stage_project_directory_deletion(
            project_id
        )
    )

    assert staged_directory is not None
    assert staged_directory.exists()

    project_deletion.finalize_project_directory_deletion(
        staged_directory
    )

    assert not staged_directory.exists()
    assert not project_directory.exists()