"""Meeting audio -> transcript + summary + tasks. Called by routes/meetings.py.

Steps (one Gemini call for the first two, the existing task extraction for the third):
    1. Save the audio file to data/recordings/ (gitignored), named by its SHA-256, so uploading
       the same file twice finds the same meeting instead of creating a second one.
    2. Gemini listens to the audio and returns the transcript and a short summary.
    3. The transcript goes through the existing task extraction (services/task_assignment.py) and
       the meeting, summary and tasks are stored in Supabase (repository.py, services/tasks.py).
"""

import hashlib
import json
import logging
from datetime import datetime

from google.genai import types
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.core.settings import Settings
from app.db import repository
from app.services import recordings, task_assignment
from app.services import tasks as task_service

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 15 * 1024 * 1024  # Gemini accepts about 20 MB inline, including the prompt

PROMPT = """Transcribe this WiCS e-board meeting recording, then summarize it.
"transcript": the words spoken, in order. Do not invent speech; use "[inaudible]" where unclear.
"summary": 3 to 6 sentences covering what was decided and what is still open."""

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"transcript": {"type": "string"}, "summary": {"type": "string"}},
    "required": ["transcript", "summary"],
}


class TranscriptAndSummary(BaseModel):
    transcript: str = Field(min_length=1)
    summary: str


def audio_extension(mime_type: str) -> str | None:
    """File extension for a supported audio type (None if unsupported)."""
    return recordings.AUDIO_EXTENSIONS.get(mime_type.split(";")[0].strip())


async def transcribe_and_summarize(audio: bytes, mime_type: str, api_key: str, model: str) -> TranscriptAndSummary:
    logger.info("Transcribing %d bytes of %s with Gemini model=%s", len(audio), mime_type, model)
    response = await task_assignment.gemini_client(api_key).aio.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=audio, mime_type=mime_type.split(";")[0]), PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_json_schema=ANSWER_SCHEMA
        ),
    )
    if not response.text:
        raise ValueError("Gemini returned no text (the response may have been blocked).")
    return TranscriptAndSummary.model_validate(json.loads(response.text))


def save_audio(audio: bytes, recording_id: str, extension: str) -> None:
    recordings.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    (recordings.RECORDINGS_DIR / f"{recording_id}.{extension}").write_bytes(audio)


async def ingest_audio(audio: bytes, mime_type: str, title: str | None, held_at: datetime, settings: Settings):
    """Run the whole pipeline. Returns the response body (see routes/meetings.py for errors)."""
    extension = audio_extension(mime_type)
    assert extension is not None  # the route checks this first
    recording_id = f"audio-{hashlib.sha256(audio).hexdigest()[:32]}"
    if settings.gemini_api_key is None:
        raise ValueError("Meeting ingest requires GEMINI_API_KEY.")
    api_key = settings.gemini_api_key.get_secret_value()

    await run_in_threadpool(save_audio, audio, recording_id, extension)
    result = await transcribe_and_summarize(audio, mime_type, api_key, settings.gemini_model)
    assignments = await task_assignment.get_assignments(
        result.transcript, task_assignment.load_eboard(), api_key, settings.gemini_model
    )
    stored = await run_in_threadpool(
        task_service.store_meeting_tasks, recording_id, held_at, title, result.transcript, assignments
    )
    await run_in_threadpool(repository.save_summary, recording_id, result.summary)
    return {
        "success": True,
        "data": {
            "recording_id": recording_id,
            "transcript": result.transcript,
            "summary": result.summary,
            "tasks": [view.model_dump(mode="json") for view in stored.tasks],
        },
        "error": None,
        "meta": {"already_stored": stored.reused, "needs_review": sum(a.needs_review for a in assignments)},
    }
