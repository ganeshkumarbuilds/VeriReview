from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.project_file import FileOrigin
from app.services import generated_files


@pytest.fixture
def generated_file_environment(tmp_path, monkeypatch):
    project_id = uuid4()
    user_id = uuid4()

    project_directory = tmp_path / str(project_id)
    project_directory.mkdir()

    monkeypatch.setattr(
        generated_files,
        "get_project",
        lambda db, uid, pid: (
            SimpleNamespace(id=project_id)
            if uid == user_id and pid == project_id
            else None
        ),
    )

    monkeypatch.setattr(
        generated_files,
        "get_project_directory",
        lambda pid: project_directory,
    )

    class FakeDB:
        def __init__(self):
            self.files = []
            self.deleted = []

        def scalar(self, statement):
            return None

        def scalars(self, statement):
            return SimpleNamespace(
                all=lambda: list(self.files)
            )

        def add(self, item):
            self.files.append(item)

        def flush(self):
            return None

        def refresh(self, item):
            if item.id is None:
                item.id = uuid4()

    return {
        "db": FakeDB(),
        "user_id": user_id,
        "project_id": project_id,
        "directory": project_directory,
    }


def test_create_generated_file(
    generated_file_environment,
):
    env = generated_file_environment

    project_file = generated_files.create_generated_file(
        db=env["db"],
        user_id=env["user_id"],
        project_id=env["project_id"],
        file_path="src/main.py",
        content=b"print('VeriReview')",
    )

    assert project_file.file_path == "src/main.py"
    assert project_file.origin == FileOrigin.GENERATED
    assert project_file.file_size == len(b"print('VeriReview')")

    assert (
        env["directory"] / "src" / "main.py"
    ).read_bytes() == b"print('VeriReview')"


def test_create_generated_file_rejects_duplicate(
    generated_file_environment,
):
    env = generated_file_environment

    generated_files.create_generated_file(
        env["db"],
        env["user_id"],
        env["project_id"],
        "src/main.py",
        b"first version",
    )

    with pytest.raises(FileExistsError):
        generated_files.create_generated_file(
            env["db"],
            env["user_id"],
            env["project_id"],
            "src/main.py",
            b"second version",
        )


def test_create_generated_file_rejects_unsafe_path(
    generated_file_environment,
):
    env = generated_file_environment

    with pytest.raises(ValueError):
        generated_files.create_generated_file(
            env["db"],
            env["user_id"],
            env["project_id"],
            "../outside.py",
            b"unsafe",
        )


def test_create_generated_file_rejects_unowned_project(
    generated_file_environment,
):
    env = generated_file_environment

    with pytest.raises(ValueError, match="Project not found"):
        generated_files.create_generated_file(
            env["db"],
            uuid4(),
            env["project_id"],
            "main.py",
            b"content",
        )


def test_update_requires_approval(
    generated_file_environment,
):
    env = generated_file_environment

    with pytest.raises(PermissionError):
        generated_files.update_generated_file(
            env["db"],
            env["user_id"],
            env["project_id"],
            "main.py",
            b"updated",
        )


def test_update_generated_file(
    generated_file_environment,
):
    env = generated_file_environment

    generated_files.create_generated_file(
        env["db"],
        env["user_id"],
        env["project_id"],
        "main.py",
        b"original",
    )

    project_file = generated_files.update_generated_file(
        env["db"],
        env["user_id"],
        env["project_id"],
        "main.py",
        b"updated",
        approved=True,
    )

    assert project_file.file_size == len(b"updated")
    assert project_file.origin == FileOrigin.GENERATED

    assert (
        env["directory"] / "main.py"
    ).read_bytes() == b"updated"


def test_update_rejects_missing_file(
    generated_file_environment,
):
    env = generated_file_environment

    with pytest.raises(FileNotFoundError):
        generated_files.update_generated_file(
            env["db"],
            env["user_id"],
            env["project_id"],
            "missing.py",
            b"content",
            approved=True,
        )


def test_generated_file_database_failure_removes_new_file(
    generated_file_environment,
    monkeypatch,
):
    env = generated_file_environment

    def fail_flush():
        raise RuntimeError("Database flush failed")

    monkeypatch.setattr(
        env["db"],
        "flush",
        fail_flush,
    )

    with pytest.raises(RuntimeError):
        generated_files.create_generated_file(
            env["db"],
            env["user_id"],
            env["project_id"],
            "main.py",
            b"content",
        )

    assert not (
        env["directory"] / "main.py"
    ).exists()


def test_update_preserves_backup_when_restoration_fails(
    generated_file_environment,
    monkeypatch,
):
    env = generated_file_environment

    original_content = b"original"
    replacement_content = b"updated"

    generated_files.create_generated_file(
        env["db"],
        env["user_id"],
        env["project_id"],
        "main.py",
        original_content,
    )

    def fail_flush():
        raise RuntimeError("Database flush failed")

    monkeypatch.setattr(
        env["db"],
        "flush",
        fail_flush,
    )

    original_replace = generated_files.os.replace
    replace_calls = 0

    def fail_restoration(source, destination):
        nonlocal replace_calls
        replace_calls += 1

        # First call: move original file to backup.
        # Second call: publish replacement.
        # Third call: simulate restoration failure.
        if replace_calls == 3:
            raise OSError("Simulated restoration failure")

        return original_replace(source, destination)

    monkeypatch.setattr(
        generated_files.os,
        "replace",
        fail_restoration,
    )

    with pytest.raises(
        RuntimeError,
        match="Original backup preserved",
    ):
        generated_files.update_generated_file(
            env["db"],
            env["user_id"],
            env["project_id"],
            "main.py",
            replacement_content,
            approved=True,
        )

    backup_files = list(
        env["directory"].glob(".main.py.*.bak")
    )

    assert len(backup_files) == 1

    # The backup must contain the original file.
    assert backup_files[0].read_bytes() == original_content

    # The original destination must not contain the replacement.
    assert not (
        env["directory"] / "main.py"
    ).exists()

    # All three replace operations must have been attempted.
    assert replace_calls == 3