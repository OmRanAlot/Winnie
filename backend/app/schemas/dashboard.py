"""Validated dashboard feedback and draft forms."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comments: str = Field(max_length=10000)


class TaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=6000)
    startDate: str = Field(default="", max_length=10)
    dueDate: str = Field(default="", max_length=10)
    time: str = Field(default="", pattern=r"^$|^([01][0-9]|2[0-3]):[0-5][0-9]$")
    summary: str = Field(default="", max_length=10000)
    priority: Literal["low", "normal", "high"] = "normal"
    ownerCode: str = Field(default="", pattern=r"^$|^[A-Z][A-Z0-9_-]{0,49}$")

    @model_validator(mode="after")
    def valid_dates(self):
        for value in (self.startDate, self.dueDate):
            if value:
                date.fromisoformat(value)
        if self.startDate and self.dueDate and self.startDate > self.dueDate:
            raise ValueError("Start date must be on or before due date.")
        return self
