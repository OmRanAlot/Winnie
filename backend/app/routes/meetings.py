"""POST /api/meetings/ingest: upload a meeting's audio file; get back the transcript, a summary
and the extracted tasks (all saved to Supabase and visible on GET /api/tasks).

Multipart form: `file` (audio, up to 15 MB), optional `title`, optional `held_at` (ISO 8601; a
time without a zone is New York time; default now). Logic lives in services/meeting_ingest.py.
Needs GEMINI_API_KEY and the Supabase settings (see app/core/settings.py).
"""

import logging
from datetime import UTC, date, datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile
from google.genai import errors
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field, ValidationError

from app.core.auth import require_admin
from app.core.settings import Settings
from app.integrations.supabase import StorageUnavailable
from app.schemas.api import failure
from app.services import meeting_ingest
from app.services import tasks as task_service
from app.services.attendance import AttendanceStore
from app.services.task_assignment import EBOARD_FILE, get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def get_attendance_store():
    return AttendanceStore()


class MeetingInput(BaseModel):
    title: str = Field(min_length=1, max_length=200, pattern=r"\S")
    meeting_date: date


class AttendanceInput(BaseModel):
    attendees: list[str] = Field(max_length=200)


@router.get("")
def list_meetings(store: Annotated[AttendanceStore, Depends(get_attendance_store)]):
    try:
        return {"success": True, "data": store.list_meetings()}
    except (StorageUnavailable, APIError, httpx.HTTPError):
        return failure("Meeting storage is unavailable. Check the attendance migration.", 503)


@router.post("", dependencies=[Depends(require_admin)])
def create_meeting(body: MeetingInput, store: Annotated[AttendanceStore, Depends(get_attendance_store)]):
    try:
        # Attendance-only meetings have a date, not a supplied start time; use local noon.
        held_at = datetime.combine(body.meeting_date, time(12), ZoneInfo("America/New_York"))
        return {"success": True, "data": store.create(body.title.strip(), held_at)}
    except (StorageUnavailable, APIError, httpx.HTTPError):
        return failure("Could not create the meeting. Please try again.", 503)


@router.patch("/{meeting_id}/attendance", dependencies=[Depends(require_admin)])
def save_attendance(meeting_id: int, body: AttendanceInput,
                    store: Annotated[AttendanceStore, Depends(get_attendance_store)]):
    try:
        store.save(meeting_id, body.attendees)
        return {"success": True, "data": {"attendees": sorted(set(body.attendees))}}
    except APIError as exc:
        if exc.code in ("22023", "P0002"):
            return failure("Select valid board members." if exc.code == "22023" else "Meeting not found.",
                           422 if exc.code == "22023" else 404)
        return failure("Could not save attendance. Please try again.", 503)
    except (StorageUnavailable, httpx.HTTPError):
        return failure("Could not save attendance. Please try again.", 503)


@router.post("/ingest")
async def ingest_meeting(
    file: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_settings)],
    title: Annotated[str | None, Form()] = None,
    held_at: Annotated[datetime | None, Form()] = None,
):
    if not settings.gemini_api_key:
        return failure("Meeting ingest is not configured. Set GEMINI_API_KEY.", 503)
    mime_type = file.content_type or ""
    if meeting_ingest.audio_extension(mime_type) is None:
        return failure("Upload an audio file (webm, m4a, ogg, wav or mp3).", 415)
    audio = await file.read(meeting_ingest.MAX_AUDIO_BYTES + 1)
    if not audio:
        return failure("The audio file is empty.", 422)
    if len(audio) > meeting_ingest.MAX_AUDIO_BYTES:
        return failure("Audio exceeds the 15 MB limit.", 413)
    try:
        return await meeting_ingest.ingest_audio(audio, mime_type, title, held_at or datetime.now(UTC), settings)
    except (errors.APIError, httpx.HTTPError):
        logger.exception("Gemini request failed")
        return failure("Gemini could not be reached. Please try again.", 502)
    except (ValueError, ValidationError):  # unusable Gemini answer, or an unreadable roster
        logger.exception("Meeting ingest failed on an unusable answer or roster (%s)", EBOARD_FILE)
        return failure("Could not turn the audio into a transcript and tasks. Please try again.", 502)
    except task_service.STORAGE_ERRORS:
        logger.exception("Meeting ingest could not reach the task store")
        return failure("The task store is unavailable. Please try again.", 503)
    except OSError:
        logger.exception("Could not save the audio file or read the roster")
        return failure("Could not save the audio file.", 503)
