"""Previous board roles for member profiles, and who can advise on a role from experience.

Source: Supabase members.previous_roles when filled in, else backend/data/member_previous_roles.json
(the board-provided list). Skills from a previous role are the role-derived skills of whoever holds
that role now (backend/data/member_skills.json), so they are grounded in the role's real
description; a role that no longer exists (e.g. Fundraising Coordinator) adds no skills.

advisors_for() is for the planned Photon flow: when someone is stuck, start a group chat with
members who held their role before.

    uv run python -m app.services.member_history --apply   # write the JSON to Supabase
"""

import argparse
import json
from pathlib import Path

from app.services.member_skills import flat

HISTORY_FILE = Path(__file__).resolve().parents[2] / "data" / "member_previous_roles.json"


def load_previous_roles(path: Path = HISTORY_FILE) -> dict[str, list[str]]:
    """{member code: [previous role, ...]} from the board-provided JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {code: [r["role"] for r in entry.get("previous_roles", [])]
            for code, entry in data.items() if not code.startswith("_")}


def _key(role: str) -> str:
    return " ".join((role or "").casefold().split())


def with_previous_roles(members: list[dict], history: dict[str, list[str]],
                        saved: dict[str, list[str]], skills: dict) -> list[dict]:
    """Add previous_roles and previous_role_skills. Supabase (saved) wins over the JSON."""
    skills_by_role: dict[str, list[str]] = {}
    for m in members:
        entry = skills.get(m["code"])
        if entry:
            skills_by_role.setdefault(_key(m["board_role"]), flat(entry))
    result = []
    for m in members:
        roles = saved.get(m["code"]) or history.get(m["code"], [])
        gained = []
        for role in roles:
            if _key(role) != _key(m["board_role"]):  # same role as now adds nothing new
                gained += [s for s in skills_by_role.get(_key(role), []) if s not in gained]
        result.append({**m, "previous_roles": roles, "previous_role_skills": gained,
                       "previous_roles_source": "supabase" if saved.get(m["code"])
                       else ("board-list" if roles else None)})
    return result


def advisors_for(member: dict, members: list[dict]) -> list[dict]:
    """Other members who previously held this member's current role."""
    role = _key(member["board_role"])
    return [m for m in members if m["code"] != member["code"]
            and any(_key(r) == role for r in m.get("previous_roles", []))]


def main():
    from app.services.members import MemberStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write previous roles to Supabase")
    args = parser.parse_args()
    history = load_previous_roles()
    for code, roles in history.items():
        print(f"{code}: {', '.join(roles)}")
    if args.apply:
        store = MemberStore()
        for code, roles in history.items():
            store._execute("members", lambda table, c=code, r=roles: table.update(
                {"previous_roles": r}).eq("code", c))
        print(f"Wrote previous roles for {len(history)} members to Supabase members.previous_roles.")


if __name__ == "__main__":
    main()
