from pathlib import Path
"""POST /api/recordings: receive a browser recording (audio + transcript JSON) and save the JSON
and the audio file.

Called by frontend/src/lib/api.ts (saveRecording). Checks the content type and the 15 MB limit
while streaming, validates the body against schemas.Recording, then hands it to
services/recordings.py. No authentication yet: local development only.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.schemas import MAX_JSON_BYTES, Recording, failure
from app.services.recordings import save_recording

router = APIRouter(prefix="/api/recordings", tags=["recordings"])


@router.post("", status_code=201)
async def create_recording(request: Request):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        return failure("Expected a JSON recording.", 415)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_JSON_BYTES:
            return failure("Recording exceeds the 15 MB JSON limit.", 413)
        body.extend(chunk)
    try:
        recording = Recording.model_validate_json(body)
    except ValidationError:
        return failure("Invalid recording. Check the audio data, size, and transcript fields.", 422)
    try:
        saved = await run_in_threadpool(save_recording, recording)
    except OSError:
        return failure("Could not save the recording. Please retry or download locally.", 503)
    data = {"id": Path(saved.json_filename).stem, "filename": saved.json_filename, "audioFilename": saved.audio_filename}
    return {"success": True, "data": data, "error": None, "meta": {}}

@router.post("/{recording_id}/assignments")
async def recording_assignments(recording_id: str):
    from app.services.meeting_tasks import assign_for_recording
    from app.services.task_assignment import get_settings
    try:
        return await assign_for_recording(recording_id, get_settings())
    except (FileNotFoundError, ValueError):
        return failure("Recording not found.", 404)
    except OSError:
        return failure("Could not persist task assignments.", 503)
