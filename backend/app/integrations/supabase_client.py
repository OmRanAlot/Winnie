"""The one Supabase client the backend uses (supabase-py, service-role key, server side only).

Called by app/repository.py. Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY through
app/settings.py and fails loudly (SupabaseNotConfigured) when either is missing. The key is
never logged: only whether it is set.
"""

import logging
from functools import lru_cache

from supabase import Client, create_client

from app.settings import Settings

logger = logging.getLogger(__name__)


class SupabaseNotConfigured(RuntimeError):
    """SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing from the environment / .env."""


def require_credentials(settings: Settings) -> tuple[str, str]:
    """Return (url, service_role_key), or raise naming every missing variable (never the value)."""
    url = settings.supabase_url
    key = settings.supabase_service_role_key.get_secret_value() if settings.supabase_service_role_key else ""
    missing = [name for name, value in (("SUPABASE_URL", url), ("SUPABASE_SERVICE_ROLE_KEY", key)) if not value]
    if missing or not url:
        raise SupabaseNotConfigured(
            f"Missing {', '.join(missing)}. Copy .env.example to .env and fill them in "
            "(Supabase dashboard -> Project Settings -> API)."
        )
    return url, key


@lru_cache(maxsize=1)
def get_client() -> Client:
    """Process-wide singleton. Raises SupabaseNotConfigured when credentials are missing."""
    url, key = require_credentials(Settings())
    logger.info("Connecting to Supabase at %s (service-role key set)", url)
    return create_client(url, key)
