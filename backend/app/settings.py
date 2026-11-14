"""Environment configuration for the backend.

Values come from environment variables prefixed WINNIE_ (e.g. WINNIE_CORS_ORIGINS), or from a
.env file at the REPOSITORY ROOT or in backend/ (copy .env.example there). Imported by app/main.py
and routes/assign_task_from_gemini.py.
Planned settings for the integrations are listed in app/__init__.py.
"""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]  # backend/app/settings.py -> repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WINNIE_",
        # backend/.env.example says to copy it to backend/.env, so read that too.
        env_file=(REPO_ROOT / ".env", REPO_ROOT / "backend" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    task_transcript_source: Literal["example", "recording"] = "example"

    app_name: str = "Winnie API"
    environment: str = "development"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Gemini (routes/assign_task_from_gemini.py). Read from the unprefixed names used in
    # .env.example; the WINNIE_-prefixed names also work.
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEY", "WINNIE_GEMINI_API_KEY")
    )
    gemini_model: str = Field(
        default="gemini-3.8-flash",
        validation_alias=AliasChoices("GEMINI_MODEL", "WINNIE_GEMINI_MODEL"),
    )
