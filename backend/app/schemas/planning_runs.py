"""Durable planning-run and exact-draft review contracts; review never activates tasks."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Revision = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


class PlanningReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    expected_revision: Revision
    note: str = Field(default="", max_length=2000)
