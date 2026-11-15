"""Environment configuration for the backend.

Values come from environment variables prefixed WINNIE_ (e.g. WINNIE_CORS_ORIGINS), or from a
.env file at the REPOSITORY ROOT or in backend/ (copy .env.example there). Imported by app/main.py,
services/task_assignment.py and integrations/supabase_client.py.
Planned settings for the integrations are listed in app/__init__.py.
"""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/app/core/settings.py -> repo root


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WINNIE_",
        # backend/.env.example says to copy it to backend/.env, so read that too.
        # Later files win: the .env.local files are the "local mode" overrides (WINNIE_MODE=local).
        # They are gitignored and excluded from the Docker / gcloud builds (.env.*), so they
        # can never reach a deployment.
        env_file=(
            REPO_ROOT / ".env",
            REPO_ROOT / "backend" / ".env",
            REPO_ROOT / ".env.local",
            REPO_ROOT / "backend" / ".env.local",
        ),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    task_transcript_source: Literal["example", "recording"] = "example"

    app_name: str = "Winnie API"
    # WINNIE_MODE: "local" for any local testing (set in .env.local, see .env.local.example),
    # "prod" for deployments. Defaults to "prod" so a deploy that sets nothing is safe.
    mode: Literal["local", "prod"] = "prod"
    environment: str = "development"
    log_level: str = "INFO"  # WINNIE_LOG_LEVEL=DEBUG for more detail
    cors_origins: list[str] = ["http://localhost:5173"]

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

    # Gemini (services/task_assignment.py). Read from the unprefixed names used in
    # .env.example; the WINNIE_-prefixed names also work.
    # GOOGLE_API_KEY takes precedence over GEMINI_API_KEY. SecretStr keeps it out of reprs.
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY", "WINNIE_GEMINI_API_KEY"),
    )
    gemini_model: str = Field(
        default="gemini-3.8-flash",
        validation_alias=AliasChoices("GEMINI_MODEL", "WINNIE_GEMINI_MODEL"),
    )

    # Supabase task store (integrations/supabase_client.py). Server-side only: the secret
    # key bypasses row-level security, so it must never reach the frontend or the logs.
    # SecretStr keeps it out of reprs and tracebacks.
    supabase_url: str | None = Field(
        default=None, validation_alias=AliasChoices("SUPABASE_URL", "WINNIE_SUPABASE_URL")
    )
    supabase_service_role_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SUPABASE_SECRET_KEY", "WINNIE_SUPABASE_SECRET_KEY",
            "SUPABASE_SERVICE_ROLE_KEY", "WINNIE_SUPABASE_SERVICE_ROLE_KEY",
        ),
    )

    # Shared secret for the task-records CRUD endpoints (routes/tasks.py, X-Winnie-Api-Key header).
    task_api_key: SecretStr = SecretStr("")

    @property
    def is_local(self) -> bool:
        return self.mode == "local"

