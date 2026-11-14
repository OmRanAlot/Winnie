# Member — one e-board person.
# Planned fields: id, name, email, iMessage handle, discord_id, skills, availability notes, active.
# A member holds one or more RoleSeats.

from ast import List
from dataclasses import dataclass

from attrs import field
from pyparsing import Optional


@dataclass
class Member:
    id: int
    name: str
    email: str
    imessage_handle: Optional[str] = None
    discord_id: Optional[str] = None
    skills: Optional[List[str]] = field(default_factory=list)
    availability_notes: Optional[str] = None
    active: bool = True

    def __post_init__(self):
        if not self.name:
            raise ValueError("Member name cannot be empty.")
        if not self.email:
            raise ValueError("Member email cannot be empty.")
