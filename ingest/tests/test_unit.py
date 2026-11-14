"""Unit tests (no database): member matching, code generation, extraction validation + retry."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.config import ConfigError, load_settings
from app.extract import MAX_RETRIES, ExtractionError, extract_action_items, parse_extraction
from app.llm import FakeLLM
from app.models import Member
from app.repository import _owner_code, format_task_code, match_member, month_code_for


def member(id_: int, code: str, name: str, kind: str = "person", seat: str | None = None,
           aliases: tuple[str, ...] = (), active: bool = True) -> Member:
    return Member(id_, code, kind, name, seat, aliases, active)  # type: ignore[arg-type]


PEOPLE = [
    member(1, "BOBN", "Bob Newman", seat="Secretary"),
    member(2, "ALI", "Alice Park", aliases=("ally",)),
    member(3, "BOBS", "Bob Smith"),
    member(4, "OLD", "Olga Old", active=False),
]
SEATS = [
    member(10, "SEC", "Secretary", "seat", aliases=("sec",)),
    member(11, "VP", "Vice President", "seat", aliases=("vp",)),
    member(12, "PRES", "President", "seat"),
]


def found(members, text, kind=None):
    result, _ = match_member(members, text, kind)
    assert result is not None
    return result


def test_match_exact_name_code_alias_case_insensitive():
    assert found(PEOPLE, "alice park").id == 2
    assert found(PEOPLE, "ALI").id == 2
    assert found(PEOPLE, "Ally").id == 2


def test_match_unique_first_name_resolves():
    assert found([PEOPLE[0], PEOPLE[1]], "Bob").name == "Bob Newman"


def test_match_ambiguous_first_name_returns_none_and_flags():
    assert match_member(PEOPLE, "Bob") == (None, True)


def test_match_unknown_and_empty():
    assert match_member(PEOPLE, "Zed") == (None, False)
    assert match_member(PEOPLE, "   ") == (None, False)
    assert match_member(PEOPLE, None) == (None, False)


def test_match_ignores_inactive_members():
    assert match_member(PEOPLE, "Olga") == (None, False)


def test_match_exact_beats_partial_for_seats():
    assert found(SEATS, "President").code == "PRES"  # not ambiguous with Vice President
    assert found(SEATS, "vice president").code == "VP"


def test_match_respects_kind_filter():
    assert match_member(PEOPLE + SEATS, "Secretary", "person") == (None, False)
    assert found(PEOPLE + SEATS, "Secretary", "seat").code == "SEC"


def test_owner_code_by_codes_meaning():
    bob, sec = PEOPLE[0], SEATS[0]
    allm = PEOPLE + SEATS
    assert _owner_code("seat", sec, None, allm) == "SEC"
    assert _owner_code("seat", None, bob, allm) == "SEC"  # falls back to the seat Bob holds
    assert _owner_code("seat", None, PEOPLE[1], allm) is None
    assert _owner_code("person", sec, bob, allm) == "BOBN"
    assert _owner_code("person", sec, None, allm) is None
    assert _owner_code("mixed", sec, bob, allm) == "BOBN"
    assert _owner_code("mixed", sec, None, allm) == "SEC"


def test_task_code_and_month_code_format():
    assert format_task_code("2026-11", 7) == "WIN-202611-7"
    # 2026-12-01 02:00 UTC is still November evening in New York; noon UTC is December.
    assert month_code_for(datetime(2026, 12, 1, 2, 0, tzinfo=UTC)) == "2026-11"
    assert month_code_for(datetime(2026, 12, 1, 12, 0, tzinfo=UTC)) == "2026-12"


GOOD = {"items": [{"title": "Order pizza", "seat": "Treasurer", "deadline": "tonight"}]}


def test_parse_extraction_accepts_fences_and_bare_list():
    fenced = "```json\n" + json.dumps(GOOD) + "\n```"
    assert parse_extraction(fenced)[0].title == "Order pizza"
    assert parse_extraction(json.dumps(GOOD["items"]))[0].needs_review is False


@pytest.mark.parametrize("raw", ["not json", '{"items": [{"description": "no title"}]}',
                                 '{"items": [{"title": ""}]}', '{"wrong": []}'])
def test_parse_extraction_rejects_invalid(raw):
    with pytest.raises(ValueError):  # pydantic ValidationError subclasses ValueError
        parse_extraction(raw)


def test_extraction_retries_with_error_fed_back():
    llm = FakeLLM(["oops not json", json.dumps(GOOD)])
    items = extract_action_items(llm, "transcript", model="m")
    assert [i.title for i in items] == ["Order pizza"]
    assert len(llm.calls) == 2
    retry_msgs = llm.calls[1]["messages"]
    assert retry_msgs[-2] == {"role": "assistant", "content": "oops not json"}
    assert "invalid" in retry_msgs[-1]["content"].lower()


def test_extraction_gives_up_after_two_retries():
    llm = FakeLLM(["nope"])
    with pytest.raises(ExtractionError):
        extract_action_items(llm, "transcript", model="m")
    assert len(llm.calls) == 1 + MAX_RETRIES


def test_extraction_empty_items_is_valid():
    assert extract_action_items(FakeLLM(['{"items": []}']), "t", model="m") == []


def test_config_fails_loudly_without_leaking_values():
    with pytest.raises(ConfigError) as exc:
        load_settings(require=["SUPABASE_DB_URL", "ANTHROPIC_API_KEY"], env={"X": "y"})
    assert "SUPABASE_DB_URL" in str(exc.value) and "ANTHROPIC_API_KEY" in str(exc.value)


def test_config_reads_models_from_env_and_redacts_repr():
    s = load_settings(env={"SUMMARY_MODEL": "m1", "ANTHROPIC_API_KEY": "sekret"})
    assert s.summary_model == "m1" and s.owner_code_kind == "seat"
    assert "sekret" not in repr(s)


def test_config_rejects_bad_owner_code_kind():
    with pytest.raises(ConfigError):
        load_settings(env={"OWNER_CODE_KIND": "robots"})
