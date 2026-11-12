import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.project import ProjectStatus
from app.workflows import repository_review


class FakeDB:
    def __init__(self, project=None, project_files=None):
        self.project = project
        self.project_files = project_files or []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def scalars(self, statement):
        return SimpleNamespace(all=lambda: self.project_files)

    def get(self, model, object_id):
        return self.project

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_load_repository_context_reads_real_text_files(
    tmp_path,
    monkeypatch,
):
    user_id = uuid4()
    project_id = uuid4()
    project_directory = tmp_path / str(project_id)
    project_directory.mkdir()

    source_file = project_directory / "main.py"
    source_file.write_text("print('hello')", encoding="utf-8")

    project = SimpleNamespace(
        id=project_id,
        name="Imported repository",
        technology_stack="Python",
    )

    project_file = SimpleNamespace(
        file_path="main.py",
        storage_path=str(source_file),
    )

    db = FakeDB(project=project, project_files=[project_file])

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project_directory",
        lambda received_id: project_directory,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: project,
    )

    context = repository_review._load_repository_context(
        user_id,
        project_id,
    )

    assert context["project_id"] == project_id
    assert context["project_name"] == "Imported repository"
    assert context["technology_stack"] == "Python"

    assert context["files"] == [
        {
            "file_path": "main.py",
            "content": "print('hello')",
        }
    ]

    assert context["skipped_binary_files"] == []
    assert db.closed


def test_load_repository_context_skips_binary_files(
    tmp_path,
    monkeypatch,
):
    user_id = uuid4()
    project_id = uuid4()

    project_directory = tmp_path / str(project_id)
    project_directory.mkdir()

    text_file = project_directory / "README.md"
    text_file.write_text("# Project", encoding="utf-8")

    binary_file = project_directory / "image.bin"
    binary_file.write_bytes(b"\xff\xfe\x00")

    project = SimpleNamespace(
        id=project_id,
        name="Repository",
        technology_stack="",
    )

    project_files = [
        SimpleNamespace(
            file_path="README.md",
            storage_path=str(text_file),
        ),
        SimpleNamespace(
            file_path="image.bin",
            storage_path=str(binary_file),
        ),
    ]

    db = FakeDB(project=project, project_files=project_files)

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project_directory",
        lambda received_id: project_directory,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: project,
    )

    context = repository_review._load_repository_context(
        user_id,
        project_id,
    )

    assert len(context["files"]) == 1
    assert context["skipped_binary_files"] == ["image.bin"]


def test_load_repository_context_rejects_file_outside_project(
    tmp_path,
    monkeypatch,
):
    user_id = uuid4()
    project_id = uuid4()

    project_directory = tmp_path / str(project_id)
    project_directory.mkdir()

    outside_file = tmp_path / "outside.py"
    outside_file.write_text("unsafe = True", encoding="utf-8")

    project = SimpleNamespace(
        id=project_id,
        name="Repository",
        technology_stack="Python",
    )

    project_file = SimpleNamespace(
        file_path="outside.py",
        storage_path=str(outside_file),
    )

    db = FakeDB(project=project, project_files=[project_file])

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project_directory",
        lambda received_id: project_directory,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: project,
    )

    with pytest.raises(
        repository_review.RepositoryReviewError,
        match="escapes its storage directory",
    ):
        repository_review._load_repository_context(
            user_id,
            project_id,
        )


def test_load_repository_context_rejects_missing_project(
    monkeypatch,
):
    db = FakeDB(project=None)

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: None,
    )

    with pytest.raises(
        repository_review.RepositoryReviewError,
        match="Project not found",
    ):
        repository_review._load_repository_context(
            uuid4(),
            uuid4(),
        )

    assert db.closed


def test_load_repository_context_rejects_empty_project(
    monkeypatch,
):
    project_id = uuid4()

    project = SimpleNamespace(
        id=project_id,
        name="Empty",
        technology_stack="",
    )

    db = FakeDB(project=project, project_files=[])

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: project,
    )
    monkeypatch.setattr(
        repository_review,
        "get_project_directory",
        lambda received_id: Path("unused"),
    )

    with pytest.raises(
        repository_review.RepositoryReviewError,
        match="no imported files",
    ):
        repository_review._load_repository_context(
            uuid4(),
            project_id,
        )


def test_review_workflow_runs_both_agents_and_persists_findings(
    monkeypatch,
):
    user_id = uuid4()
    project_id = uuid4()

    project = SimpleNamespace(
        id=project_id,
        status=ProjectStatus.CREATED,
    )

    db = FakeDB(project=project)

    context = {
        "project_id": project_id,
        "project_name": "Demo",
        "technology_stack": "Python",
        "files": [
            {
                "file_path": "main.py",
                "content": "bad code",
            }
        ],
        "skipped_binary_files": [],
    }

    verification_data = {
        "passed": False,
        "findings": [{"title": "Bug"}],
    }

    review_data = {
        "summary": "A bug was found.",
        "total_findings": 1,
        "critical_count": 0,
        "high_count": 1,
        "medium_count": 0,
        "low_count": 0,
        "findings": [{"title": "Bug"}],
        "requires_user_approval": True,
    }

    calls = {
        "verify": 0,
        "review": 0,
        "persist": 0,
        "failed": 0,
    }

    class FakeAgent:
        async def verify_files(self, **kwargs):
            calls["verify"] += 1

            assert kwargs["files"] == context["files"]

            return SimpleNamespace(
                model_dump=lambda: verification_data
            )

    class FakeReviewAgent:
        async def review(self, received):
            calls["review"] += 1

            assert received == verification_data

            return SimpleNamespace(
                model_dump=lambda: review_data
            )

    monkeypatch.setattr(
        repository_review,
        "_load_repository_context",
        lambda received_user_id, received_project_id: context,
    )

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )

    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: project,
    )

    monkeypatch.setattr(
        repository_review,
        "verifying_agent",
        FakeAgent(),
    )

    monkeypatch.setattr(
        repository_review,
        "review_agent",
        FakeReviewAgent(),
    )

    def fake_persist(
        received_project_id,
        verification,
        review,
    ):
        calls["persist"] += 1

        assert received_project_id == project_id
        assert verification == verification_data
        assert review == review_data

        return {
            "review_id": str(uuid4()),
            "review_number": 1,
            "total_findings": 1,
            "status": "COMPLETED",
        }

    monkeypatch.setattr(
        repository_review,
        "_persist_repository_review",
        fake_persist,
    )

    monkeypatch.setattr(
        repository_review,
        "_mark_project_failed",
        lambda received_project_id: calls.__setitem__(
            "failed",
            calls["failed"] + 1,
        ),
    )

    result = asyncio.run(
        repository_review.review_imported_project(
            user_id,
            project_id,
        )
    )

    assert result["workflow_status"] == "WAITING_FOR_APPROVAL"
    assert result["files_reviewed"] == 1
    assert result["review"] == review_data

    assert calls == {
        "verify": 1,
        "review": 1,
        "persist": 1,
        "failed": 0,
    }

    assert project.status == ProjectStatus.VERIFYING


def test_review_workflow_skips_review_agent_when_no_findings(
    monkeypatch,
):
    user_id = uuid4()
    project_id = uuid4()

    project = SimpleNamespace(
        id=project_id,
        status=ProjectStatus.CREATED,
    )

    db = FakeDB(project=project)

    verification_data = {
        "passed": True,
        "findings": [],
    }

    calls = {
        "review": 0,
        "persist": 0,
    }

    class FakeAgent:
        async def verify_files(self, **kwargs):
            return SimpleNamespace(
                model_dump=lambda: verification_data
            )

    class FakeReviewAgent:
        async def review(self, received):
            calls["review"] += 1

            raise AssertionError(
                "Review Agent must not run without findings"
            )

    monkeypatch.setattr(
        repository_review,
        "_load_repository_context",
        lambda *args: {
            "project_id": project_id,
            "project_name": "Clean",
            "technology_stack": "Python",
            "files": [
                {
                    "file_path": "main.py",
                    "content": "pass",
                }
            ],
            "skipped_binary_files": [],
        },
    )

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )

    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: project,
    )

    monkeypatch.setattr(
        repository_review,
        "verifying_agent",
        FakeAgent(),
    )

    monkeypatch.setattr(
        repository_review,
        "review_agent",
        FakeReviewAgent(),
    )

    def fake_persist(
        received_project_id,
        verification,
        review,
    ):
        calls["persist"] += 1

        assert review["total_findings"] == 0

        return {
            "review_id": str(uuid4()),
            "review_number": 1,
            "total_findings": 0,
            "status": "COMPLETED",
        }

    monkeypatch.setattr(
        repository_review,
        "_persist_repository_review",
        fake_persist,
    )

    monkeypatch.setattr(
        repository_review,
        "_mark_project_failed",
        lambda received_project_id: None,
    )

    result = asyncio.run(
        repository_review.review_imported_project(
            user_id,
            project_id,
        )
    )

    assert result["workflow_status"] == "COMPLETED"

    assert calls == {
        "review": 0,
        "persist": 1,
    }


def test_review_workflow_marks_project_failed_when_verifier_fails(
    monkeypatch,
):
    user_id = uuid4()
    project_id = uuid4()

    project = SimpleNamespace(
        id=project_id,
        status=ProjectStatus.CREATED,
    )

    db = FakeDB(project=project)

    failed_projects = []

    class FailingAgent:
        async def verify_files(self, **kwargs):
            raise RuntimeError("Verifier unavailable")

    monkeypatch.setattr(
        repository_review,
        "_load_repository_context",
        lambda *args: {
            "project_id": project_id,
            "project_name": "Demo",
            "technology_stack": "Python",
            "files": [
                {
                    "file_path": "main.py",
                    "content": "pass",
                }
            ],
            "skipped_binary_files": [],
        },
    )

    monkeypatch.setattr(
        repository_review,
        "SessionLocal",
        lambda: db,
    )

    monkeypatch.setattr(
        repository_review,
        "get_project",
        lambda **kwargs: project,
    )

    monkeypatch.setattr(
        repository_review,
        "verifying_agent",
        FailingAgent(),
    )

    monkeypatch.setattr(
        repository_review,
        "_mark_project_failed",
        lambda received_project_id: failed_projects.append(
            received_project_id
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Verifier unavailable",
    ):
        asyncio.run(
            repository_review.review_imported_project(
                user_id,
                project_id,
            )
        )

    assert failed_projects == [project_id]