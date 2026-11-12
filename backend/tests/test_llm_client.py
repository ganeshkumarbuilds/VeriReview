import asyncio

import httpx
import pytest

from app.core.config import settings
from app.services.llm_client import (
    LLMAPIError,
    LLMConfigurationError,
    OpenRouterClient,
)


def test_rejects_paid_model(monkeypatch):
    monkeypatch.setattr(
        settings,
        "OPENROUTER_MODEL",
        "some-model",
    )

    client = OpenRouterClient()

    with pytest.raises(LLMConfigurationError):
        client._validate_configuration()


def test_rejects_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        settings,
        "OPENROUTER_API_KEY",
        "",
    )

    monkeypatch.setattr(
        settings,
        "OPENROUTER_MODEL",
        "openrouter/free",
    )

    client = OpenRouterClient()

    with pytest.raises(LLMConfigurationError):
        client._validate_configuration()


def test_accepts_free_model(monkeypatch):
    monkeypatch.setattr(
        settings,
        "OPENROUTER_API_KEY",
        "test-key",
    )

    monkeypatch.setattr(
        settings,
        "OPENROUTER_MODEL",
        "openrouter/free",
    )

    client = OpenRouterClient()

    client._validate_configuration()


def test_successful_chat_completion(monkeypatch):
    async def run_test():
        monkeypatch.setattr(
            settings,
            "OPENROUTER_API_KEY",
            "test-key",
        )

        monkeypatch.setattr(
            settings,
            "OPENROUTER_MODEL",
            "openrouter/free",
        )

        client = OpenRouterClient()

        def handler(request):
            assert request.url.path == "/api/v1/chat/completions"

            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "Test response"
                            }
                        }
                    ]
                },
            )

        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        try:
            result = await client.chat_completion(
                messages=[
                    {
                        "role": "user",
                        "content": "Hello",
                    }
                ]
            )

            assert result == "Test response"

        finally:
            await client.close()

    asyncio.run(run_test())


def test_retries_rate_limit(monkeypatch):
    async def run_test():
        monkeypatch.setattr(
            settings,
            "OPENROUTER_API_KEY",
            "test-key",
        )

        monkeypatch.setattr(
            settings,
            "OPENROUTER_MODEL",
            "openrouter/free",
        )

        monkeypatch.setattr(
            settings,
            "OPENROUTER_MAX_RETRIES",
            1,
        )

        client = OpenRouterClient()

        attempts = 0

        def handler(request):
            nonlocal attempts
            attempts += 1

            if attempts == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                )

            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "Recovered"
                            }
                        }
                    ]
                },
            )

        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        )

        try:
            result = await client.chat_completion(
                messages=[
                    {
                        "role": "user",
                        "content": "Test retry",
                    }
                ]
            )

            assert result == "Recovered"
            assert attempts == 2

        finally:
            await client.close()

    asyncio.run(run_test())


def test_rejects_empty_messages():
    async def run_test():
        client = OpenRouterClient()

        with pytest.raises(ValueError):
            await client.chat_completion(messages=[])

    asyncio.run(run_test())