"""Resolve admin-verified sender identities and complete tracker assignee cells."""

import unicodedata

from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable, create_task_client


def normalize_sender(sender_id: str) -> str:
    sender_id = sender_id.strip()
    return sender_id.casefold() if "@" in sender_id else sender_id


def normalize_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class AliasConflict(ValueError):
    pass


def assignment_members(assignee_text: str, aliases: list[dict]) -> set[str] | None:
    """Match whole verified aliases; unresolved text means no authorized assignment.

    Do not split full names on spaces, match arbitrary substrings, or assume a role.
    Every participant in a shared assignment must be recognized before returning it.
    """
    lookup = {}
    for entry in aliases:
        alias = normalize_alias(entry["alias"])
        if not alias:
            raise AliasConflict("Empty member alias.")
        if alias in lookup and lookup[alias] != entry["member_code"]:
            raise AliasConflict("Member aliases are ambiguous.")
        lookup[alias] = entry["member_code"]
    text = normalize_alias(assignee_text)
    separators = " ,;&/|"

    def advance(position, had_member):
        while position < len(text) and text[position] in separators:
            position += 1
        if had_member and text.startswith("and ", position):
            position += 4
        return position

    # Each position holds one verified interpretation, or None if interpretations
    # disagree. Never guess that a long alias is one person rather than two names.
    states = {advance(0, False): frozenset()}
    for position in range(len(text)):
        if position not in states:
            continue
        current = states[position]
        for alias, member_code in lookup.items():
            if not text.startswith(alias, position):
                continue
            end = position + len(alias)
            if end < len(text) and text[end] not in separators:
                continue
            end = advance(end, True)
            candidate = None if current is None else current | {member_code}
            if end not in states:
                states[end] = candidate
            elif states[end] != candidate:
                states[end] = None
    result = states.get(len(text))
    return set(result) if result is not None else None


class MemberStore:
    def __init__(self, client_factory=create_task_client):
        self.client_factory = client_factory

    def _execute(self, table_name, operation):
        client = None
        try:
            client = self.client_factory()
            return operation(client.table(table_name)).execute()
        except (HTTPError, APIError) as exc:
            raise StorageUnavailable("Member storage is unavailable.") from exc
        finally:
            if client is not None:
                client.postgrest.session.close()

    def resolve(self, platform: str, sender_id: str):
        identity = self._execute("member_identities", lambda table: table.select(
            "member_code"
        ).eq("platform", platform).eq("sender_id", normalize_sender(sender_id))).data
        if len(identity) != 1:
            return None
        members = self._execute("members", lambda table: table.select(
            "code,display_name,active"
        ).eq("code", identity[0]["member_code"]).eq("active", True)).data
        return members[0] if len(members) == 1 else None

    def aliases(self, semester_code: str):
        aliases, offset = [], 0
        while True:
            page = self._execute("member_aliases", lambda table, offset=offset: table.select(
                "alias,member_code"
            ).eq("semester_code", semester_code).order("alias").range(offset, offset + 499)).data
            aliases.extend(page)
            if len(page) < 500:
                return aliases
            offset += 500
