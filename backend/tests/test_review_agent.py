import asyncio
import json

import pytest

from app.agents.review import (
    ReviewAgent,
    ReviewAgentError,
    ReviewOutputError,
    ReviewResult,
)


def run_async(coroutine):
    return asyncio.run(
        coroutine,
        loop_factory=asyncio.SelectorEventLoop,
    )


def sample_finding():
    return {
        "file_path": "main.py",
        "title": "Unsafe input handling",
        "description": "Input is not validated.",
        "severity": "HIGH",
        "category": "SECURITY",
        "line_number": 4,
        "suggested_fix": "Validate input.",
    }


def valid_review():
    return json.dumps({
        "summary": "One security issue requires attention.",
        "total_findings": 1,
        "critical_count": 0,
        "high_count": 1,
        "medium_count": 0,
        "low_count": 0,
        "requires_user_approval": True,
        "findings": [
            {
                **sample_finding(),
                "recommended_action": "Request user approval.",
            }
        ],
    })


def test_parse_valid_json():
    result = ReviewAgent._parse_response(valid_review())

    assert result["total_findings"] == 1


def test_parse_markdown_json():
    response = f"```json\n{valid_review()}\n```"

    result = ReviewAgent._parse_response(response)

    assert result["requires_user_approval"] is True


def test_reject_invalid_json():
    with pytest.raises(ReviewOutputError):
        ReviewAgent._parse_response("invalid")


def test_reject_non_object_json():
    with pytest.raises(ReviewOutputError):
        ReviewAgent._parse_response('["invalid"]')


def test_reject_empty_response():
    with pytest.raises(ReviewOutputError):
        ReviewAgent._parse_response("")


def test_review_result_schema():
    result = ReviewResult.model_validate(
        json.loads(valid_review())
    )

    assert result.total_findings == 1
    assert result.high_count == 1


def test_reject_missing_findings():
    agent = ReviewAgent()

    with pytest.raises(ValueError):
        run_async(
            agent.review({})
        )


def test_successful_review(monkeypatch):
    agent = ReviewAgent()

    async def mock_completion(**kwargs):
        return valid_review()

    monkeypatch.setattr(
        "app.agents.review.llm_client.chat_completion",
        mock_completion,
    )

    result = run_async(
        agent.review({
            "findings": [sample_finding()],
        })
    )

    assert result.total_findings == 1
    assert result.high_count == 1
    assert result.requires_user_approval is True


def test_reject_inconsistent_finding_count(monkeypatch):
    agent = ReviewAgent()

    async def mock_completion(**kwargs):
        result = json.loads(valid_review())
        result["total_findings"] = 5
        return json.dumps(result)

    monkeypatch.setattr(
        "app.agents.review.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(ReviewOutputError):
        run_async(
            agent.review({
                "findings": [sample_finding()],
            })
        )


def test_reject_inconsistent_severity_counts(monkeypatch):
    agent = ReviewAgent()

    async def mock_completion(**kwargs):
        result = json.loads(valid_review())
        result["high_count"] = 3
        return json.dumps(result)

    monkeypatch.setattr(
        "app.agents.review.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(ReviewOutputError):
        run_async(
            agent.review({
                "findings": [sample_finding()],
            })
        )


def test_reject_missing_user_approval(monkeypatch):
    agent = ReviewAgent()

    async def mock_completion(**kwargs):
        result = json.loads(valid_review())
        result["requires_user_approval"] = False
        return json.dumps(result)

    monkeypatch.setattr(
        "app.agents.review.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(ReviewOutputError):
        run_async(
            agent.review({
                "findings": [sample_finding()],
            })
        )


def test_handles_llm_failure(monkeypatch):
    agent = ReviewAgent()

    async def mock_completion(**kwargs):
        from app.services.llm_client import LLMAPIError
        raise LLMAPIError("Simulated failure")

    monkeypatch.setattr(
        "app.agents.review.llm_client.chat_completion",
        mock_completion,
    )

    with pytest.raises(ReviewAgentError):
        run_async(
            agent.review({
                "findings": [sample_finding()],
            })
        )