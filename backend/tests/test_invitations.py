"""Invitation preview rejects unconsented contacts and never invokes email sending."""

from types import SimpleNamespace

import pytest

from app.cli.invite_member import prepare_invitation


class PreviewClient:
    def __init__(self, members):
        self.members = members
        self.table_name = None

    def table(self, name): self.table_name = name; return self
    def select(self, *args): return self
    def eq(self, *args): return self
    def limit(self, *args): return self
    def execute(self):
        return SimpleNamespace(data=self.members if self.table_name == "members" else [])


def test_invitation_uses_roster_name_only_and_never_assigns_privileges():
    client = PreviewClient([{"display_name": "Alice", "active": True, "contact_consent": True}])
    result = prepare_invitation(client, " ALICE@example.com ", "http://localhost:5173/auth/set-password")
    assert result == {"email": "alice@example.com", "options": {
        "redirect_to": "http://localhost:5173/auth/set-password", "data": {"name": "Alice"},
    }}


@pytest.mark.parametrize("members", [[], [{"active": False, "contact_consent": True}],
                                    [{"active": True, "contact_consent": False}]])
def test_unapproved_contacts_cannot_be_invited(members):
    with pytest.raises(ValueError, match="active, consenting"):
        prepare_invitation(PreviewClient(members), "alice@example.com", "https://example.com/auth/set-password")


@pytest.mark.parametrize("url", ["http://example.com/auth/set-password", "javascript:alert(1)",
                                  "https://example.com/other", "https://user:pass@example.com/auth/set-password"])
def test_unsafe_callback_is_rejected(url):
    with pytest.raises(ValueError):
        prepare_invitation(PreviewClient([]), "alice@example.com", url)
