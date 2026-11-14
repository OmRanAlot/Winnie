"""Turn an exported WiCS task tracker CSV into data/tracker_tasks.csv with ROLES instead of people.

The raw export contains NJIT emails and names, so it is never stored in this folder. Assignees are
mapped to board roles with the roster (backend/data/eboardMembers.json) and the verified aliases
(backend/data/member_aliases.json); emails in the Notes column are replaced the same way.

    python3 simulations/prepare_tasks.py "path/to/Task Tracker export.csv"
"""

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "backend" / "data"
OUT = HERE / "data" / "tracker_tasks.csv"
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+", re.I)

ROLE_NAMES = {
    "President": "President", "Vice President": "Vice President", "Secretary": "Secretary",
    "Treasurer": "Treasurer", "Industry Partnership1": "Industry Partnership Chair 1",
    "Industry Partnership2": "Industry Partnership Chair 2", "PR1": "PR Chair 1", "PR2": "PR Chair 2",
    "Event Co-ordinator1": "Event Coordinator 1", "Event Co-ordinator2": "Event Coordinator 2",
    "Technical Director": "Technical Director", "Membership chair": "Membership Chair",
    "Community Outreach": "Community Outreach Chair",
}


def alias_table() -> dict[str, str]:
    roster = json.loads((DATA / "eboardMembers.json").read_text())
    aliases = json.loads((DATA / "member_aliases.json").read_text())
    table = {v["name"].casefold(): ROLE_NAMES[seat] for seat, v in roster.items()}
    table |= {k.casefold(): ROLE_NAMES[v] for k, v in aliases.items() if not k.startswith("_")}
    return table


def roles_in(cell: str, table: dict[str, str]) -> list[str]:
    text = " ".join(cell.casefold().split())
    if text in {"everyone", "all"}:
        return ["Whole board"]
    if text == "external":
        return ["External"]
    found, rest = [], text
    for alias in sorted(table, key=len, reverse=True):  # longest first: full names before parts
        if alias in rest:
            found.append(table[alias])
            rest = rest.replace(alias, " ")
    if rest.strip():
        raise SystemExit(f"Unrecognised assignee text in tracker: {rest.strip()!r}")
    return sorted(set(found), key=found.index)


def main(src: str) -> None:
    table = alias_table()
    with open(src, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header = next(i for i, r in enumerate(rows) if r[:2] == ["Event", "Task Name"])
    out = []
    for r in rows[header + 1:]:
        if not any(r):
            continue
        event, task, status, priority, assignee, deadline, notes, task_id = (r + [""] * 8)[:8]
        roles = roles_in(assignee, table)
        notes = EMAIL.sub(lambda m: table.get(m.group(0).casefold(), "a board member"), notes)
        out.append({
            "task_id": task_id.strip(), "event": event.strip(), "task": " ".join(task.split()),
            "status": status.strip(), "priority": priority.strip(),
            "assignee_roles": "; ".join(roles) or "Unassigned", "n_assignees": len(roles),
            "deadline": datetime.strptime(deadline.strip(), "%m/%d/%Y").date().isoformat(),
            "notes": " ".join(notes.split()),
        })
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(out[0]))
        writer.writeheader()
        writer.writerows(out)
    print(f"Wrote {len(out)} tasks to {OUT.relative_to(HERE.parent)} (roles only, no contact details).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
