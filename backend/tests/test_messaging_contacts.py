"""Board phone normalization and contact-row assembly for iMessage enrollment."""

import pytest
from pydantic import SecretStr

from app.core.settings import Settings
from app.services.messaging_contacts import (
    MessagingContactsError,
    board_phone_rows,
    photon_auth_header,
    sync_board_phones,
    to_e164,
)


def test_to_e164_accepts_common_us_formats():
    assert to_e164("(202) 555-0123") == "+12025550123"
    assert to_e164("2025550123") == "+12025550123"
    assert to_e164("+1 202 555 0123") == "+12025550123"
    assert to_e164("+442071838750") == "+442071838750"
    assert to_e164("not-a-phone") is None
    assert to_e164("") is None


def test_board_phone_rows_lists_every_usable_consented_number():
    roster = [
        {
            "code": "A", "display_name": "Avery", "board_role": "President",
            "phone_number": "(202) 555-0100", "contact_consent": True, "active": True,
        },
        {
            "code": "B", "display_name": "Blake", "board_role": "Treasurer",
            "phone_number": "+12025550101", "contact_consent": True, "active": True,
        },
        {
            "code": "C", "display_name": "Casey", "board_role": "Secretary",
            "phone_number": "(202) 555-0102", "contact_consent": False, "active": True,
        },
        {
            "code": "D", "display_name": "Drew", "board_role": "PR Chair",
            "phone_number": "bad", "contact_consent": True, "active": True,
        },
    ]
    identities = [
        {"platform": "imessage", "sender_id": "+12025550100", "member_code": "A"},
    ]
    rows = board_phone_rows(roster, identities)
    assert [row["member_code"] for row in rows] == ["A", "B", "D"]
    assert rows[0]["handle"] == "+12025550100"
    assert rows[0]["ready"] is True
    assert rows[1]["handle"] == "+12025550101"
    assert rows[1]["ready"] is False
    assert rows[2]["handle"] is None
    assert "E.164" in rows[2]["issue"]


def test_photon_auth_header_raises_when_credentials_missing():
    settings = Settings(photon_project_id="", photon_project_secret=SecretStr(""))
    with pytest.raises(MessagingContactsError, match="Photon project credentials"):
        photon_auth_header(settings)


class _Store:
    def __init__(self):
        self.identities = []
        self.ensured = []

    def list_identities(self):
        return list(self.identities)

    def ensure_identity(self, member_code, sender_id):
        row = {"platform": "imessage", "sender_id": sender_id, "member_code": member_code}
        self.ensured.append(row)
        self.identities.append(row)
        return row


def test_sync_board_phones_skips_photon_when_disabled():
    roster = [{
        "code": "A", "display_name": "Avery", "board_role": "President",
        "phone_number": "(202) 555-0100", "contact_consent": True, "active": True, "email": None,
    }]
    store = _Store()
    settings = Settings(photon_project_id="", photon_project_secret=SecretStr(""))
    result = sync_board_phones(roster, store, settings, enroll_photon=False)
    assert result["mode"] is None
    assert result["ready"] == 1
    assert store.ensured[0]["sender_id"] == "+12025550100"
    assert result["contacts"][0]["photon"] is None
