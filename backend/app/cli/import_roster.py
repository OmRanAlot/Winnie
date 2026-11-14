"""Preview a WiCS roster TSV, prepare private SQL, or import through the server-only RPC.

Run from backend/: python -m app.import_roster PATH [--prepare-sql | --apply]
No invitations, Auth accounts, or messaging sender mappings are created.
"""

import argparse
import json
from pathlib import Path

from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable, create_task_client
from app.services.roster_import import parse_roster

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
MIGRATION = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / (
    "20261114140000_link_member_roster.sql"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--prepare-sql", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    records, warnings = parse_roster(args.path)
    print(json.dumps({
        "members": len(records),
        "provided_emails": sum(bool(row["email"]) for row in records),
        "provided_phones": sum(bool(row["phone_number"]) for row in records),
        "warnings": warnings,
    }, indent=2))
    if args.prepare_sql:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Contacts are written only to gitignored local data, never to a committed migration.
        literal = json.dumps(records, ensure_ascii=False).replace("'", "''")
        sql = MIGRATION.read_text(encoding="utf-8")
        sql = sql.replace("commit;", "")
        sql += f"\nselect public.import_member_roster('{literal}'::jsonb);\ncommit;\n"
        target = DATA_DIR / "apply-roster.sql"
        target.write_text(sql, encoding="utf-8")
        print(f"Private schema + roster SQL saved to {target}. Run once in Supabase SQL Editor.")
    if args.apply:
        client = create_task_client()
        try:
            result = client.rpc("import_member_roster", {"records": records}).execute()
            print(f"Imported {result.data} roster records. No invitations were sent.")
        finally:
            client.postgrest.session.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, APIError, HTTPError, StorageUnavailable) as exc:
        # Do not include contacts or provider request bodies in terminal output.
        print(f"Roster import failed ({type(exc).__name__}). Check file format and migration setup.")
        raise SystemExit(1)
