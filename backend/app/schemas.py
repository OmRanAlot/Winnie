"""API request/response shapes: what crosses HTTP between the frontend and the backend.

Currently contains only the browser Recording (audio + transcript saved as one JSON file).
Used by routes/recordings.py. The planned {success, data, error, meta} envelope and per-feature
shapes are described in app/__init__.py. These shapes are the contract the replacement frontend
is built against, so change them deliberately.
"""

import base64
import binascii
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 15 * 1024 * 1024


class Audio(BaseModel):
    mimeType: str = Field(pattern=r"^audio/(webm|mp4|ogg|wav|mpeg)(;.*)?$")
    encoding: Literal["base64"]
    sizeBytes: int = Field(gt=0, le=MAX_AUDIO_BYTES)
    data: str = Field(max_length=14 * 1024 * 1024)

    @model_validator(mode="after")
    def valid_audio(self):
        try:
            decoded = base64.b64decode(self.data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid base64 audio") from exc
        if len(decoded) != self.sizeBytes:
            raise ValueError("Audio size does not match sizeBytes")
        return self


class Transcript(BaseModel):
    language: str = Field(max_length=20)
    text: str = Field(max_length=500_000)
    provider: Literal["browser-speech-recognition"] = "browser-speech-recognition"
    status: Literal["completed", "partial", "unavailable", "manual"]


class Recording(BaseModel):
    schemaVersion: Literal[1]
    title: str = Field(min_length=1, max_length=120)
    startedAt: datetime
    durationMs: int = Field(ge=0)
    transcription: Transcript
    audio: Audio
