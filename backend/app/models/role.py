# Role + RoleSeat.
# Roles: President, Vice President, Treasurer, Secretary, Event Coordinator (2),
#        Industry Partnership Chair (2), Community Outreach Chair, PR Chair (2), Technical Director.
# RoleSeat = numbered seat in a role ("Event Coordinator #2") held by one Member.
# Targets must distinguish "whole role" (every seat) from "one seat".

from attr import dataclass


@dataclass
class Role:
    id: int
    name: str  # e.g., "President", "Event Coordinator"
    total_seats: int  # total number of seats for this role

    def __post_init__(self):
        if not self.name:
            raise ValueError("Role name cannot be empty.")
        if self.total_seats < 1:
            raise ValueError("Role must have at least one seat.")

@dataclass
class RoleSeat:
    id: int
    role_id: int  # foreign key to Role
    seat_number: int  # e.g., 1 for "Event Coordinator #1", 2 for "Event Coordinator #2"
    member_id: int  # foreign key to Member

    def __post_init__(self):
        if self.seat_number < 1:
            raise ValueError("RoleSeat seat number must be at least 1.")
