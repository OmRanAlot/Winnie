"""Draft planning contracts; these are deliberately separate from live tasks."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
EventType = Literal["WiCS", "Tabling", "Company", "Club Collab"]
Role = Literal[
    "President", "Vice President", "Treasurer", "Secretary", "Event Coordinator",
    "Industry Partnership Chair", "Community Outreach Chair", "PR Chair", "Technical Director",
]


class PlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: Text
    idea: str = Field(min_length=1, max_length=6000)
    event_type: EventType
    event_date: date
    event_format: Literal["gbm", "technical_workshop", "hackathon", "other"] = "other"


class ProposedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Text
    title: Text
    suggested_role: Role | None = None
    due_date: date | None = None
    phase: Literal["before", "during", "after"] = "before"
    dependency_ids: list[Text] = Field(default_factory=list, max_length=50)
    evidence_ids: list[Text] = Field(default_factory=list, max_length=30)
    rationale: str = Field(min_length=1, max_length=2000)


class DraftContents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[ProposedTask] = Field(min_length=1, max_length=80)
    questions: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_graph(self):
        tasks = {task.id: task for task in self.tasks}
        if len(tasks) != len(self.tasks):
            raise ValueError("Task IDs must be unique.")
        visited, visiting = set(), set()

        def visit(task_id):
            if task_id in visiting:
                raise ValueError("Dependency cycle detected.")
            if task_id in visited:
                return
            visiting.add(task_id)
            task = tasks[task_id]
            for dep_id in task.dependency_ids:
                if dep_id not in tasks:
                    raise ValueError("Unknown dependency ID.")
                dependency = tasks[dep_id]
                if task.due_date and dependency.due_date and dependency.due_date > task.due_date:
                    raise ValueError("Dependency is due after its dependent task.")
                visit(dep_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in tasks:
            visit(task_id)
        return self


class PlanningDraft(DraftContents):
    status: Literal["draft"] = "draft"
    mode: Literal["mock", "deepagents"]
    request: PlanningRequest
    warnings: list[str]
    historical_examples: list[dict]
