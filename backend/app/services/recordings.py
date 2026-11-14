"""Save a validated browser recording to disk: one JSON file plus the audio as its own file.

Files go to backend/data/recordings/ (gitignored: they contain private audio and transcripts):
  conversation-<uuid>.json   the full recording (transcript + base64 audio)
  conversation-<uuid>.<ext>  the decoded audio, playable directly (webm, m4a, ogg, wav, mp3)
Called by routes/recordings.py.
"""

import base64
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from app.schemas import Recording

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "data" / "recordings"

AUDIO_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
}


class SavedRecording(NamedTuple):
    json_filename: str
    audio_filename: str


def save_recording(recording: Recording) -> SavedRecording:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"conversation-{uuid4()}"
    mime = recording.audio.mimeType.split(";")[0]
    saved = SavedRecording(f"{stem}.json", f"{stem}.{AUDIO_EXTENSIONS[mime]}")
    audio_path = RECORDINGS_DIR / saved.audio_filename
    json_path = RECORDINGS_DIR / saved.json_filename
    try:
        with audio_path.open("xb") as output:
            output.write(base64.b64decode(recording.audio.data))
        with json_path.open("x", encoding="utf-8") as output:
            output.write(recording.model_dump_json(indent=2))
    except OSError:
        audio_path.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)
        raise
    return saved


def load_recording(recording_id: str) -> Recording:
    import re
    if not re.fullmatch(r"conversation-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", recording_id):
        raise FileNotFoundError(recording_id)
    return Recording.model_validate_json((RECORDINGS_DIR / f"{recording_id}.json").read_text(encoding="utf-8"))
