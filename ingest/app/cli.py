"""Command line: python -m app.cli <command>. Output is JSON so it can be piped into jq."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import ConfigError, Settings, load_settings
from app.db import make_pool
from app.deadlines import NEW_YORK
from app.llm import LLM, AnthropicLLM, FakeLLM, Message
from app.models import Segment
from app.pipeline import PipelineError, ingest_meeting
from app.repository import Repository
from app.storage import AudioStore, InMemoryAudioStore, SupabaseAudioStore
from app.transcription import FakeTranscriber, FasterWhisperTranscriber, Transcriber

FAKE_SEGMENTS = (
    Segment(0, 0, 4000, None, "Okay, the Treasurer will order pizza for the kickoff by Monday noon."),
    Segment(1, 4000, 8000, None, "Bob will send the sponsor email tonight."),
)
FAKE_EXTRACTION = json.dumps({"items": [
    {"title": "Order pizza for kickoff", "description": "Order food for the kickoff event",
     "seat": "Treasurer", "assignee": None, "rationale": "Treasurer will order pizza",
     "deadline": "by Monday noon", "needs_review": False},
    {"title": "Send sponsor email", "description": "", "seat": None, "assignee": "Bob",
     "rationale": "Bob will send the sponsor email", "deadline": "tonight",
     "needs_review": False},
]})  # fmt: skip


def _fake_llm_reply(system: str, _messages: Sequence[Message]) -> str:
    if "extract action items" in system:
        return FAKE_EXTRACTION
    return "- Kickoff pizza ordered by the Treasurer\n- Bob sends the sponsor email tonight"


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str))


def _parse_held_at(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=NEW_YORK)


def _repo(settings: Settings) -> Repository:
    assert settings.supabase_db_url
    return Repository(make_pool(settings.supabase_db_url), settings.owner_code_kind)


def _members(repo: Repository, args: argparse.Namespace) -> int:
    if args.action == "add":
        member = repo.add_member(args.code, args.name, args.kind, args.seat, args.alias)
        _json(member.__dict__)
    else:
        _json([m.__dict__ for m in repo.list_members(args.kind, active_only=not args.all)])
    return 0


def _tasks(repo: Repository, args: argparse.Namespace) -> int:
    if args.action == "list":
        _json(repo.list_tasks(
            status=args.status, owner_code=args.owner, month_code=args.month,
            source=args.source, meeting_id=args.meeting,
            due_before=date.fromisoformat(args.due_before) if args.due_before else None,
            limit=args.limit,
        ))  # fmt: skip
    elif args.action == "add":
        month = args.month or datetime.now(NEW_YORK).strftime("%Y-%m")
        _json(repo.add_task(
            title=args.title, description=args.description, month_code=month,
            owner_code=args.owner, due_date=args.due, event_tag=args.event_tag,
            tags=args.tag, status=args.status or "todo", source="manual",
        ))  # fmt: skip
    else:
        changes: dict[str, Any] = {
            k: v for k, v in (("status", args.status), ("owner_code", args.owner),
                              ("title", args.title), ("due_date", args.due)) if v is not None
        }  # fmt: skip
        _json(repo.update_task(args.ref, **changes))
    return 0


def _ingest(settings: Settings, repo: Repository, args: argparse.Namespace) -> int:
    store: AudioStore
    transcriber: Transcriber
    llm: LLM
    if args.dry_run_fakes:
        store, transcriber = InMemoryAudioStore(), FakeTranscriber(FAKE_SEGMENTS)
        llm = FakeLLM([_fake_llm_reply])
        summary_model = extraction_model = "fake-llm"
    else:
        missing = [n for n, v in (
            ("SUPABASE_URL", settings.supabase_url),
            ("SUPABASE_SERVICE_ROLE_KEY", settings.supabase_service_role_key),
            ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
            ("SUMMARY_MODEL", settings.summary_model),
            ("EXTRACTION_MODEL", settings.extraction_model)) if not v]  # fmt: skip
        if missing:
            raise ConfigError("Missing required environment variable(s): " + ", ".join(missing))
        assert settings.supabase_url and settings.supabase_service_role_key
        assert settings.anthropic_api_key and settings.summary_model and settings.extraction_model
        store = SupabaseAudioStore(
            settings.supabase_url, settings.supabase_service_role_key, settings.audio_bucket
        )
        transcriber = FasterWhisperTranscriber(settings.whisper_model)
        llm = AnthropicLLM(settings.anthropic_api_key)
        summary_model, extraction_model = settings.summary_model, settings.extraction_model
    result = ingest_meeting(
        repo=repo, store=store, transcriber=transcriber, llm=llm, audio_path=Path(args.audio),
        title=args.title, held_at=_parse_held_at(args.held_at), attendees=args.attendee,
        summary_model=summary_model, extraction_model=extraction_model,
    )  # fmt: skip
    detail = repo.get_meeting(result.meeting["id"])
    _json({"created": result.created, "unresolved_attendees": result.unresolved_attendees,
           "meeting": detail})  # fmt: skip
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="audio file -> transcript, summary, tasks")
    ing.add_argument("audio")
    ing.add_argument("--title")
    ing.add_argument("--held-at", required=True, help="ISO 8601; naive = America/New_York")
    ing.add_argument("--attendee", action="append", default=[], help="repeatable")
    ing.add_argument("--dry-run-fakes", action="store_true",
                     help="fake transcriber/LLM/storage (the database is still written)")  # fmt: skip

    meetings = sub.add_parser("meetings")
    msub = meetings.add_subparsers(dest="action", required=True)
    msub.add_parser("list")
    show = msub.add_parser("show")
    show.add_argument("id", type=int)

    tasks = sub.add_parser("tasks")
    tsub = tasks.add_subparsers(dest="action", required=True)
    tl = tsub.add_parser("list")
    for flag in ("status", "owner", "month", "source", "due-before"):
        tl.add_argument(f"--{flag}")
    tl.add_argument("--meeting", type=int)
    tl.add_argument("--limit", type=int, default=100)
    ta = tsub.add_parser("add")
    ta.add_argument("--title", required=True)
    ta.add_argument("--description", default="")
    for flag in ("month", "owner", "due", "event-tag", "status"):
        ta.add_argument(f"--{flag}")
    ta.add_argument("--tag", action="append", default=[])
    tu = tsub.add_parser("update")
    tu.add_argument("ref", help="task uuid or task_code")
    for flag in ("status", "owner", "title", "due"):
        tu.add_argument(f"--{flag}")

    members = sub.add_parser("members")
    sub_m = members.add_subparsers(dest="action", required=True)
    ma = sub_m.add_parser("add")
    ma.add_argument("--code", required=True)
    ma.add_argument("--name", required=True)
    ma.add_argument("--kind", choices=["person", "seat"], default="person")
    ma.add_argument("--seat")
    ma.add_argument("--alias", action="append", default=[])
    ml = sub_m.add_parser("list")
    ml.add_argument("--kind", choices=["person", "seat"])
    ml.add_argument("--all", action="store_true", help="include inactive")

    s = sub.add_parser("search", help="full-text search over transcripts")
    s.add_argument("text")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(require=["SUPABASE_DB_URL"])
        repo = _repo(settings)
        if args.command == "ingest":
            return _ingest(settings, repo, args)
        if args.command == "members":
            return _members(repo, args)
        if args.command == "tasks":
            return _tasks(repo, args)
        if args.command == "search":
            _json(repo.search_transcripts(args.text))
        elif args.action == "list":
            _json(repo.list_meetings())
        else:
            meeting = repo.get_meeting(args.id)
            if meeting is None:
                print(f"meeting {args.id} not found", file=sys.stderr)
                return 1
            _json(meeting)
        return 0
    except (ConfigError, PipelineError, LookupError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
