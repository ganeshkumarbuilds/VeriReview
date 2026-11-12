from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.routes import project_files
from app.services.file_deletion import (
    finalize_file_deletion,
    restore_file_deletion,
    stage_file_deletion,
)


def create_test_file(tmp_path: Path):
    project_directory = tmp_path / "project"
    project_directory.mkdir()

    original_path = project_directory / "src" / "main.py"
    original_path.parent.mkdir()

    original_path.write_text(
        "print('VeriReview')",
        encoding="utf-8",
    )

    return project_directory, original_path


def test_file_deletion_can_be_staged(tmp_path):
    project_directory, original_path = create_test_file(tmp_path)

    staged_path = stage_file_deletion(
        original_path,
        project_directory,
    )

    assert staged_path.exists()
    assert not original_path.exists()

    assert staged_path.read_text(
        encoding="utf-8"
    ) == "print('VeriReview')"


def test_file_deletion_can_be_restored(tmp_path):
    project_directory, original_path = create_test_file(tmp_path)

    original_content = original_path.read_text(
        encoding="utf-8"
    )

    staged_path = stage_file_deletion(
        original_path,
        project_directory,
    )

    restore_file_deletion(
        staged_path,
        original_path,
    )

    assert original_path.exists()
    assert not staged_path.exists()

    assert original_path.read_text(
        encoding="utf-8"
    ) == original_content


def test_file_deletion_can_be_finalized(tmp_path):
    project_directory, original_path = create_test_file(tmp_path)

    staged_path = stage_file_deletion(
        original_path,
        project_directory,
    )

    finalize_file_deletion(
        staged_path,
        project_directory,
    )

    assert not staged_path.exists()
    assert not original_path.exists()

    # The empty src directory should also be removed.
    assert not original_path.parent.exists()


def test_file_deletion_rejects_paths_outside_project(tmp_path):
    project_directory, _ = create_test_file(tmp_path)

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text(
        "Do not delete this file",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        stage_file_deletion(
            outside_file,
            project_directory,
        )

    assert outside_file.exists()


def test_database_failure_restores_original_file(
    tmp_path,
    monkeypatch,
):
    project_directory, original_path = create_test_file(tmp_path)

    project_id = uuid4()
    file_id = uuid4()

    project_file = SimpleNamespace(
        id=file_id,
        storage_path=str(original_path),
    )

    current_user = SimpleNamespace(
        id=uuid4(),
    )

    class FakeDatabase:
        def __init__(self):
            self.deleted_object = None
            self.rollback_called = False

        def delete(self, obj):
            self.deleted_object = obj

        def commit(self):
            raise RuntimeError("Simulated database failure")

        def rollback(self):
            self.rollback_called = True

    db = FakeDatabase()

    monkeypatch.setattr(
        project_files,
        "get_project_file",
        lambda **kwargs: (project_file, original_path),
    )

    monkeypatch.setattr(
        project_files,
        "get_project_directory",
        lambda project_id: project_directory,
    )

    with pytest.raises(
        RuntimeError,
        match="Simulated database failure",
    ):
        project_files.remove_file(
            project_id=project_id,
            file_id=file_id,
            current_user=current_user,
            db=db,
        )

    assert db.deleted_object is project_file
    assert db.rollback_called

    assert original_path.exists()
    assert original_path.read_text(
        encoding="utf-8"
    ) == "print('VeriReview')"

    assert not list(
        project_directory.rglob("*.deleting")
    )


def test_successful_api_deletion_removes_file(
    tmp_path,
    monkeypatch,
):
    project_directory, original_path = create_test_file(tmp_path)

    project_id = uuid4()
    file_id = uuid4()

    project_file = SimpleNamespace(
        id=file_id,
        storage_path=str(original_path),
    )

    current_user = SimpleNamespace(
        id=uuid4(),
    )

    class FakeDatabase:
        def __init__(self):
            self.deleted_object = None
            self.committed = False

        def delete(self, obj):
            self.deleted_object = obj

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError(
                "Rollback should not occur after successful commit"
            )

    db = FakeDatabase()

    monkeypatch.setattr(
        project_files,
        "get_project_file",
        lambda **kwargs: (project_file, original_path),
    )

    monkeypatch.setattr(
        project_files,
        "get_project_directory",
        lambda project_id: project_directory,
    )

    result = project_files.remove_file(
        project_id=project_id,
        file_id=file_id,
        current_user=current_user,
        db=db,
    )

    assert result is None
    assert db.committed
    assert db.deleted_object is project_file

    assert not original_path.exists()
    assert not original_path.parent.exists()