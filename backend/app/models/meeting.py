# Meeting — a recorded/transcribed e-board meeting, plus its TaskCandidates
# (extracted tasks awaiting confirmation before they become Tasks).

from typing import List, Optional


from dataclasses import dataclass, field


@dataclass
class Meeting:
    id: int
    date: str  # ISO format date string
    transcript: Optional[str] = None
    task_candidates: Optional[List[str]] = field(default_factory=list)

    def __post_init__(self):
        if not self.date:
            raise ValueError("Meeting date cannot be empty.")
