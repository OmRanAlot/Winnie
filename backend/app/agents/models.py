"""Chat-model setup for the planning agents.

planning_model() turns the WINNIE_PLANNING_MODEL setting (or a model instance passed by tests)
into something Deep Agents can use. Only "google_genai:<model id>" strings are configured here,
explicitly against the Gemini Developer API with the key from settings. Any other string, such
as "openai:gpt-x", or any model instance is passed through untouched for the harness to resolve.

describe_model() is the only way a model should appear in a log line: a string is shown as is,
anything else by class name, so API keys held on a model object can never be logged.
"""

import logging

from app.core.settings import Settings

logger = logging.getLogger(__name__)

GEMINI_PREFIX = "google_genai:"
GEMINI_MAX_RETRIES = 1  # the pipeline has its own overall timeout, so retry sparingly


def describe_model(model) -> str:
    """Log-safe name for a model: the "provider:id" string, or the instance's class name."""
    return model if isinstance(model, str) else type(model).__name__


def planning_model(model, settings: Settings | None = None):
    """Return a model Deep Agents can run. Raises ValueError if Gemini is selected but unset."""
    if not isinstance(model, str) or not model.startswith(GEMINI_PREFIX):
        return model
    settings = settings or Settings()
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    model_id = model.removeprefix(GEMINI_PREFIX).strip()
    if not key or not model_id:
        logger.error("Gemini planning model requested but the API key or model id is missing")
        raise ValueError("Configure GEMINI_API_KEY and a google_genai model ID.")
    from langchain_google_genai import ChatGoogleGenerativeAI

    logger.debug("building Gemini chat model id=%s timeout=%ss",
                 model_id, settings.planning_timeout_seconds)
    return ChatGoogleGenerativeAI(
        model=model_id, api_key=key, vertexai=False,
        timeout=settings.planning_timeout_seconds, max_retries=GEMINI_MAX_RETRIES,
    )
