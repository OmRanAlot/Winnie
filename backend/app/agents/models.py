"""Explicit Gemini Developer API setup; secrets can come from the root .env."""

from app.settings import Settings


def planning_model(model, settings: Settings | None = None):
    """Keep other model strings/instances supported by the Deep Agents harness."""
    if not isinstance(model, str) or not model.startswith("google_genai:"):
        return model
    settings = settings or Settings()
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
    model_id = model.removeprefix("google_genai:").strip()
    if not key or not model_id:
        raise ValueError("Configure GEMINI_API_KEY and a google_genai model ID.")
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model_id, api_key=key, vertexai=False,
        timeout=settings.planning_timeout_seconds, max_retries=1,
    )
