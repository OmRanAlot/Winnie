"""Task API validation, used by routes/tasks.py and services/tasks.py."""

from datetime import date, datetime, time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MonthCode = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
StakeholderCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9_-]{0,49}$")
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TaskStatus = Literal["todo", "in_progress", "blocked", "done"]
TaskPriority = Literal["low", "normal", "high"]
SemesterCode = Annotated[
    str, StringConstraints(pattern=r"^(spring|summer|fall|winter)-[0-9]{4}$")
]
SourceId = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,199}$")
]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    month_code: MonthCode
    description: str = Field(default="", max_length=10000)
    notes: str = Field(default="", max_length=10000)
    status: TaskStatus = "todo"
    stakeholder_codes: list[StakeholderCode] = Field(default_factory=list, max_length=50)
    owner_code: StakeholderCode | None = None
    due_date: date | None = None
    start_date: date | None = None
    due_time: time | None = None
    event_tag: str | None = Field(default=None, max_length=100)
    tags: list[Annotated[str, StringConstraints(min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=50
    )
    source: Literal["manual", "meeting", "sheet", "doc", "discord"] = "manual"
    source_reference: str | None = Field(default=None, max_length=2000)
    semester_code: SemesterCode | None = None
    project_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    priority: TaskPriority = "normal"
    # Preserve the original cells until a member mapping/date interpretation is confirmed.
    assignee_text: str = Field(default="", max_length=2000)
    deadline_text: str = Field(default="", max_length=200)
    source_spreadsheet_id: SourceId | None = None
    source_task_id: SourceId | None = None
    source_tab_id: SourceId | None = None
    source_tab_name: str | None = Field(default=None, max_length=200)
    snapshot_month: MonthCode | None = None

    @model_validator(mode="after")
    def validate_source_identity(self):
        if self.start_date and self.due_date and self.start_date > self.due_date:
            raise ValueError("Start date must be on or before due date.")
        if self.source_task_id is not None and self.source_spreadsheet_id is None:
            raise ValueError("A source task ID requires a source spreadsheet ID.")
        return self


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: str | None = Field(default=None, max_length=10000)
    notes: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None
    stakeholder_codes: list[StakeholderCode] | None = Field(default=None, max_length=50)
    owner_code: StakeholderCode | None = None
    due_date: date | None = None
    start_date: date | None = None
    due_time: time | None = None
    event_tag: str | None = Field(default=None, max_length=100)
    tags: list[Annotated[str, StringConstraints(min_length=1, max_length=50)]] | None = Field(
        default=None, max_length=50
    )
    source_reference: str | None = Field(default=None, max_length=2000)
    project_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    priority: TaskPriority | None = None
    assignee_text: str | None = Field(default=None, max_length=2000)
    deadline_text: str | None = Field(default=None, max_length=200)
    source_tab_id: SourceId | None = None
    source_tab_name: str | None = Field(default=None, max_length=200)
    snapshot_month: MonthCode | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        for name in (
            "title", "description", "notes", "status", "stakeholder_codes", "tags",
            "priority", "assignee_text", "deadline_text",
        ):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        if self.start_date and self.due_date and self.start_date > self.due_date:
            raise ValueError("Start date must be on or before due date.")
        return self


class StoredTask(TaskCreate):
    completed_at: datetime | None = None
    original_assignee_code: StakeholderCode | None = None
    id: UUID
    task_code: str
    created_at: datetime
    updated_at: datetime
