"""Backend-owned transcript selection, assignment and persistence."""
import json
import logging
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from app.services import recordings, task_assignment

logger = logging.getLogger(__name__)

async def assign_for_recording(recording_id, settings):
    recording = await run_in_threadpool(recordings.load_recording, recording_id)
    source = settings.task_transcript_source
    transcript = recording.transcription.text
    if source == "example":
        logger.info("Using the example transcript instead of recording %s", recording_id)
        transcript = (Path(__file__).resolve().parents[2] / "data/example_transcript.json").read_text(encoding="utf-8")
    logger.info("Assigning tasks for %s (source=%s, %d transcript chars)", recording_id, source, len(transcript))
    response = await task_assignment.assign_tasks(task_assignment.AssignRequest(transcript=transcript), settings)
    if not isinstance(response, dict):
        logger.warning("Assignment for %s returned an error response (status %s); nothing saved",
                       recording_id, getattr(response, "status_code", "?"))
        return response
    response["meta"]["source"] = source
    target = recordings.RECORDINGS_DIR / f"{recording_id}.tasks.json"
    await run_in_threadpool(target.write_text, json.dumps(response, indent=2), encoding="utf-8")
    logger.info("Saved %d assignments to %s", response["meta"].get("count", 0), target.name)
    return response
