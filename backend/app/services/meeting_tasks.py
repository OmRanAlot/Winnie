"""Backend-owned transcript selection, assignment and persistence."""
import json
from pathlib import Path
from starlette.concurrency import run_in_threadpool
from app.services import recordings, task_assignment

async def assign_for_recording(recording_id, settings):
    recording = await run_in_threadpool(recordings.load_recording, recording_id)
    source = settings.task_transcript_source
    transcript = recording.transcription.text
    if source == "example":
        transcript = (Path(__file__).resolve().parents[2] / "data/example_transcript.json").read_text(encoding="utf-8")
    response = await task_assignment.assign_tasks(task_assignment.AssignRequest(transcript=transcript), settings)
    if not isinstance(response, dict):
        return response
    response["meta"]["source"] = source
    target = recordings.RECORDINGS_DIR / f"{recording_id}.tasks.json"
    await run_in_threadpool(target.write_text, json.dumps(response, indent=2), encoding="utf-8")
    return response
