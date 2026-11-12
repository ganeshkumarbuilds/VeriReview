import asyncio

import pytest

from app.agents.planning import (
    PlanningAgent,
    PlanningAgentError,
    PlanningOutputError,
    PlanningResult,
)


VALID_PLAN = {
    "architecture": {
        "overview": "Three-tier architecture",
        "components": ["Frontend", "Backend", "Database"],
        "technology_decisions": ["React", "FastAPI", "PostgreSQL"],
        "data_flow": ["Frontend to Backend", "Backend to Database"],
        "assumptions": [],
    },
    "folder_structure": {
        "root": "sample-project",
        "directories": ["src", "tests"],
        "files": ["main.py", "README.md"],
    },
    "implementation_plan": {
        "phases": ["Backend", "Frontend", "Testing"],
        "dependencies": [],
        "milestones": ["MVP"],
    },
    "estimated_files": 2,
}


def test_parse_valid_json():
    result = PlanningAgent._parse_response(
        __import__("json").dumps(VALID_PLAN)
    )

    assert result == VALID_PLAN


def test_parse_markdown_json():
    import json

    response = f"```json\n{json.dumps(VALID_PLAN)}\n```"

    result = PlanningAgent._parse_response(response)

    assert result == VALID_PLAN


def test_reject_invalid_json():
    with pytest.raises(PlanningOutputError):
        PlanningAgent._parse_response("{invalid json}")


def test_reject_non_object_json():
    with pytest.raises(PlanningOutputError):
        PlanningAgent._parse_response('["not", "an", "object"]')


def test_reject_empty_requirements():
    agent = PlanningAgent()

    with pytest.raises(ValueError):
        asyncio.run(agent.plan("   "))


def test_reject_invalid_planning_schema():
    invalid_plan = {
        "architecture": {},
        "folder_structure": {},
        "implementation_plan": {},
        "estimated_files": -1,
    }

    with pytest.raises(Exception):
        PlanningResult.model_validate(invalid_plan)


def test_successful_planning(monkeypatch):
    async def mock_chat_completion(**kwargs):
        return __import__("json").dumps(VALID_PLAN)

    agent = PlanningAgent()

    monkeypatch.setattr(
        "app.agents.planning.llm_client.chat_completion",
        mock_chat_completion,
    )

    result = asyncio.run(
        agent.plan(
            requirements="Build a task management application.",
            technology_stack="React, FastAPI, PostgreSQL",
        )
    )

    assert isinstance(result, PlanningResult)
    assert result.architecture["overview"] == "Three-tier architecture"
    assert result.estimated_files == 2


def test_llm_failure_is_handled(monkeypatch):
    from app.services.llm_client import LLMAPIError

    async def mock_chat_completion(**kwargs):
        raise LLMAPIError("Simulated API failure")

    agent = PlanningAgent()

    monkeypatch.setattr(
        "app.agents.planning.llm_client.chat_completion",
        mock_chat_completion,
    )

    with pytest.raises(PlanningAgentError):
        asyncio.run(
            agent.plan("Build a task management application.")
        )