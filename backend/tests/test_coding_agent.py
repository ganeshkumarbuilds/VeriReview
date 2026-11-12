import asyncio
import json

import pytest

from app.agents.coding import (
    CodingAgent,
    CodingAgentError,
    CodingOutputError,
    GeneratedFile,
)


def run_async(coroutine):
    return asyncio.run(
        coroutine,
        loop_factory=asyncio.SelectorEventLoop,
    )


def test_parse_valid_json():
    response = json.dumps({
        "file_path": "src/main.py",
        "purpose": "Application entry point",
        "content": "print('Hello')",
    })

    result = CodingAgent._parse_response(response)

    assert result["file_path"] == "src/main.py"
    assert result["content"] == "print('Hello')"


def test_parse_markdown_json():
    response = """```json
{
    "file_path": "main.py",
    "purpose": "Entry point",
    "content": "print('Hello')"
}
```"""

    result = CodingAgent._parse_response(response)

    assert result["file_path"] == "main.py"


def test_reject_invalid_json():
    with pytest.raises(CodingOutputError):
        CodingAgent._parse_response("invalid json")


def test_reject_non_object_json():
    with pytest.raises(CodingOutputError):
        CodingAgent._parse_response('["invalid"]')


def test_reject_empty_response():
    with pytest.raises(CodingOutputError):
        CodingAgent._parse_response("")


def test_generated_file_validation():
    result = GeneratedFile(
        file_path="src/main.py",
        purpose="Entry point",
        content="print('Hello')",
    )

    result.validate_path()

    assert result.file_path == "src/main.py"


def test_generated_file_rejects_unsafe_path():
    result = GeneratedFile(
        file_path="../secret.py",
        purpose="Unsafe file",
        content="print('Hello')",
    )

    with pytest.raises(ValueError):
        result.validate_path()


def test_successful_file_generation(monkeypatch):
    agent = CodingAgent()

    response = json.dumps({
        "file_path": "src/main.py",
        "purpose": "Application entry point",
        "content": "print('VeriReview')",
    })

    async def mock_completion(**kwargs):
        return response

    monkeypatch.setattr(
        "app.agents.coding.llm_client.chat_completion",
        mock_completion,
    )

    result = run_async(
        agent.generate_file(
            requirements="Build a Python application.",
            architecture={"overview": "Modular architecture"},
            implementation_plan={"phases": []},
            file_path="src/main.py",
            file_purpose="Application entry point",
            technology_stack="Python",
        )
    )

    assert result.file_path == "src/main.py"
    assert result.content == "print('VeriReview')"


def test_generation_rejects_wrong_file_path(monkeypatch):
    agent = CodingAgent()

    async def mock_completion(**kwargs):
        return json.dumps({
            "file_path": "src/other.py",
            "purpose": "Wrong file",
            "content": "print('Wrong')",
        })

    monkeypatch.setattr(
        "app.agents.coding.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(CodingOutputError):
        run_async(
            agent.generate_file(
                requirements="Build a Python application.",
                architecture={},
                implementation_plan={},
                file_path="src/main.py",
                file_purpose="Application entry point",
            )
        )


def test_generation_rejects_empty_requirements():
    agent = CodingAgent()

    with pytest.raises(ValueError):
        run_async(
            agent.generate_file(
                requirements="",
                architecture={},
                implementation_plan={},
                file_path="main.py",
                file_purpose="Entry point",
            )
        )


def test_generation_handles_llm_failure(monkeypatch):
    agent = CodingAgent()

    async def mock_completion(**kwargs):
        from app.services.llm_client import LLMAPIError
        raise LLMAPIError("Simulated failure")

    monkeypatch.setattr(
        "app.agents.coding.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(CodingAgentError):
        run_async(
            agent.generate_file(
                requirements="Build an application.",
                architecture={},
                implementation_plan={},
                file_path="main.py",
                file_purpose="Entry point",
            )
        )