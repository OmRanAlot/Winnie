"""Create a confirmed, non-admin Auth login for local UI testing; run manually with --create.

Uses the repository-root Supabase settings. Stores credentials only in gitignored backend/data/.
Never call this module from a request handler or seed a known password into a migration.
"""

import argparse
import json
import secrets
from pathlib import Path

from httpx import HTTPError
from supabase_auth.errors import AuthError

from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable, create_task_client

CREDENTIALS_PATH = Path(__file__).resolve().parents[2] / "data" / "demo-login.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", help="Create a demo Auth account if needed.")
    args = parser.parse_args()
    if not args.create:
        parser.error("Pass --create to create a demo Auth account and save its credentials locally.")

    url = Settings().supabase_url
    client = create_task_client()
    try:
        if CREDENTIALS_PATH.exists():
            credentials = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
            if credentials["supabase_url"] != url:
                raise ValueError("Demo credentials belong to another project; move that file first.")
        else:
            # Open the file before creating the account so a disk failure cannot lose its password.
            CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
            credentials = {
                "supabase_url": url,
                "email": f"winnie-demo-{secrets.token_hex(4)}@example.com",
                "password": f"Wi9!{secrets.token_urlsafe(24)}",
            }
            with CREDENTIALS_PATH.open("x", encoding="utf-8") as handle:
                json.dump(credentials, handle, indent=2)
                handle.flush()
                result = client.auth.admin.create_user({
                    "email": credentials["email"],
                    "password": credentials["password"],
                    "email_confirm": True,
                    "user_metadata": {"name": "Winnie Demo Member"},
                })
                if result.user is None:
                    raise RuntimeError("Auth did not return a demo user.")

        result = client.auth.sign_in_with_password({
            "email": credentials["email"], "password": credentials["password"],
        })
        if result.session is None:
            raise RuntimeError("Auth did not return a login session.")
        print("Demo email/password login verified.")
        print(f"Credentials saved in {CREDENTIALS_PATH}")
        print("This is a regular account; it has no admin privileges.")
    finally:
        client.postgrest.session.close()


if __name__ == "__main__":
    try:
        main()
    except (AuthError, HTTPError, OSError, ValueError, RuntimeError, StorageUnavailable) as exc:
        # Provider exceptions can contain request details. Do not print passwords or tokens.
        print(f"Demo account setup failed ({type(exc).__name__}). Check Supabase configuration.")
        raise SystemExit(1)
