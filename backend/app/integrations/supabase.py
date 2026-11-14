"""Server-only Supabase client factory, called by the task service."""

from supabase import Client, create_client
from supabase.client import ClientOptions

from app.settings import Settings


class StorageUnavailable(Exception):
    """Storage is missing configuration or temporarily unreachable."""


def create_task_client() -> Client:
    settings = Settings()
    key = settings.supabase_service_role_key.get_secret_value() if settings.supabase_service_role_key else ""
    if not settings.supabase_url or not key:
        raise StorageUnavailable("Supabase is not configured.")
    return create_client(
        settings.supabase_url,
        key,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )
