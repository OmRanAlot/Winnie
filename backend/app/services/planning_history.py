"""Build categorized evidence, verified role labels and measured deadline lead times."""

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median

from app.schemas.pipeline import RosterFile
from app.services.members import assignment_members
from app.services.planning_context import normalize


def read_taxonomy(text: str) -> dict:
    """Preserve supplied categories even when a title suggests another category."""
    examples = []
    for row_number, row in enumerate(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))), 2):
        name, category = row.get("Event", "").strip(), row.get("Category", "").strip()
        if name and category:
            examples.append({"event_name": name, "category": category,
                             "evidence_id": f"spring-calendar-row-{row_number}"})
    if not examples:
        raise ValueError("No event/category examples found.")
    return {"schema_version": 1, "examples": examples}


def load_rosters(path: Path | None) -> list:
    if path is None or not path.exists():
        return []
    rosters = RosterFile.model_validate_json(path.read_text(encoding="utf-8")).rosters
    if len({r.semester_code for r in rosters}) != len(rosters):
        raise ValueError("Duplicate semester rosters.")
    for roster in rosters:
        if len({m.member_code for m in roster.members}) != len(roster.members):
            raise ValueError("Duplicate roster members.")
        aliases = [{"alias": alias, "member_code": member.member_code}
                   for member in roster.members for alias in member.aliases + [member.display_name]]
        assignment_members("", aliases)  # Validate ambiguous aliases even before matching.
    return rosters


def enrich_history(knowledge: dict, rosters: list, semester: str) -> list[dict]:
    """Never interpret a historical owner's name as a role without a verified mapping."""
    roster = next((r for r in rosters if r.semester_code == semester), None)
    aliases = [{"alias": alias, "member_code": member.member_code}
               for member in roster.members for alias in member.aliases + [member.display_name]
               ] if roster else []
    members = {m.member_code: m for m in roster.members} if roster else {}
    events = json.loads(json.dumps(knowledge["events"]))
    for event in events:
        event["event_id"] = f"calendar-row-{event['calendar_row']}"
        for task in event["tasks"]:
            owner_text = task.pop("historical_assignee_text", "")
            codes = assignment_members(owner_text, aliases) if owner_text and roster else None
            task["historical_roles"] = sorted({role for code in codes for role in members[code].roles}) if codes else []
            task["role_mapping_verified"] = bool(codes)
            try:
                deadline = datetime.strptime(task["historical_deadline"], "%m/%d/%Y").date()
                task["lead_days"] = (date.fromisoformat(event["start_date"]) - deadline).days
            except ValueError:
                task["lead_days"] = None
    return events


def timing_statistics(examples: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for example in examples:
        for task in example["tasks"]:
            if task["lead_days"] is not None:
                groups[normalize(task["title"])].append(task)
    return [{"task_title": tasks[0]["title"], "sample_count": len(tasks),
             "median_lead_days": median(t["lead_days"] for t in tasks),
             "min_lead_days": min(t["lead_days"] for t in tasks),
             "max_lead_days": max(t["lead_days"] for t in tasks),
             "evidence_ids": [t["evidence_id"] for t in tasks],
             "meaning": "Days from the scheduled deadline to event start, not work duration."}
            for tasks in groups.values()]


def match_roles(tasks: list, rosters: list, semester: str) -> list[dict]:
    roster = next((r for r in rosters if r.semester_code == semester), None)
    assignments = []
    for task in tasks:
        candidates = [m for m in roster.members if m.active and task.suggested_role in m.roles] if roster else []
        proposed = candidates[0].member_code if len(candidates) == 1 else None
        reason = "Unique active role holder; proposal requires review."
        if len(candidates) != 1:
            reason = "No verified role holder." if not candidates else "Multiple role holders; choose an owner during review."
        assignments.append({"task_id": task.id, "role": task.suggested_role,
                            "candidate_member_codes": sorted(m.member_code for m in candidates),
                            "proposed_member_code": proposed, "rationale": reason})
    return assignments
