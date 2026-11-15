"""Preview or atomically import an attendance CSV. Requires the attendance migration and roster."""
import argparse
import json
from pathlib import Path

from app.integrations.supabase import create_task_client
from app.services.attendance_import import parse_attendance
from app.services.members import MemberStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--semester', required=True)
    parser.add_argument('--mapping', type=Path, help='JSON object mapping CSV headers to verified member codes')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--apply', action='store_true')
    action.add_argument('--prepare-sql', type=Path, help='Write a private, transactional SQL import')
    args = parser.parse_args()
    store = MemberStore()
    mapping = json.loads(args.mapping.read_text(encoding='utf-8-sig')) if args.mapping else None
    records = parse_attendance(args.path, args.year, store.list_active(), store.aliases(args.semester), mapping)
    print(json.dumps({'meetings': len(records), 'attendance_marks': sum(len(r['attendees']) for r in records),
                      'dates': [r['held_at'][:10] for r in records]}, indent=2))
    if args.prepare_sql:
        literal = json.dumps(records, ensure_ascii=False).replace("'", "''")
        args.prepare_sql.write_text(
            "-- Apply the meeting attendance migration first. Existing recorded attendance is preserved.\n"
            f"begin;\nselect public.import_meeting_attendance('{literal}'::jsonb);\ncommit;\n",
            encoding='utf-8',
        )
        print(f'Private attendance import saved to {args.prepare_sql}.')
    if args.apply:
        client = create_task_client()
        try:
            result = client.rpc('import_meeting_attendance', {'records': records}).execute()
            print(f'Imported {result.data} meetings. Previously recorded meetings were preserved.')
        finally:
            client.postgrest.session.close()


if __name__ == '__main__':
    main()
