"""Validation for the administrator's roster forms."""

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StrictBool, StringConstraints, field_validator

MemberName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Role = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]


class RosterContacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_role: Role | None = None
    email: Email | None = None
    phone_number: Phone | None = None
    contact_consent: StrictBool = False

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if not value:
            return None
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value.lower()

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if not value:
            return None
        digits = re.sub(r"[^0-9]", "", value)
        if not 7 <= len(digits) <= 15 or not re.fullmatch(r"\+?[0-9(). -]+", value):
            raise ValueError("Enter a phone number with 7 to 15 digits.")
        return value


class RosterCreate(RosterContacts):
    display_name: MemberName


class RosterUpdate(RosterContacts):
    display_name: MemberName | None = None
    active: StrictBool = True

    @field_validator("display_name")
    @classmethod
    def require_name_when_supplied(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Enter a name.")
        return value
