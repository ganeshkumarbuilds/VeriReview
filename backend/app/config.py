import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


load_dotenv()


# ============================================================
# LLM CONFIGURATION
# ============================================================
#
# VeriReview uses an OpenAI-compatible API.
#
# Default provider:
#   OpenRouter
#
# Default free router:
#   openrouter/free
#
# The actual API key MUST come from the backend environment.
# Never put this key in the React frontend.
# ============================================================

LLM_BASE_URL = (
    os.getenv("LLM_BASE_URL")
    or "https://openrouter.ai/api/v1"
).strip().rstrip("/")

LLM_API_KEY = (
    os.getenv("LLM_API_KEY")
    or ""
).strip()


# Explicit model selection.
#
# Recommended for development:
#
#   LLM_MODEL=openrouter/free
#
# OpenRouter's free router dynamically selects an available
# free model instead of depending on hard-coded model names.
LLM_MODEL = (
    os.getenv("LLM_MODEL")
    or "openrouter/free"
).strip()


# Optional explicit model list.
#
# This exists mainly for advanced configuration/testing.
#
# Example:
#
#   LLM_MODELS=model-a,model-b
#
# If LLM_MODELS is not provided, VeriReview uses LLM_MODEL.
def _resolve_models():
    override = (os.getenv("LLM_MODELS") or "").strip()

    if override:
        models = [
            model.strip()
            for model in override.split(",")
            if model.strip()
        ]

        if models:
            return models

    return [LLM_MODEL]


FREE_MODELS = _resolve_models()


# ============================================================
# LLM CLIENT
# ============================================================

def get_llm(
    model_name: str = None,
    temperature: float = 0.2,
) -> ChatOpenAI:
    """
    Create the LangChain OpenAI-compatible chat client.

    If model_name is omitted, use the configured LLM_MODEL.
    """

    selected_model = (
        model_name or LLM_MODEL
    ).strip()

    return ChatOpenAI(
        model=selected_model,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=temperature,
        request_timeout=120,
        max_retries=1,
    )