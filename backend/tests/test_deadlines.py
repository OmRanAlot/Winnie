"""Tests for app/core/deadlines.py: spoken deadlines resolved against the meeting time (New York)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.deadlines import NEW_YORK, resolve_deadline

# Friday 2026-11-13, 18:00 in New York.
FRIDAY_EVENING = datetime(2026, 11, 13, 18, 0, tzinfo=NEW_YORK)


def ny(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NEW_YORK)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("tonight", ny(2026, 11, 13, 21)),
        ("by tonight", ny(2026, 11, 13, 21)),
        ("today", ny(2026, 11, 13, 23, 59)),
        ("by end of day", ny(2026, 11, 13, 23, 59)),
        ("EOD", ny(2026, 11, 13, 23, 59)),
        ("tomorrow", ny(2026, 11, 14, 23, 59)),
        ("tomorrow morning", ny(2026, 11, 14, 9)),
        ("tomorrow night", ny(2026, 11, 14, 21)),
        ("Monday", ny(2026, 11, 16, 23, 59)),
        ("Monday morning", ny(2026, 11, 16, 9)),
        ("by Monday noon", ny(2026, 11, 16, 12)),
        ("By Monday at noon.", ny(2026, 11, 16, 12)),
        ("before Tuesday afternoon", ny(2026, 11, 17, 15)),
        ("Wed evening", ny(2026, 11, 18, 21)),
        ("by Thursday 5pm", ny(2026, 11, 19, 17)),
        ("Thursday at 5:30 p.m.", ny(2026, 11, 19, 17, 30)),
        ("due by this Sunday", ny(2026, 11, 15, 23, 59)),
        ("noon", ny(2026, 11, 13, 12)),
        ("by 9am Saturday", ny(2026, 11, 14, 9)),
        ("Saturday 17:00", ny(2026, 11, 14, 17)),
        ("12am Saturday", ny(2026, 11, 14, 0)),
        ("12pm Saturday", ny(2026, 11, 14, 12)),
    ],
)
def test_resolves_simple_relative_phrases(raw, expected):
    assert resolve_deadline(raw, FRIDAY_EVENING) == expected


def test_same_weekday_means_next_week():
    assert resolve_deadline("Friday", FRIDAY_EVENING) == ny(2026, 11, 20, 23, 59)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "soon",
        "ASAP",
        "next week",
        "next Monday",
        "in two days",
        "by the end of the month",
        "December 3rd",
        "at 5",
        "Monday at 5:30",
        "13pm",
        "Monday Tuesday",
        "noon noon",
        "whenever Bob has time",
    ],
)
def test_returns_none_instead_of_guessing(raw):
    assert resolve_deadline(raw, FRIDAY_EVENING) is None


def test_none_input_returns_none():
    assert resolve_deadline(None, FRIDAY_EVENING) is None


def test_aware_reference_in_utc_is_converted_to_new_york():
    # 2026-11-14 02:00 UTC is still Friday 21:00 in New York, so "tomorrow" is Saturday.
    reference = datetime(2026, 11, 14, 2, 0, tzinfo=UTC)
    assert resolve_deadline("tomorrow", reference) == ny(2026, 11, 14, 23, 59)


def test_naive_reference_is_treated_as_new_york_time():
    assert resolve_deadline("tonight", datetime(2026, 11, 13, 18, 0)) == ny(2026, 11, 13, 21)


def test_offset_follows_daylight_saving_change():
    # DST ends Sunday 2026-11-01. A Friday-before meeting resolving to Monday gets EST (-05:00).
    reference = datetime(2026, 10, 30, 12, 0, tzinfo=NEW_YORK)
    result = resolve_deadline("Monday morning", reference)
    assert result == ny(2026, 11, 2, 9)
    assert result.utcoffset() == ny(2026, 11, 2, 9).utcoffset()
    assert result.astimezone(ZoneInfo("UTC")).hour == 14
