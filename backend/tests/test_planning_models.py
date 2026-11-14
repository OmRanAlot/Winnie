"""Provider configuration tests use synthetic keys and never make model requests."""

import pytest

from app.agents.models import planning_model
from app.settings import Settings


def key_value(settings):
    key = settings.gemini_api_key
    return key.get_secret_value() if hasattr(key, "get_secret_value") else key


def test_gemini_key_loaded_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=synthetic-key\n", encoding="utf-8")
    settings = Settings(_env_file=dotenv)
    assert key_value(settings) == "synthetic-key"
    assert "synthetic-key" not in repr(settings)


def test_gemini_alias_precedence(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "primary-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fallback-test-key")
    assert key_value(Settings(_env_file=None)) == "fallback-test-key"


def test_missing_gemini_key_fails_before_model_creation(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        planning_model("google_genai:example", Settings(_env_file=None))


def test_gemini_explicit_configuration(monkeypatch):
    package = pytest.importorskip("langchain_google_genai")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    captured = {}

    def fake_model(**kwargs):
        captured.update(kwargs)
        return "configured-model"

    monkeypatch.setattr(package, "ChatGoogleGenerativeAI", fake_model)
    result = planning_model("google_genai:example", Settings(_env_file=None))
    assert result == "configured-model"
    assert captured == {
        "model": "example", "api_key": "synthetic-key", "vertexai": False,
        "timeout": 60, "max_retries": 1,
    }


def test_other_models_are_passed_through():
    assert planning_model("openai:example") == "openai:example"
    instance = object()
    assert planning_model(instance) is instance
