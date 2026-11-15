"""Preview an invitation for a consenting roster email; --send explicitly sends the email.

Run from backend/: uv run python -m app.cli.invite_member EMAIL [--send]
No temporary passwords are generated. The recipient chooses a password through the email link.
"""

import argparse
from urllib.parse import urlsplit

from httpx import HTTPError
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthError

from app.integrations.supabase import StorageUnavailable, create_task_client

DEFAULT_REDIRECT_TO = "https://hack-princeton-514716.web.app/auth/set-password"


def prepare_invitation(client, email: str, redirect_to: str):
    email = email.strip().lower()
    url = urlsplit(redirect_to)
    if (url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
    )) or not url.hostname or url.username or url.password or url.fragment or url.query:
        raise ValueError("Use an HTTPS callback URL, or HTTP localhost for development.")
    if url.path != "/auth/set-password":
        raise ValueError("Invitation callback must end with /auth/set-password.")
    rows = client.table("members").select("code,display_name,email,active,contact_consent").eq(
        "email", email
    ).execute().data
    if len(rows) != 1 or not rows[0].get("active") or not rows[0].get("contact_consent"):
        raise ValueError("Email must belong to one active, consenting roster member.")
    # Check the final schema before creating an invitation that cannot be completed.
    client.table("profiles").select("password_setup_complete,member_code").limit(1).execute()
    return {"email": email, "options": {
        "redirect_to": redirect_to, "data": {"name": rows[0]["display_name"]},
    }}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument(
        "--redirect-to", default=DEFAULT_REDIRECT_TO,
        help="Password setup callback (defaults to the deployed Winnie site).",
    )
    parser.add_argument("--send", action="store_true", help="Send this invitation through Supabase Auth.")
    args = parser.parse_args(argv)
    client = create_task_client()
    try:
        invitation = prepare_invitation(client, args.email, args.redirect_to)
        if not args.send:
            print("Roster and auth schema verified. Preview only; no email sent.")
            print(f"Callback: {args.redirect_to}")
            print("Add --send to send this invitation after SMTP and redirect URLs are configured.")
            return
        client.auth.admin.invite_user_by_email(invitation["email"], invitation["options"])
        print("Invitation submitted to Supabase Auth. The recipient can set their own password.")
    finally:
        client.postgrest.session.close()


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)
    except (AuthError, APIError, HTTPError, OSError, StorageUnavailable) as exc:
        print(f"Invitation setup failed ({type(exc).__name__}). Check migrations, SMTP and Auth configuration.")
        raise SystemExit(1)
