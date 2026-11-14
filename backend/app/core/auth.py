"""Verify Supabase access tokens and approved roster membership for HTTP callers."""

from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request
from postgrest.exceptions import APIError

from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable, create_task_client


@dataclass
class Principal:
    user_id: str
    profile: dict
    service: bool = False

    @property
    def is_admin(self):
        return self.profile.get("is_admin") is True


def verify_token(token: str, settings: Settings) -> dict:
    """Ask Auth to verify the token, rather than trusting browser claims or decoding unsigned JWTs."""
    key = settings.supabase_service_role_key
    if not settings.supabase_url or not key:
        raise HTTPException(503, "Authentication is not configured.")
    try:
        response = httpx.get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
            headers={"apikey": key.get_secret_value(), "Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if response.status_code in (401, 403):
            raise HTTPException(401, "Your session expired. Please sign in again.",
                                headers={"WWW-Authenticate": "Bearer"})
        response.raise_for_status()
        user = response.json()
        UUID(user["id"])
        if not user.get("email_confirmed_at"):
            raise HTTPException(403, "Verify your email before continuing.")
        return user
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Authentication is temporarily unavailable.") from exc


def load_profile(user: dict) -> dict:
    client = None
    try:
        client = create_task_client()
        rows = client.table("profiles").select(
            "id,name,email,phone_number,role,is_admin,skills,member_code,"
            "girlhacks_title,major,graduation_date,graduation_year,password_setup_complete"
        ).eq("id", user["id"]).execute().data
        if len(rows) != 1 or not rows[0].get("member_code"):
            raise HTTPException(403, "Your account is not linked to the approved board roster. Contact an administrator.")
        profile = rows[0]
        members = client.table("members").select("code,email,active,contact_consent").eq(
            "code", profile["member_code"]
        ).execute().data
        email = (user.get("email") or "").strip().lower()
        if (len(members) != 1 or not members[0].get("active")
                or not members[0].get("contact_consent") or not email
                or members[0].get("email") != email
                or (profile.get("email") or "").strip().lower() != email):
            raise HTTPException(403, "Board access is inactive or has not been approved.")
        return profile
    except (StorageUnavailable, APIError, httpx.HTTPError) as exc:
        raise HTTPException(503, "Profile storage is unavailable. Check the authentication migrations.") from exc
    finally:
        if client is not None:
            client.postgrest.session.close()


def get_principal(request: Request) -> Principal:
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip() or len(token) > 16384:
            raise HTTPException(401, "A valid Bearer token is required.")
        user = verify_token(token.strip(), Settings())
        return Principal(user["id"], load_profile(user))

    # Keep existing trusted server integrations, scoped to their existing keys.
    # A bad Bearer token never falls back to a shared secret or development bypass.
    settings = Settings()
    path = request.url.path
    header = "x-winnie-api-key"
    if path.startswith("/api/help-requests"):
        expected = settings.help_admin_api_key.get_secret_value()
    elif path.startswith("/api/planning/") and path.endswith("/review"):
        expected = settings.planning_review_api_key.get_secret_value()
        header = "x-winnie-planning-review-key"
    elif path.startswith("/api/auth"):
        expected = ""
    else:
        expected = settings.task_api_key.get_secret_value()
    supplied = request.headers.get(header, "")
    if expected and supplied and compare_digest(expected.encode(), supplied.encode()):
        return Principal("service", {"is_admin": True, "password_setup_complete": True}, True)
    raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})


def require_member(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if principal.profile.get("password_setup_complete") is not True:
        raise HTTPException(403, "Set your password before opening the dashboard.")
    return principal


def require_admin(principal: Annotated[Principal, Depends(require_member)]) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, "Administrator access is required.")
    return principal
