"""Environment-driven settings. Fails loudly (naming the variable, never its value) when missing."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, cast

OwnerCodeKind = Literal["seat", "person", "mixed"]
_OWNER_KINDS = ("seat", "person", "mixed")


class ConfigError(RuntimeError):
    """A required environment variable is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None
    supabase_service_role_key: str | None
    supabase_db_url: str | None
    anthropic_api_key: str | None
    summary_model: str | None
    extraction_model: str | None
    whisper_model: str
    audio_bucket: str
    owner_code_kind: OwnerCodeKind

    def __repr__(self) -> str:  # never leak secrets via repr/logging
        return "Settings(<redacted>)"


def load_settings(require: Iterable[str] = (), env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env` (default os.environ, plus a .env file if python-dotenv is
    present). `require` lists ENV VAR NAMES that must be set and non-empty; all missing ones are
    reported together."""
    if env is None:
        _load_dotenv()
    source: Mapping[str, str] = os.environ if env is None else env

    def get(name: str) -> str | None:
        value = source.get(name, "").strip()
        return value or None

    missing = [name for name in require if get(name) is None]
    if missing:
        raise ConfigError(
            "Missing required environment variable(s): " + ", ".join(missing) + ". See .env.example."
        )
    kind = (get("OWNER_CODE_KIND") or "seat").lower()
    if kind not in _OWNER_KINDS:
        raise ConfigError(f"OWNER_CODE_KIND must be one of {_OWNER_KINDS}, got {kind!r}")
    return Settings(
        supabase_url=get("SUPABASE_URL"),
        supabase_service_role_key=get("SUPABASE_SERVICE_ROLE_KEY"),
        supabase_db_url=get("SUPABASE_DB_URL"),
        anthropic_api_key=get("ANTHROPIC_API_KEY"),
        summary_model=get("SUMMARY_MODEL"),
        extraction_model=get("EXTRACTION_MODEL"),
        whisper_model=get("WHISPER_MODEL") or "small",
        audio_bucket=get("AUDIO_BUCKET") or "meeting-audio",
        owner_code_kind=cast(OwnerCodeKind, kind),
    )


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # optional convenience
        return
    load_dotenv(override=False)
