"""Read-only authentication readiness report. Never prints contact details, passwords or API keys."""

import base64
import binascii
import json
from pathlib import Path

from dotenv import dotenv_values
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.core.settings import REPO_ROOT, Settings
from app.integrations.supabase import StorageUnavailable, create_task_client


def main():
    frontend = {}
    for name in (".env", ".env.local"):
        path = Path(REPO_ROOT) / "frontend" / name
        if path.exists():
            frontend.update(dotenv_values(path))
    settings = Settings()
    key = frontend.get("VITE_SUPABASE_PUBLISHABLE_KEY") or ""
    public_key = key.startswith("sb_publishable_")
    if not public_key and key.count(".") == 2:
        try:
            payload = key.split(".")[1]
            public_key = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role") == "anon"
        except (ValueError, binascii.Error, UnicodeDecodeError):
            public_key = False
    report = {
        "backend_configured": bool(settings.supabase_url and settings.supabase_service_role_key),
        "frontend_configured": bool(frontend.get("VITE_SUPABASE_URL")
                                    and frontend.get("VITE_SUPABASE_PUBLISHABLE_KEY")),
        "frontend_key_is_publishable": public_key,
        "frontend_matches_backend": frontend.get("VITE_SUPABASE_URL", "").rstrip("/") == (
            settings.supabase_url or ""
        ).rstrip("/"),
        "auth_schema_ready": False,
        "eligible_roster_members": None,
        "smtp_and_redirect_settings": "Check in Supabase dashboard; not exposed by the database API.",
    }
    client = None
    try:
        client = create_task_client()
        try:
            client.table("profiles").select("member_code,password_setup_complete").limit(1).execute()
            report["auth_schema_ready"] = True
        except APIError:
            report["database_action"] = "Apply the final authentication migration."
        result = client.table("members").select("code", count="exact").eq(
            "active", True
        ).eq("contact_consent", True).not_.is_("email", "null").limit(1).execute()
        report["eligible_roster_members"] = result.count
    except (StorageUnavailable, APIError, HTTPError):
        report["database_action"] = "Check credentials and apply the final authentication migration."
    finally:
        if client is not None:
            client.postgrest.session.close()
    print(json.dumps(report, indent=2))
    return all(report[key] for key in (
        "backend_configured", "frontend_configured", "frontend_key_is_publishable",
        "frontend_matches_backend", "auth_schema_ready"
    ))


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
