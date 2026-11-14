"""Speech to text: a Protocol, a local faster-whisper implementation, and a fake."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from app.models import Segment


class Transcriber(Protocol):
    model_name: str

    def transcribe(self, audio_path: Path) -> list[Segment]: ...


class FasterWhisperTranscriber:
    """Local transcription (no API key). faster-whisper is imported lazily; install with
    `pip install -e '.[whisper]'`. Whisper does not diarize, so speaker_label is None."""

    def __init__(self, model_name: str = "small") -> None:
        self.model_name = model_name
        self._model: Any = None

    def transcribe(self, audio_path: Path) -> list[Segment]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install -e '.[whisper]'"
            ) from exc
        if self._model is None:
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        raw_segments, _info = self._model.transcribe(str(audio_path))
        segments: list[Segment] = []
        for seg in raw_segments:
            text = seg.text.strip()
            if not text:
                continue
            segments.append(
                Segment(
                    idx=len(segments),
                    start_ms=int(seg.start * 1000),
                    end_ms=int(seg.end * 1000),
                    speaker_label=None,
                    text=text,
                )
            )
        return segments


class FakeTranscriber:
    """Returns canned segments; can be told to fail the first N calls."""

    model_name = "fake-transcriber"

    def __init__(self, segments: Sequence[Segment], fail_times: int = 0) -> None:
        self._segments = list(segments)
        self.fail_times = fail_times
        self.calls = 0

    def transcribe(self, audio_path: Path) -> list[Segment]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("fake transcription failure")
        return list(self._segments)
