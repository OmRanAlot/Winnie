"""Shared event proposals; drafts remain separate from activated task records."""
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.planning import DraftContents, ProposedTask, Text
from app.schemas.tasks import StakeholderCode


class EventPlanTask(ProposedTask):
    owner_code: StakeholderCode | None = None
    description: str = Field(default="", max_length=10000)
    due_time: time | None = None


class EventPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_name: Text
    description: str = Field(default="", max_length=6000)
    event_date: date
    event_time: time | None = None
    plan_text: str = Field(default="", max_length=20000)
    tasks: list[EventPlanTask] = Field(default_factory=list, max_length=80)
    questions: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=60)
    plan_mode: Literal["mock", "deepagents"] | None = None

    @model_validator(mode="after")
    def valid_plan(self):
        if not self.plan_text.strip() and not self.tasks:
            raise ValueError("Add an outline or structured tasks.")
        if self.tasks:
            # Reuse graph validation, including duplicate IDs, unknown edges and cycles.
            DraftContents(tasks=[ProposedTask.model_validate(t.model_dump(exclude={
                "owner_code", "description", "due_time",
            })) for t in self.tasks])
        for task in self.tasks:
            if task.due_date and (
                (task.phase == "before" and task.due_date > self.event_date)
                or (task.phase == "during" and task.due_date != self.event_date)
                or (task.phase == "after" and task.due_date < self.event_date)
            ):
                raise ValueError("Task date does not match its event phase.")
        return self


class EventPlanUpdate(EventPlanInput):
    expected_revision: int = Field(ge=1)


class EventPlanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=10000)
