import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.coding import GeneratedFile
from app.workflows.fix_execution import (
    FixApprovalError,
    FixExecutionError,
    execute_approved_fix,
)


@pytest.fixture
def identifiers():
    return {
        "user_id": uuid4(),
        "project_id": uuid4(),
        "fix_request_id": uuid4(),
        "finding_id": uuid4(),
    }


@pytest.fixture
def fix_context(identifiers):
    return {
        "fix_request_id": identifiers["fix_request_id"],
        "finding_id": identifiers["finding_id"],
        "project_id": identifiers["project_id"],
        "file_path": "app/main.py",
        "title": "Potential SQL injection",
        "description": "Unsafe SQL query construction.",
        "severity": "HIGH",
        "category": "SECURITY",
        "line_number": 25,
        "code_snippet": "query = f'SELECT * FROM users WHERE id={user_id}'",
        "suggested_fix": "Use parameterized queries.",
        "user_instruction": "Use parameterized SQL.",
        "requirements": "Build a FastAPI application.",
        "technology_stack": "Python, FastAPI, PostgreSQL",
        "storage_path": "C:/projects/test/app/main.py",
    }


@pytest.fixture
def generated_file():
    return GeneratedFile(
        file_path="app/main.py",
        purpose="Fixed SQL injection vulnerability.",
        content=(
            "from sqlalchemy import text\n\n"
            "def get_user(db, user_id):\n"
            "    return db.execute(\n"
            "        text('SELECT * FROM users WHERE id = :user_id'),\n"
            "        {'user_id': user_id},\n"
            "    )\n"
        ),
    )


def test_execute_fix_rejects_unapproved_request(identifiers):
    with patch(
        "app.workflows.fix_execution._load_fix_context",
        side_effect=FixApprovalError(
            "Explicit user approval is required."
        ),
    ):
        with pytest.raises(FixApprovalError):
            asyncio.run(
                execute_approved_fix(
                    user_id=identifiers["user_id"],
                    project_id=identifiers["project_id"],
                    fix_request_id=identifiers["fix_request_id"],
                )
            )


def test_execute_fix_rejects_missing_request(identifiers):
    with patch(
        "app.workflows.fix_execution._load_fix_context",
        side_effect=FixExecutionError("Fix request not found."),
    ):
        with pytest.raises(FixExecutionError):
            asyncio.run(
                execute_approved_fix(
                    user_id=identifiers["user_id"],
                    project_id=identifiers["project_id"],
                    fix_request_id=identifiers["fix_request_id"],
                )
            )


def test_execute_fix_generates_and_verifies_replacement(
    identifiers,
    fix_context,
    generated_file,
):
    verification_result = {
        "passed": True,
        "summary": "Verification passed.",
        "findings": [],
    }

    with (
        patch(
            "app.workflows.fix_execution._load_fix_context",
            return_value=fix_context,
        ),
        patch(
            "app.workflows.fix_execution._start_request",
        ) as start_request,
        patch(
            "app.workflows.fix_execution._read_file",
            return_value="original source code",
        ),
        patch(
            "app.workflows.fix_execution.coding_agent.generate_fix",
            new_callable=AsyncMock,
            return_value=generated_file,
        ),
        patch(
            "app.workflows.fix_execution._publish_replacement",
        ) as publish,
        patch(
            "app.workflows.fix_execution._verify_replacement",
            return_value=verification_result,
        ),
        patch(
            "app.workflows.fix_execution._persist_post_fix_review",
            return_value={
                "review_id": str(uuid4()),
                "review_number": 2,
                "total_findings": 0,
                "passed": True,
            },
        ),
        patch(
            "app.workflows.fix_execution._complete_request",
        ) as complete,
    ):
        result = asyncio.run(
            execute_approved_fix(
                user_id=identifiers["user_id"],
                project_id=identifiers["project_id"],
                fix_request_id=identifiers["fix_request_id"],
            )
        )

    start_request.assert_called_once()
    publish.assert_called_once()
    complete.assert_called_once()

    assert result["status"] == "COMPLETED"
    assert result["verification"]["passed"] is True
    assert result["review"]["total_findings"] == 0


def test_execute_fix_rejects_wrong_generated_path(
    identifiers,
    fix_context,
):
    wrong_file = GeneratedFile(
        file_path="app/other.py",
        purpose="Unexpected file.",
        content="print('wrong file')",
    )

    with (
        patch(
            "app.workflows.fix_execution._load_fix_context",
            return_value=fix_context,
        ),
        patch(
            "app.workflows.fix_execution._start_request",
        ),
        patch(
            "app.workflows.fix_execution._read_file",
            return_value="original source code",
        ),
        patch(
            "app.workflows.fix_execution.coding_agent.generate_fix",
            new_callable=AsyncMock,
            return_value=wrong_file,
        ),
        patch(
            "app.workflows.fix_execution._fail_request",
        ) as fail_request,
    ):
        with pytest.raises(FixExecutionError):
            asyncio.run(
                execute_approved_fix(
                    user_id=identifiers["user_id"],
                    project_id=identifiers["project_id"],
                    fix_request_id=identifiers["fix_request_id"],
                )
            )

    fail_request.assert_called_once()


def test_execute_fix_fails_when_verification_fails(
    identifiers,
    fix_context,
    generated_file,
):
    verification_result = {
        "passed": False,
        "summary": "Verification failed.",
        "findings": [
            {
                "file_path": "app/main.py",
                "title": "SQL injection remains",
                "description": "Unsafe query remains.",
                "severity": "HIGH",
                "category": "SECURITY",
                "line_number": 25,
            }
        ],
    }

    with (
        patch(
            "app.workflows.fix_execution._load_fix_context",
            return_value=fix_context,
        ),
        patch(
            "app.workflows.fix_execution._start_request",
        ),
        patch(
            "app.workflows.fix_execution._read_file",
            return_value="original source code",
        ),
        patch(
            "app.workflows.fix_execution.coding_agent.generate_fix",
            new_callable=AsyncMock,
            return_value=generated_file,
        ),
        patch(
            "app.workflows.fix_execution._publish_replacement",
        ),
        patch(
            "app.workflows.fix_execution._verify_replacement",
            return_value=verification_result,
        ),
        patch(
            "app.workflows.fix_execution._fail_request",
        ) as fail_request,
    ):
        with pytest.raises(FixExecutionError):
            asyncio.run(
                execute_approved_fix(
                    user_id=identifiers["user_id"],
                    project_id=identifiers["project_id"],
                    fix_request_id=identifiers["fix_request_id"],
                )
            )

    fail_request.assert_called_once()


def test_execute_fix_does_not_publish_when_generation_fails(
    identifiers,
    fix_context,
):
    with (
        patch(
            "app.workflows.fix_execution._load_fix_context",
            return_value=fix_context,
        ),
        patch(
            "app.workflows.fix_execution._start_request",
        ),
        patch(
            "app.workflows.fix_execution._read_file",
            return_value="original source code",
        ),
        patch(
            "app.workflows.fix_execution.coding_agent.generate_fix",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM unavailable"),
        ),
        patch(
            "app.workflows.fix_execution._publish_replacement",
        ) as publish,
        patch(
            "app.workflows.fix_execution._fail_request",
        ),
    ):
        with pytest.raises(FixExecutionError):
            asyncio.run(
                execute_approved_fix(
                    user_id=identifiers["user_id"],
                    project_id=identifiers["project_id"],
                    fix_request_id=identifiers["fix_request_id"],
                )
            )

    publish.assert_not_called()