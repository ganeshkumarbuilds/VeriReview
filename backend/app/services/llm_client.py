import asyncio
import logging
from typing import Any

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Base exception for LLM client errors."""


class LLMConfigurationError(LLMClientError):
    """Raised when the LLM configuration is invalid."""


class LLMAPIError(LLMClientError):
    """Raised when the LLM API request fails."""


class OpenRouterClient:
    """
    Centralized asynchronous OpenRouter client.

    All VeriReview agents will use this client.
    Only free models are permitted.
    """

    def __init__(self) -> None:
        self.base_url = settings.OPENROUTER_BASE_URL.rstrip("/")
        self.model = settings.OPENROUTER_MODEL
        self.timeout = settings.OPENROUTER_TIMEOUT
        self.max_retries = settings.OPENROUTER_MAX_RETRIES

        self._client: httpx.AsyncClient | None = None

    def _validate_configuration(self) -> None:
        if not settings.OPENROUTER_API_KEY:
            raise LLMConfigurationError(
                "OPENROUTER_API_KEY is not configured."
            )

        if not (
            self.model == "openrouter/free"
            or self.model.endswith(":free")
        ):
            raise LLMConfigurationError(
                "Only OpenRouter free models are permitted."
            )

        if not self.base_url.startswith("https://"):
            raise LLMConfigurationError(
                "OpenRouter must use an HTTPS endpoint."
            )

    async def start(self) -> None:
        """Initialize the asynchronous HTTP client."""

        if self._client is not None:
            return

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )

    async def close(self) -> None:
        """Close the asynchronous HTTP client."""

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """
        Send a chat completion request to OpenRouter.

        Retries transient network errors, rate limits,
        and server errors. Never falls back to paid models.
        """

        self._validate_configuration()

        if not messages:
            raise ValueError("Messages cannot be empty.")

        if self._client is None:
            await self.start()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens is not None:
            if max_tokens < 1:
                raise ValueError("max_tokens must be positive.")

            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": settings.APP_NAME,
        }

        endpoint = f"{self.base_url}/chat/completions"

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                )

                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_retries:
                        retry_after = response.headers.get("Retry-After")

                        try:
                            delay = float(retry_after) if retry_after else 2 ** attempt
                        except ValueError:
                            delay = 2 ** attempt

                        await asyncio.sleep(min(delay, 30))
                        continue

                response.raise_for_status()

                data = response.json()

                content = data["choices"][0]["message"]["content"]

                if not isinstance(content, str) or not content.strip():
                    raise LLMAPIError(
                        "OpenRouter returned an empty response."
                    )

                return content.strip()

            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 30))
                    continue

                logger.error(
                    "OpenRouter network request failed: %s",
                    type(exc).__name__,
                )

                raise LLMAPIError(
                    "Unable to connect to OpenRouter."
                ) from exc

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "OpenRouter returned HTTP status %s.",
                    exc.response.status_code,
                )

                raise LLMAPIError(
                    f"OpenRouter request failed with HTTP "
                    f"{exc.response.status_code}."
                ) from exc

            except (KeyError, IndexError, TypeError, ValueError) as exc:
                if isinstance(exc, LLMAPIError):
                    raise

                raise LLMAPIError(
                    "OpenRouter returned an invalid response."
                ) from exc

        raise LLMAPIError(
            "OpenRouter request failed after all retry attempts."
        )


llm_client = OpenRouterClient()