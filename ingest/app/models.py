"""Plain data types shared across modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

MeetingStatus = Literal["uploaded", "transcribing", "summarizing", "extracting_tasks", "done", "failed"]
MemberKind = Literal["person", "seat"]


@dataclass(frozen=True)
class Segment:
    idx: int
    start_ms: int | None
    end_ms: int | None
    speaker_label: str | None
    text: str


@dataclass(frozen=True)
class Member:
    id: int
    code: str
    kind: MemberKind
    name: str
    seat: str | None
    aliases: tuple[str, ...]
    active: bool


class ExtractedTask(BaseModel):
    """One action item as returned by the LLM. Validated before anything touches the DB."""

    title: str = Field(min_length=1)
    description: str = ""
    seat: str | None = None
    assignee: str | None = None
    rationale: str = ""
    deadline: str | None = None
    needs_review: bool = False


class ExtractionResult(BaseModel):
    items: list[ExtractedTask]
