"""Ingest pipeline: audio -> stored audio -> transcript -> summary -> tasks. Resumable and
idempotent (keyed on the audio's sha256). Progress is recorded in meetings.status; the step to
resume from is derived from what is already saved, so a crash at any point is recoverable."""

from __future__ import annotations

import hashlib
import mimetypes
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.extract import extract_action_items
from app.llm import LLM
from app.repository import Repository, Row
from app.storage import AudioStore
from app.summarize import summarize_transcript
from app.transcription import Transcriber

_CHUNK = 1024 * 1024
_ERROR_MAX = 1000


class PipelineError(RuntimeError):
    """A pipeline step failed. The meeting is marked 'failed' with the error recorded."""

    def __init__(self, meeting_id: int, step: str, cause: Exception) -> None:
        super().__init__(f"meeting {meeting_id} failed at {step}: {cause}")
        self.meeting_id = meeting_id
        self.step = step


@dataclass(frozen=True)
class IngestResult:
    meeting: Row
    created: bool
    unresolved_attendees: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _record_failure(repo: Repository, meeting_id: int, step: str, exc: Exception) -> None:
    message = f"{step}: {type(exc).__name__}: {exc}"[:_ERROR_MAX]
    repo.set_meeting_status(meeting_id, "failed", message)


def ingest_meeting(
    *,
    repo: Repository,
    store: AudioStore,
    transcriber: Transcriber,
    llm: LLM,
    audio_path: Path,
    title: str | None,
    held_at: datetime,
    attendees: Sequence[str] = (),
    summary_model: str,
    extraction_model: str,
) -> IngestResult:
    if not audio_path.is_file():
        raise FileNotFoundError(f"audio file not found: {audio_path}")
    sha = sha256_file(audio_path)
    existing = repo.get_meeting_by_sha(sha)
    created = False
    if existing is None:
        data = audio_path.read_bytes()
        mime = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        storage_path = f"{sha[:2]}/{sha}{audio_path.suffix.lower()}"
        store.upload(storage_path, data, mime)  # before the row: no row without stored audio
        existing, created = repo.create_meeting(
            title=title, held_at=held_at, audio_path=storage_path, audio_mime=mime,
            audio_bytes=len(data), audio_sha256=sha, audio_bucket=store.bucket,
        )  # fmt: skip
    meeting_id: int = existing["id"]

    unresolved: list[str] = []
    member_ids: list[int] = []
    for name in attendees:
        member = repo.get_or_create_member(name, "person")
        if member is None:
            unresolved.append(name)
        else:
            member_ids.append(member.id)
    repo.add_attendees(meeting_id, member_ids)

    if existing["status"] == "done":
        return IngestResult(existing, created, tuple(unresolved))

    step = "start"
    try:
        step = "transcribing"
        if existing["transcript_text"] is None:
            repo.set_meeting_status(meeting_id, "transcribing")
            segments = transcriber.transcribe(audio_path)
            if not segments:
                raise ValueError("transcription produced no segments")
            repo.save_transcript(meeting_id, segments, transcriber.model_name)
        transcript = (repo.get_meeting_by_sha(sha) or existing)["transcript_text"] or ""

        step = "summarizing"
        if existing["summary"] is None:
            repo.set_meeting_status(meeting_id, "summarizing")
            summary = summarize_transcript(llm, transcript, model=summary_model, title=title)
            repo.save_summary(meeting_id, summary, summary_model)

        step = "extracting_tasks"
        repo.set_meeting_status(meeting_id, "extracting_tasks")
        members = repo.list_members()
        items = extract_action_items(
            llm, transcript, model=extraction_model,
            known_seats=[m.name for m in members if m.kind == "seat"],
            known_people=[m.name for m in members if m.kind == "person"],
        )  # fmt: skip
        repo.insert_extracted_tasks(meeting_id, items)
        repo.set_meeting_status(meeting_id, "done")
    except Exception as exc:
        _record_failure(repo, meeting_id, step, exc)
        raise PipelineError(meeting_id, step, exc) from exc

    final = repo.get_meeting_by_sha(sha)
    assert final is not None
    return IngestResult(final, created, tuple(unresolved))
