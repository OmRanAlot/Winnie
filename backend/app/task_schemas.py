"""Task API validation, used by routes/tasks.py and services/tasks.py."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MonthCode = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]
StakeholderCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9_-]{0,49}$")
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
TaskStatus = Literal["todo", "in_progress", "blocked", "done"]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title
    month_code: MonthCode
    description: str = Field(default="", max_length=10000)
    status: TaskStatus = "todo"
    stakeholder_codes: list[StakeholderCode] = Field(default_factory=list, max_length=50)
    owner_code: StakeholderCode | None = None
    due_date: date | None = None
    event_tag: str | None = Field(default=None, max_length=100)
    tags: list[Annotated[str, StringConstraints(min_length=1, max_length=50)]] = Field(
        default_factory=list, max_length=50
    )
    source: Literal["manual", "meeting", "sheet", "doc", "discord"] = "manual"
    source_reference: str | None = Field(default=None, max_length=2000)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None
    stakeholder_codes: list[StakeholderCode] | None = Field(default=None, max_length=50)
    owner_code: StakeholderCode | None = None
    due_date: date | None = None
    event_tag: str | None = Field(default=None, max_length=100)
    tags: list[Annotated[str, StringConstraints(min_length=1, max_length=50)]] | None = Field(
        default=None, max_length=50
    )
    source_reference: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update.")
        for name in ("title", "description", "status", "stakeholder_codes", "tags"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        return self


class StoredTask(TaskCreate):
    id: UUID
    task_code: str
    created_at: datetime
    updated_at: datetime
