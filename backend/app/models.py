"""Domain objects for Winnie: who is on the board, what work exists, who gets told about it.

These are plain dataclasses that validate themselves on creation. They are NOT database tables
and hold no business logic; services/ does the work, and database.py (planned, see
app/__init__.py) will handle persistence.

Contents, in order:
    Member, Role, RoleSeat        the e-board people and their positions
    Skill                         tags used to suggest substitutes
    Task, TaskDependency          board work and "A waits on B" links
    Meeting                       a transcribed meeting and the tasks pulled out of it
    Notification, NotificationSubscription   who gets told what
    (EmailThread is planned, see the note at the bottom.)

Several roles have two seats (Event Coordinator, Industry Partnership Chair, PR Chair). A task or
notification can target one member, one seat ("PR Chair #2"), or a whole role (every seat).
"""

from dataclasses import dataclass, field

# --- People and roles -------------------------------------------------------------------------


@dataclass
class Member:
    """One e-board person. Holds one or more RoleSeats."""

    id: int
    name: str
    email: str
    imessage_handle: str | None = None
    discord_id: str | None = None
    skills: list[str] = field(default_factory=list)
    availability_notes: str | None = None
    active: bool = True

    def __post_init__(self):
        if not self.name:
            raise ValueError("Member name cannot be empty.")
        if not self.email:
            raise ValueError("Member email cannot be empty.")


@dataclass
class Role:
    """A board position. Roles: President, Vice President, Treasurer, Secretary,
    Event Coordinator (2), Industry Partnership Chair (2), Community Outreach Chair,
    PR Chair (2), Technical Director."""

    id: int
    name: str  # e.g. "President", "Event Coordinator"
    total_seats: int

    def __post_init__(self):
        if not self.name:
            raise ValueError("Role name cannot be empty.")
        if self.total_seats < 1:
            raise ValueError("Role must have at least one seat.")


@dataclass
class RoleSeat:
    """One numbered seat in a role ("Event Coordinator #2"), held by one Member."""

    id: int
    role_id: int
    seat_number: int  # 1-based
    member_id: int

    def __post_init__(self):
        if self.seat_number < 1:
            raise ValueError("RoleSeat seat number must be at least 1.")


@dataclass
class Skill:
    """A tag used to suggest substitutes (e.g. the Secretary covering a PR task).
    Attached to Members, and to Tasks as required skills."""

    id: int
    name: str  # e.g. "PR", "Finance", "Event Planning"

    def __post_init__(self):
        if not self.name:
            raise ValueError("Skill name cannot be empty.")


# --- Work -------------------------------------------------------------------------------------

TASK_STATUSES = {"todo", "in_progress", "blocked", "done"}
OWNER_TARGETS = {"member", "role_seat", "whole_role"}


@dataclass
class Task:
    """A unit of board work. The single source of truth that replaces the spreadsheet, Docs and Discord."""

    id: int
    title: str
    description: str
    status: str  # one of TASK_STATUSES
    owner_target: str  # one of OWNER_TARGETS
    due_date: str | None = None  # ISO 8601 date
    event_tag: str | None = None  # e.g. "GirlHacks"
    source: str | None = None  # "meeting" | "sheet" | "doc" | "discord" | "manual"
    source_reference: str | None = None
    required_skills: list[str] = field(default_factory=list)
    ai_eligible: bool = False
    created_at: str | None = None  # ISO 8601 datetime
    updated_at: str | None = None  # ISO 8601 datetime

    def __post_init__(self):
        if not self.title:
            raise ValueError("Task title cannot be empty.")
        if self.status not in TASK_STATUSES:
            raise ValueError(f"Invalid task status: {self.status}")
        if self.owner_target not in OWNER_TARGETS:
            raise ValueError(f"Invalid owner target: {self.owner_target}")


@dataclass
class TaskDependency:
    """Directed edge: task `task_id` depends on task `depends_on_task_id`.

    Core feature: when the task being waited on finishes or gets blocked, the owners of the
    dependents are notified. Longer cycles (A->B->A) must be rejected by services/tasks.py.
    """

    task_id: int
    depends_on_task_id: int

    def __post_init__(self):
        if self.task_id == self.depends_on_task_id:
            raise ValueError("A task cannot depend on itself.")


@dataclass
class Meeting:
    """A recorded/transcribed e-board meeting, plus the task candidates extracted from it
    (candidates wait for human confirmation before they become Tasks)."""

    id: int
    date: str  # ISO 8601 date
    transcript: str | None = None
    task_candidates: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.date:
            raise ValueError("Meeting date cannot be empty.")


# --- Notifications ----------------------------------------------------------------------------

# Notification kinds: task_done, due_soon, overdue, blocked, reassignment, email_reminder,
# question_routed. Channels: imessage, discord, web.


@dataclass
class Notification:
    """One message to one recipient, e.g. "sponsorship email sent" to the President."""

    recipient: str  # email or user ID
    kind: str
    payload: dict  # extra data for the message
    channel: str
    sent_time: str | None = None  # ISO 8601 datetime
    asked_time: str | None = None  # ISO 8601 datetime

    def __post_init__(self):
        if not self.recipient:
            raise ValueError("Notification recipient cannot be empty.")
        if not self.kind:
            raise ValueError("Notification kind cannot be empty.")
        if not self.channel:
            raise ValueError("Notification channel cannot be empty.")


@dataclass
class NotificationSubscription:
    """Who cares about what, e.g. sponsorship tasks -> President, VP, Industry Partnership Chair #2."""

    subscriber: str  # email or user ID
    kind: str  # a notification kind, see above

    def __post_init__(self):
        if not self.subscriber:
            raise ValueError("NotificationSubscription subscriber cannot be empty.")
        if not self.kind:
            raise ValueError("NotificationSubscription kind cannot be empty.")


# --- Planned ----------------------------------------------------------------------------------
# EmailThread: a thread in the shared inbox. Planned fields: external id, subject, sender,
# received_at, assigned member/role, routing confidence, responded_at, reminder count.
