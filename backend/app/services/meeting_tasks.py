"""Backend-owned transcript selection, assignment and persistence.

Called by routes/recordings.py (POST /api/recordings/{id}/assignments). Picks the transcript
(the recording's, or the example one when WINNIE_TASK_TRANSCRIPT_SOURCE=example), asks Gemini
for assignments (services/task_assignment.py), then stores the meeting and every task in
Supabase (services/tasks.py) so they show up on the timeline (GET /api/tasks).

Storing is idempotent per recording (meetings.recording_id is unique): a retry returns the
tasks already stored, with meta.already_stored=true, instead of duplicating them. If storing
fails, the assignments are still returned with meta.stored=false and meta.store_error, so the
caller can show them and the failure is never silent.
"""

import logging
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from app.domain.models import ExtractedTask
from app.services import recordings, task_assignment
from app.services import tasks as task_service

logger = logging.getLogger(__name__)

EXAMPLE_TRANSCRIPT = Path(__file__).resolve().parents[2] / "data" / "example_transcript.json"


async def assign_for_recording(recording_id, settings):
    recording = await run_in_threadpool(recordings.load_recording, recording_id)
    source = settings.task_transcript_source
    transcript = recording.transcription.text
    if source == "example":
        logger.info("Using the example transcript instead of recording %s", recording_id)
        transcript = EXAMPLE_TRANSCRIPT.read_text(encoding="utf-8")
    logger.info("Assigning tasks for %s (source=%s, %d transcript chars)", recording_id, source, len(transcript))
    response = await task_assignment.assign_tasks(task_assignment.AssignRequest(transcript=transcript), settings)
    if not isinstance(response, dict):
        logger.warning("Assignment for %s returned an error response (status %s); nothing saved",
                       recording_id, getattr(response, "status_code", "?"))
        return response
    response["meta"]["source"] = source
    assignments = [ExtractedTask(**item) for item in response["data"]["assignments"]]
    try:
        stored = await run_in_threadpool(
            task_service.store_meeting_tasks,
            recording_id, recording.startedAt, recording.title, transcript, assignments,
        )
    except task_service.STORAGE_ERRORS:
        logger.exception("Could not store %d tasks for %s in Supabase", len(assignments), recording_id)
        response["data"]["tasks"] = []
        response["meta"].update(stored=False, store_error="Tasks were not saved: the task store is unavailable.")
        return response
    response["data"]["tasks"] = [view.model_dump(mode="json") for view in stored.tasks]
    response["meta"].update(stored=True, already_stored=stored.reused)
    if stored.reused:
        logger.info("Recording %s was already stored; returned its %d existing tasks", recording_id, len(stored.tasks))
    else:
        logger.info("Stored %d tasks for %s", len(stored.tasks), recording_id)
    return response
