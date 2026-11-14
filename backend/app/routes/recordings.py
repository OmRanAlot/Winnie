"""POST /api/recordings: receive a browser recording (audio + transcript JSON) and save the JSON
and the audio file.

Called by frontend/src/lib/api.ts (saveRecording). Checks the content type and the 15 MB limit
while streaming, validates the body against schemas.Recording, then hands it to
services/recordings.py. No authentication yet: local development only.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.schemas.api import MAX_JSON_BYTES, Recording, failure
from app.services.recordings import save_recording

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recordings", tags=["recordings"])


@router.post("", status_code=201)
async def create_recording(request: Request):
    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0] != "application/json":
        logger.warning("Recording rejected: content-type %r is not application/json", content_type)
        return failure("Expected a JSON recording.", 415)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_JSON_BYTES:
            logger.warning("Recording rejected: body exceeded %d bytes", MAX_JSON_BYTES)
            return failure("Recording exceeds the 15 MB JSON limit.", 413)
        body.extend(chunk)
    logger.info("Recording received: %d bytes", len(body))
    try:
        recording = Recording.model_validate_json(body)
    except ValidationError as error:
        logger.warning("Recording failed validation: %s", error.errors(include_input=False))
        return failure("Invalid recording. Check the audio data, size, and transcript fields.", 422)
    try:
        saved = await run_in_threadpool(save_recording, recording)
    except OSError:
        logger.exception("Could not save the recording to disk")
        return failure("Could not save the recording. Please retry or download locally.", 503)
    data = {"id": Path(saved.json_filename).stem, "filename": saved.json_filename, "audioFilename": saved.audio_filename}
    return {"success": True, "data": data, "error": None, "meta": {}}


@router.post("/{recording_id}/assignments")
async def recording_assignments(recording_id: str):
    from app.services.meeting_tasks import assign_for_recording
    from app.services.task_assignment import get_settings
    logger.info("Assignment requested for recording %s", recording_id)
    try:
        return await assign_for_recording(recording_id, get_settings())
    except (FileNotFoundError, ValueError):
        logger.warning("Recording %s not found or unreadable", recording_id, exc_info=True)
        return failure("Recording not found.", 404)
    except OSError:
        logger.exception("Could not persist task assignments for %s", recording_id)
        return failure("Could not persist task assignments.", 503)
