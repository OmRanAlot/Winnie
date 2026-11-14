"""Environment configuration for the backend.

Values come from environment variables prefixed WINNIE_ (e.g. WINNIE_CORS_ORIGINS), or from a
.env file at the REPOSITORY ROOT (copy .env.example there). Imported by app/main.py.
Planned settings for the integrations are listed in app/__init__.py.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/app/settings.py -> repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WINNIE_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Winnie API"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]
