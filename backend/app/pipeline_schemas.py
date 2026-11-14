"""Validated contracts for the staged planner. All outputs remain proposals."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.planning_schemas import DraftContents, Role, Text
from app.task_schemas import SemesterCode, StakeholderCode

Category = Literal[
    "Tabling", "Professional Development", "Company Events", "Technical Workshop",
    "Destress", "Alumni Panel Session", "Unknown",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PipelineRequest(StrictModel):
    event_name: Text
    idea: str = Field(min_length=1, max_length=6000)
    event_date: date
    semester_code: SemesterCode
    category: Category | None = None


class Classification(StrictModel):
    category: Category
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1, max_length=2000)
    taxonomy_evidence_ids: list[Text] = Field(default_factory=list, max_length=20)


class HistoricalClassification(Classification):
    event_id: Text


class ClassifiedHistory(StrictModel):
    events: list[HistoricalClassification] = Field(max_length=200)


class Dependency(StrictModel):
    upstream_task_id: Text
    downstream_task_id: Text
    minimum_gap_days: int = Field(default=0, ge=0, le=365)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[Text] = Field(default_factory=list, max_length=20)
    basis: Literal["inferred", "explicit"] = "inferred"


class Dependencies(StrictModel):
    edges: list[Dependency] = Field(default_factory=list, max_length=300)


class ScheduleItem(StrictModel):
    task_id: Text
    due_date: date | None
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[Text] = Field(default_factory=list, max_length=20)
    # Estimates remain distinct from historical event-relative deadline buffers.
    estimated_effort_hours: float | None = Field(default=None, gt=0, le=1000)


class Schedule(StrictModel):
    items: list[ScheduleItem] = Field(min_length=1, max_length=80)
    warnings: list[str] = Field(default_factory=list, max_length=30)


class RosterMember(StrictModel):
    member_code: StakeholderCode
    display_name: Text
    roles: list[Role] = Field(min_length=1, max_length=9)
    aliases: list[Text] = Field(default_factory=list, max_length=30)
    active: bool = True
    open_task_count: int | None = Field(default=None, ge=0)


class SemesterRoster(StrictModel):
    semester_code: SemesterCode
    verified_by: Text
    members: list[RosterMember] = Field(max_length=100)


class RosterFile(StrictModel):
    rosters: list[SemesterRoster] = Field(max_length=30)


class Assignment(StrictModel):
    task_id: Text
    role: Role | None
    candidate_member_codes: list[StakeholderCode]
    proposed_member_code: StakeholderCode | None
    rationale: str


class PipelineDraft(StrictModel):
    status: Literal["draft"] = "draft"
    mode: Literal["mock", "deepagents"]
    request: PipelineRequest
    classification: Classification
    historical_classifications: list[HistoricalClassification]
    plan: DraftContents
    dependencies: Dependencies
    schedule: Schedule
    assignments: list[Assignment]
    handoffs: list[dict]
    timing_statistics: list[dict]
    historical_examples: list[dict]
    warnings: list[str]
    completed_stages: list[str]
