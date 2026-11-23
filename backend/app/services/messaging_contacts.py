"""Admin board-phone pool: normalize roster numbers, link iMessage identities, enroll Photon users.

Photon Stable create-user is idempotent on phoneNumber (shared) or (phoneNumber, assignedPhoneNumber)
(dedicated). Dedicated enrollment can attach every roster handle to every project line so outbound
sends can rotate across lines. Shared mode lets Photon allocate the line per handle.
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx

from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable, create_task_client

logger = logging.getLogger(__name__)
SPECTRUM = "https://spectrum.photon.codes"


class MessagingContactsError(Exception):
    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


def to_e164(raw: str | None) -> str | None:
    """Normalize a US-leaning roster phone to E.164, or return None if unusable."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


def split_name(display_name: str) -> tuple[str | None, str | None]:
    """Split a display name into first/last fields for Photon enrollment."""
    parts = [part for part in display_name.strip().split() if part]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0][:100], None
    return parts[0][:100], " ".join(parts[1:])[:100]


class MessagingContactStore:
    def __init__(self, client_factory: Callable[[], Any] = create_task_client):
        self.client_factory = client_factory

    def _client(self):
        return self.client_factory()

    def list_identities(self) -> list[dict]:
        """Return every imessage identity row (paginated)."""
        client = None
        try:
            client = self._client()
            rows, offset = [], 0
            while True:
                page = (
                    client.table("member_identities")
                    .select("platform,sender_id,member_code")
                    .eq("platform", "imessage")
                    .order("sender_id")
                    .range(offset, offset + 499)
                    .execute()
                    .data
                )
                rows.extend(page)
                if len(page) < 500:
                    return rows
                offset += 500
        except Exception as exc:
            raise StorageUnavailable("Messaging identity storage is unavailable.") from exc
        finally:
            if client is not None:
                client.postgrest.session.close()

    def ensure_identity(self, member_code: str, sender_id: str) -> dict:
        """Link sender_id to member_code, or return the existing matching row."""
        client = None
        try:
            client = self._client()
            existing = (
                client.table("member_identities")
                .select("platform,sender_id,member_code")
                .eq("platform", "imessage")
                .eq("sender_id", sender_id)
                .execute()
                .data
            )
            if existing:
                row = existing[0]
                if row["member_code"] != member_code:
                    raise MessagingContactsError(
                        "That phone number is already linked to another member.", status=409
                    )
                return row
            inserted = (
                client.table("member_identities")
                .insert({"platform": "imessage", "sender_id": sender_id, "member_code": member_code})
                .execute()
                .data
            )
            return inserted[0]
        except MessagingContactsError:
            raise
        except Exception as exc:
            raise StorageUnavailable("Could not save the messaging identity.") from exc
        finally:
            if client is not None:
                client.postgrest.session.close()


def board_phone_rows(roster: list[dict], identities: list[dict]) -> list[dict]:
    """One row per active consented phone, with identity and E.164 status."""
    by_member: dict[str, list[dict]] = {}
    for row in identities:
        by_member.setdefault(row["member_code"], []).append(row)

    contacts = []
    for member in roster:
        if not member.get("active") or not member.get("contact_consent"):
            continue
        handle = to_e164(member.get("phone_number"))
        if not handle:
            if member.get("phone_number"):
                contacts.append({
                    "member_code": member["code"],
                    "display_name": member["display_name"],
                    "board_role": member.get("board_role"),
                    "phone_number": member.get("phone_number"),
                    "handle": None,
                    "identity_linked": False,
                    "ready": False,
                    "issue": "Phone number could not be normalized to E.164.",
                })
            continue
        linked = any(
            to_e164(identity["sender_id"]) == handle or identity["sender_id"] == handle
            for identity in by_member.get(member["code"], [])
        )
        contacts.append({
            "member_code": member["code"],
            "display_name": member["display_name"],
            "board_role": member.get("board_role"),
            "phone_number": member.get("phone_number"),
            "handle": handle,
            "identity_linked": linked,
            "ready": linked,
            "issue": None if linked else "Not linked for personal iMessage commands yet.",
        })
    contacts.sort(key=lambda row: (row["display_name"].lower(), row["member_code"]))
    return contacts


def photon_auth_header(settings: Settings) -> str:
    project = settings.photon_project_id
    secret = settings.photon_project_secret.get_secret_value() if settings.photon_project_secret else ""
    if not project or not secret:
        raise MessagingContactsError("Photon project credentials are not configured.", status=503)
    token = base64.b64encode(f"{project}:{secret}".encode()).decode()
    return f"Basic {token}"


def photon_line_inventory(settings: Settings, client: httpx.Client | None = None) -> dict[str, Any]:
    """Shared vs dedicated mode and dedicated line numbers from the tokens endpoint."""
    own = client is None
    session = client or httpx.Client(timeout=20.0)
    try:
        project = settings.photon_project_id
        response = session.post(
            f"{SPECTRUM}/projects/{project}/imessage/tokens",
            headers={"Authorization": photon_auth_header(settings)},
        )
        if response.status_code >= 400:
            raise MessagingContactsError("Photon did not return line inventory.", status=502)
        payload = response.json().get("data") or {}
        if payload.get("type") == "shared":
            return {"mode": "shared", "lines": []}
        if payload.get("type") == "dedicated":
            numbers = sorted({value for value in (payload.get("numbers") or {}).values() if value})
            return {"mode": "dedicated", "lines": numbers}
        raise MessagingContactsError("Unknown Photon line mode.", status=502)
    finally:
        if own:
            session.close()


def enroll_photon_handle(
    settings: Settings,
    handle: str,
    *,
    first_name: str | None,
    last_name: str | None,
    email: str | None,
    assigned_phone: str | None,
    client: httpx.Client | None = None,
) -> dict:
    own = client is None
    session = client or httpx.Client(timeout=20.0)
    try:
        body: dict[str, Any] = {"phoneNumber": handle}
        if assigned_phone:
            body["type"] = "dedicated"
            body["assignedPhoneNumber"] = assigned_phone
        else:
            body["type"] = "shared"
        if first_name:
            body["firstName"] = first_name
        if last_name:
            body["lastName"] = last_name
        if email:
            body["email"] = email
        response = session.post(
            f"{SPECTRUM}/projects/{settings.photon_project_id}/users/",
            headers={
                "Authorization": photon_auth_header(settings),
                "Content-Type": "application/json",
            },
            json=body,
        )
        if response.status_code >= 400:
            logger.warning("Photon enrollment failed with HTTP %d.", response.status_code)
            raise MessagingContactsError(
                "Photon rejected enrollment for one board phone number.", status=502
            )
        data = response.json().get("data") or response.json()
        return data if isinstance(data, dict) else {"raw": data}
    finally:
        if own:
            session.close()


def sync_board_phones(
    roster: list[dict],
    store: MessagingContactStore,
    settings: Settings,
    *,
    enroll_photon: bool = True,
    rotate_across_lines: bool = True,
) -> dict:
    """Link identities for every usable board phone and optionally enroll them in Photon.

    When the project is on dedicated lines and rotate_across_lines is true, each handle is
    enrolled against every project line so outbound traffic can use any line.
    """
    identities = store.list_identities()
    contacts = board_phone_rows(roster, identities)
    results = []
    inventory: dict[str, Any] = {"mode": None, "lines": []}
    if enroll_photon:
        inventory = photon_line_inventory(settings)

    photon_client: httpx.Client | None = None
    try:
        if enroll_photon:
            photon_client = httpx.Client(timeout=20.0)
        for contact in contacts:
            entry = {**contact, "photon": None, "identity": None, "errors": []}
            handle = contact.get("handle")
            if not handle:
                entry["errors"].append(contact.get("issue") or "Missing phone.")
                results.append(entry)
                continue
            try:
                identity = store.ensure_identity(contact["member_code"], handle)
                entry["identity"] = identity
                entry["identity_linked"] = True
                entry["ready"] = True
                entry["issue"] = None
            except (MessagingContactsError, StorageUnavailable) as exc:
                entry["errors"].append(str(exc))
                results.append(entry)
                continue

            if enroll_photon:
                first, last = split_name(contact["display_name"])
                member = next((row for row in roster if row["code"] == contact["member_code"]), {})
                email = member.get("email")
                try:
                    if inventory["mode"] == "dedicated" and inventory["lines"] and rotate_across_lines:
                        enrolled_assignments = [
                            enroll_photon_handle(
                                settings, handle, first_name=first, last_name=last, email=email,
                                assigned_phone=line, client=photon_client,
                            )
                            for line in inventory["lines"]
                        ]
                        entry["photon"] = {
                            "mode": "dedicated",
                            "assignments": enrolled_assignments,
                            "lines": inventory["lines"],
                        }
                    else:
                        enrolled_user = enroll_photon_handle(
                            settings, handle, first_name=first, last_name=last, email=email,
                            assigned_phone=None, client=photon_client,
                        )
                        entry["photon"] = {
                            "mode": inventory["mode"] or "shared",
                            "user": enrolled_user,
                        }
                except MessagingContactsError as exc:
                    entry["errors"].append(str(exc))
                except (httpx.HTTPError, ValueError):
                    entry["errors"].append("Photon enrollment could not be confirmed.")
            results.append(entry)
    finally:
        if photon_client is not None:
            photon_client.close()

    ready = sum(1 for row in results if row.get("ready") and not row.get("errors"))
    return {
        "mode": inventory.get("mode"),
        "lines": inventory.get("lines") or [],
        "total": len(results),
        "ready": ready,
        "contacts": results,
    }
