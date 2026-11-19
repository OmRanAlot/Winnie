"""Poll configured Google trackers outside the API process; default invocation only previews."""
import argparse
import json
import logging
import time

from app.core.settings import Settings
from app.integrations.google_sheets import SheetsUnavailable
from app.integrations.supabase import StorageUnavailable
from app.services.sheet_sync import SheetSyncService
from app.services.tracker_sync import ImportConflict

logger = logging.getLogger(__name__)


def cycle(service, *, apply=False, source_key=None):
    results = []
    sources = service.settings.sheet_sync_sources
    if source_key:
        sources = [service.source(source_key)]
    for source in sources:
        try:
            plan = service.preview(source.key)
            report = {'source': source.key, 'mode': 'preview', 'plan_id': plan['plan_id'],
                      'summary': plan['summary'], 'conflicts': len(plan['conflicts']),
                      'preserved_fields': len(plan['preserved'])}
            if plan['conflicts']:
                report['mode'] = 'conflict'
            elif apply and source.auto_apply:
                report['summary'] = service.apply(source.key, plan['plan_id'])
                report['mode'] = 'applied'
            results.append(report)
        except (ImportConflict, SheetsUnavailable, StorageUnavailable, ValueError) as exc:
            # No provider responses, cell values, credentials or contacts in worker logs.
            logger.warning("Sheet sync failed source=%s reason=%s", source.key,
                           str(exc) if isinstance(exc, SheetsUnavailable) else type(exc).__name__)
            results.append({'source': source.key, 'mode': 'failed',
                            'message': 'Sync failed. Check the admin preview for details.'})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source')
    parser.add_argument('--apply', action='store_true', help='Write only sources with auto_apply=true')
    parser.add_argument('--watch', action='store_true', help='Poll until stopped; run one worker')
    args = parser.parse_args()
    settings = Settings()
    if not settings.sheet_sync_sources:
        parser.error('Configure WINNIE_SHEET_SYNC_SOURCES first.')
    service = SheetSyncService(settings)
    if args.source:
        service.source(args.source)
    while True:
        results = cycle(service, apply=args.apply, source_key=args.source)
        print(json.dumps(results), flush=True)
        if not args.watch:
            return 1 if any(r['mode'] in ('failed', 'conflict') for r in results) else 0
        time.sleep(settings.sheet_sync_interval_seconds)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
