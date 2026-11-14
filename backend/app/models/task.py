# Task — a unit of board work.
# Planned fields: id, title, description, status (todo / in_progress / blocked / done),
#   owner target (member | role seat | whole role), due_date, event tag,
#   source (meeting | sheet | doc | discord | manual) + source reference,
#   required skills, ai_eligible flag, timestamps.


from dataclasses import dataclass
from attr import dataclass, field
from typing import List, Optional
from pyparsing import Optional


@dataclass
class Task:
    id: int
    title: str
    description: str
    status: str  # e.g., "todo", "in_progress", "blocked", "done", "behind schedule"
    owner_target: str  # e.g., "member", "role_seat", "whole_role"
    due_date: Optional[str] = None  # ISO 8601 date string
    event_tag: Optional[str] = None
    source: Optional[str] = None  # e.g., "meeting", "sheet", "doc", "discord", "manual"
    source_reference: Optional[str] = None
    required_skills: Optional[List[str]] = field(default_factory=list)
    ai_eligible: bool = False
    created_at: Optional[str] = None  # ISO 8601 datetime string
    updated_at: Optional[str] = None  # ISO 8601 datetime string

    def __post_init__(self):
        if not self.title:
            raise ValueError("Task title cannot be empty.")
        if self.status not in {"todo", "in_progress", "blocked", "done"}:
            raise ValueError(f"Invalid task status: {self.status}")
        if self.owner_target not in {"member", "role_seat", "whole_role"}:
            raise ValueError(f"Invalid owner target: {self.owner_target}")

