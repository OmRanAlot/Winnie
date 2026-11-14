from pathlib import Path
from uuid import uuid4

from app.schemas.recording import Recording

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "data" / "recordings"


def save_recording(recording: Recording) -> str:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"conversation-{uuid4()}.json"
    path = RECORDINGS_DIR / filename
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(recording.model_dump_json(indent=2))
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return filename
