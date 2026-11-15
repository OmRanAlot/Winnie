"""Server-configured Google tracker sources and reviewed sync requests."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.tasks import MonthCode, SemesterCode, SourceId


class SheetSource(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    spreadsheet_id: SourceId
    semester_code: SemesterCode
    tab_id: int | None = Field(default=None, ge=0)
    tab_name: str | None = Field(default=None, min_length=1, max_length=200)
    project_name: str | None = Field(default=None, max_length=200)
    initial_month: MonthCode | None = None
    auto_apply: bool = False

    @model_validator(mode="after")
    def tab_selector(self):
        if (self.tab_id is None) == (self.tab_name is None):
            raise ValueError("Configure exactly one of tab_id or tab_name.")
        return self


class SyncRequest(BaseModel):
    resolutions: dict[str, Literal["sheet", "winnie"]] = Field(default_factory=dict, max_length=5000)
    expected_plan: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
