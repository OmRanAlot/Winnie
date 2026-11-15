"""Three-way tracker merge: incoming cells, last synced cells and current Winnie tasks."""
import hashlib
import json
from types import SimpleNamespace

from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.google_sheets import GoogleSheetsReader
from app.integrations.supabase import StorageUnavailable, create_task_client
from app.services.members import MemberStore
from app.services.tasks import TaskStore
from app.services.tracker_import import TrackerContext, preview_tracker
from app.services.tracker_sync import SHEET_FIELDS, ImportConflict, plan_import


class SheetSyncStore(MemberStore):
    def baselines(self, spreadsheet_id):
        rows, offset = [], 0
        while True:
            page = self._execute('sheet_sync_state', lambda q, offset=offset: q.select('*').eq(
                'spreadsheet_id', spreadsheet_id,
            ).order('source_task_id').range(offset, offset + 499)).data
            rows.extend(page)
            if len(page) < 500:
                return {r['source_task_id']: r for r in rows}
            offset += 500

    def last_run(self, source_key):
        rows = self._execute('sheet_sync_runs', lambda q: q.select(
            'created_at,summary'
        ).eq('source_key', source_key).order('created_at', desc=True).limit(1)).data
        return rows[0] if rows else None

    def apply(self, plan):
        client = None
        try:
            client = self.client_factory()
            return client.rpc('apply_sheet_sync', {'plan': plan}).execute().data
        except APIError as exc:
            if exc.code in ('40001', '23505', 'P0002'):
                raise ImportConflict('Tasks or sync state changed. Build a fresh preview before applying.') from exc
            raise StorageUnavailable('Sheet sync storage is unavailable. Check the sync migration.') from exc
        except HTTPError as exc:
            raise StorageUnavailable('Sheet sync storage is unavailable. Preview again to check whether the transaction completed.') from exc
        finally:
            if client is not None:
                client.postgrest.session.close()


def merge_plan(preview, tasks, baselines, target, source_key, resolutions=None):
    """Pure planning; an unresolved concurrent edit prevents the entire batch from writing."""
    resolutions = resolutions or {}
    spreadsheet_id = preview['rows'][0]['task']['source_spreadsheet_id'] if preview['rows'] else ''
    existing = tasks.tracker_tasks(spreadsheet_id)
    if any(not t.get('source_task_id') for t in existing):
        raise ImportConflict('Existing workbook tasks are missing source IDs. Reconcile their permanent IDs before syncing.')
    validated = plan_import(preview, SimpleNamespace(tracker_tasks=lambda _: existing), target)
    current = {t['source_task_id']: t for t in existing}
    incoming = {row['task']['source_task_id']: row['task'] for row in preview['rows']}
    conflicts, preserved, operations = [], [], []
    for op in validated['operations']:
        key = op['source_task_id']
        task = incoming[key]
        baseline = baselines.get(key)
        old = current.get(key)
        # plan_import already validates identity, semester and monthly snapshot ordering.
        if old is None:
            operations.append({**op, 'source_values': {f: task[f] for f in SHEET_FIELDS},
                               'expected_state_version': baseline['version'] if baseline else None})
            continue
        values = {}
        for field in SHEET_FIELDS:
            new, local = task[field], old.get(field)
            if field == 'source_tab_id' and new is None:
                continue
            if new == local:
                continue
            if field in ('source_tab_id', 'source_tab_name', 'snapshot_month'):
                values[field] = new
                continue
            base = baseline['source_values'].get(field) if baseline else None
            if baseline and new == base:
                preserved.append({'source_task_id': key, 'field': field})
                continue
            if baseline and local == base:
                values[field] = new
                continue
            # With no baseline, differences may be local edits made since the CSV import.
            resolution = resolutions.get(f'{key}:{field}')
            if resolution == 'sheet':
                values[field] = new
            elif resolution == 'winnie':
                preserved.append({'source_task_id': key, 'field': field})
            else:
                conflicts.append({'key': f'{key}:{field}', 'source_task_id': key, 'field': field,
                                  'winnie': local, 'sheet': new})
        operations.append({
            'action': 'update' if values else 'unchanged', 'source_task_id': key,
            'id': old['id'], 'expected_updated_at': old['updated_at'], 'values': values,
            'before': {f: old.get(f) for f in values},
            'source_values': {f: task[f] for f in SHEET_FIELDS},
            'expected_state_version': baseline['version'] if baseline else None,
        })
    plan = {**validated, 'source_key': source_key, 'operations': operations, 'conflicts': conflicts,
            'snapshot_month': preview['snapshot_month'],
            'project_name': next(iter(incoming.values()))['project_name'],
            'preserved': preserved, 'missing_from_sheet': sorted(set(current) - set(incoming)),
            'summary': {action: sum(op['action'] == action for op in operations)
                        for action in ('insert', 'update', 'unchanged')}}
    plan.pop('plan_id', None)
    plan['plan_id'] = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return plan


class SheetSyncService:
    def __init__(self, settings, reader=None, tasks=None, store=None):
        self.settings = settings
        self.reader = reader or GoogleSheetsReader(settings)
        self.tasks = tasks or TaskStore()
        self.store = store or SheetSyncStore(create_task_client)

    def source(self, key):
        matches = [s for s in self.settings.sheet_sync_sources if s.key == key]
        if len(matches) != 1:
            raise ImportConflict('Sync source is missing or duplicated in server configuration.')
        return matches[0]

    def preview(self, key, resolutions=None):
        source = self.source(key)
        snapshot = self.reader.read(source)
        context = TrackerContext(
            semester_code=source.semester_code, spreadsheet_id=source.spreadsheet_id,
            tab_name=snapshot.tab_name, tab_id=snapshot.tab_id,
            project_name=source.project_name, initial_month=source.initial_month,
        )
        preview = preview_tracker(snapshot.text, context)
        if preview['summary']['rows_with_errors']:
            errors = ', '.join(sorted(preview['summary']['errors']))
            raise ImportConflict(f'Fix the tracker before syncing: {errors}. Each task needs a unique Winnie Task ID.')
        return merge_plan(preview, self.tasks, self.store.baselines(source.spreadsheet_id),
                          self.settings.supabase_url or '', key, resolutions)

    def apply(self, key, expected_plan, resolutions=None):
        # Re-read Google AND Supabase; no browser-provided plan data is trusted.
        plan = self.preview(key, resolutions)
        if not expected_plan or plan['plan_id'] != expected_plan:
            raise ImportConflict('The preview changed. Review a fresh preview before applying.')
        if plan['conflicts']:
            raise ImportConflict('Resolve every conflicting field before applying.')
        return self.store.apply(plan)
