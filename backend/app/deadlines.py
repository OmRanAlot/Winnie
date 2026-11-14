"""Turn a spoken deadline ("by Monday noon") into a datetime, relative to the meeting time.

Called by app/repository.py (insert_extracted_tasks) to fill tasks.deadline_at; the original
phrase is always kept in tasks.deadline_raw. Everything is resolved in America/New_York.

Grammar (case-insensitive, filler words like "by", "before", "due", "at", "on", "this" ignored):
    [day] [time]   or   [time] [day]       (at least one of the two)
    day:  today | tonight | tomorrow | a weekday ("mon", "monday", ...)
    time: morning 09:00 | noon/midday 12:00 | afternoon 15:00 | evening/night 21:00
          | end of day/EOD 23:59 | a clock time with am/pm ("5pm", "5:30 p.m.") | 24h "17:00"
Defaults: no day means the meeting day; no time means 23:59 (end of that day); "tonight" is
today at 21:00. A weekday is its next occurrence AFTER the meeting day (said on Friday,
"Friday" means next week's Friday).

Anything outside this grammar ("next week", "soon", "at 5", "December 3rd") returns None. The
function never guesses: a None deadline is shown as unscheduled and left for a human.
"""

import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")

END_OF_DAY = time(23, 59)
NAMED_TIMES = {
    "morning": time(9, 0),
    "noon": time(12, 0),
    "midday": time(12, 0),
    "afternoon": time(15, 0),
    "evening": time(21, 0),
    "night": time(21, 0),
    "eod": END_OF_DAY,
}
WEEKDAYS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}  # fmt: skip
FILLER_WORDS = {"by", "before", "until", "due", "at", "on", "this", "in", "the"}

CLOCK_12H = re.compile(r"(\d{1,2})(?::(\d{2}))?(am|pm)")
CLOCK_24H = re.compile(r"(\d{1,2}):(\d{2})")


def _normalize(raw: str) -> list[str]:
    text = raw.lower().strip()
    text = text.replace("a.m.", "am").replace("p.m.", "pm")
    text = re.sub(r"\bend of (the )?day\b|\bcob\b", "eod", text)
    text = re.sub(r"\btonight\b", "today night", text)
    text = re.sub(r"(\d)\s+(am|pm)\b", r"\1\2", text)
    text = re.sub(r"[.,!;]+(\s|$)", r"\1", text)
    return [token for token in text.split() if token not in FILLER_WORDS]


def _parse_clock(token: str) -> time | None:
    if match := CLOCK_12H.fullmatch(token):
        hour, minute = int(match[1]), int(match[2] or 0)
        if not 1 <= hour <= 12 or minute > 59:
            return None
        return time(hour % 12 + (12 if match[3] == "pm" else 0), minute)
    if match := CLOCK_24H.fullmatch(token):
        hour, minute = int(match[1]), int(match[2])
        # "5:30" could be morning or evening, so only unambiguous 24-hour times count.
        if 13 <= hour <= 23 and minute <= 59:
            return time(hour, minute)
    return None


def _parse_day(token: str, today: date) -> date | None:
    if token == "today":
        return today
    if token == "tomorrow":
        return today + timedelta(days=1)
    if token in WEEKDAYS:
        days_ahead = (WEEKDAYS[token] - today.weekday()) % 7 or 7
        return today + timedelta(days=days_ahead)
    return None


def resolve_deadline(raw: str | None, reference: datetime) -> datetime | None:
    """Resolve `raw` against `reference` (the meeting time). Naive references are New York time.

    Returns an aware datetime in America/New_York, or None when the phrase is not understood.
    """
    if not raw or not raw.strip():
        return None
    if reference.tzinfo is None:
        local = reference.replace(tzinfo=NEW_YORK)
    else:
        local = reference.astimezone(NEW_YORK)
    tokens = _normalize(raw)
    if not 1 <= len(tokens) <= 2:
        return None
    day: date | None = None
    at: time | None = None
    for token in tokens:
        parsed_day = _parse_day(token, local.date())
        parsed_time = NAMED_TIMES.get(token) or _parse_clock(token)
        if parsed_day and day is None:
            day = parsed_day
        elif parsed_time and at is None:
            at = parsed_time
        else:
            return None  # unknown word, or a second day / second time
    return datetime.combine(day or local.date(), at or END_OF_DAY, tzinfo=NEW_YORK)
