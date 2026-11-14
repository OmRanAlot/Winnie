"""Domain objects for Winnie: who is on the board, what work exists, who gets told about it.

Most are plain dataclasses that validate themselves on creation and are not stored yet. The task
models (ExtractedTask, Task, TaskDependency) are Pydantic and project canonical UUID task rows
into the timeline shape; app/db/repository.py reads and writes them. Business logic lives in
services/.

Contents, in order:
    Member, Role, RoleSeat        the e-board people and their positions
    Skill                         tags used to suggest substitutes
    ExtractedTask                 an action item pulled out of a transcript (pre-storage)
    Task, TaskDependency          stored board work and "A waits on B" links (Supabase rows)
    Meeting                       a transcribed meeting and the tasks pulled out of it
    Notification, NotificationSubscription   who gets told what
    (EmailThread is planned, see the note at the bottom.)

Several roles have two seats (Event Coordinator, Industry Partnership Chair, PR Chair). A task or
notification can target one member, one seat ("PR Chair #2"), or a whole role (every seat).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

TaskStatus = Literal["todo", "in_progress", "done", "blocked"]
TASK_STATUSES: frozenset[str] = frozenset(get_args(TaskStatus))


class ExtractedTask(BaseModel):
    """One action item extracted from a meeting transcript, as the assignment step returns it
    (services/task_assignment.py) and as app/repository.insert_extracted_tasks stores it.

    Matches the LLM JSON: {"title", "description", "seat", "assignee", "rationale",
    "deadline", "needs_review"}. `deadline` is the phrase as spoken ("by Monday noon").
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    seat: str  # a roster seat key, or "Unassigned"
    assignee: str | None = None  # the member's name; None when unassigned
    rationale: str = ""
    deadline: str | None = None  # as spoken; parsed by app/core/deadlines.py
    needs_review: bool = False  # True when no seat could be chosen


class Task(BaseModel):
    """A timeline projection of a canonical UUID task record.

    `seat` and `assignee` are display text projected by app/db/repository.py.
    `assignee_id` groups labels for display; authorization uses verified member mappings.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    description: str | None = None
    seat_id: int | None = None
    assignee_id: str | None = None
    rationale: str | None = None
    deadline_raw: str | None = None
    deadline_at: datetime | None = None
    needs_review: bool = False
    status: TaskStatus = "todo"
    source_meeting_id: int | None = None
    raw_json: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    seat: str | None = None
    assignee: str | None = None
    meeting_held_at: datetime | None = None
    depends_on: tuple[str, ...] = ()


class TaskDependency(BaseModel):
    """Directed edge: task `task_id` waits on task `depends_on_id` (table task_dependencies).

    Core feature: when the task being waited on finishes or gets blocked, the owners of the
    dependents are notified. Longer cycles (A->B->A) are rejected by app/db/repository.py.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str
    depends_on_id: str

    @model_validator(mode="after")
    def not_self(self) -> "TaskDependency":
        if self.task_id == self.depends_on_id:
            raise ValueError("A task cannot depend on itself.")
        return self


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
