"""Environment configuration for the backend.

Values come from environment variables prefixed WINNIE_ (e.g. WINNIE_CORS_ORIGINS), or from a
.env file at the REPOSITORY ROOT (copy .env.example there). Imported by app/main.py.
Planned settings for the integrations are listed in app/__init__.py.
"""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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
    supabase_url: str = ""
    supabase_secret_key: SecretStr = SecretStr("")
    task_api_key: SecretStr = SecretStr("")
    messaging_bridge_secret: SecretStr = SecretStr("")
    active_semester: str = "fall-2026"
    planning_mode: Literal["mock", "deepagents"] = "mock"
    planning_model: str = ""
    planning_knowledge_path: Path = Path("backend/data/planning/fall-2026.json")
    planning_taxonomy_path: Path = Path("backend/data/planning/spring-2027-taxonomy.json")
    planning_roster_path: Path | None = None
    planning_history_semester: str = "fall-2026"
    planning_timeout_seconds: float = Field(default=60, gt=0, le=180)
    planning_pipeline_timeout_seconds: float = Field(default=180, gt=0, le=600)
    gemini_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY")
    )
