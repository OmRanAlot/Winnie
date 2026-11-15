"""Administrator-only live tracker previews, reviewed applies and last successful sync."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import require_admin
from app.core.settings import Settings
from app.integrations.google_sheets import SheetsUnavailable
from app.integrations.supabase import StorageUnavailable
from app.schemas.api import failure
from app.schemas.sheets import SyncRequest
from app.services.sheet_sync import SheetSyncService
from app.services.tracker_sync import ImportConflict

router = APIRouter(prefix='/api/sheet-sync', tags=['sheet-sync'], dependencies=[Depends(require_admin)])


def get_sync_service():
    return SheetSyncService(Settings())


Service = Annotated[SheetSyncService, Depends(get_sync_service)]


def result(operation):
    try:
        return {'success': True, 'data': operation()}
    except ImportConflict as exc:
        return failure(str(exc), 409)
    except SheetsUnavailable as exc:
        return failure(str(exc), 503)
    except StorageUnavailable:
        return failure('Sync storage is unavailable. Check Supabase and the Google Sheets sync migration.', 503)
    except ValueError:
        return failure('Tracker format is invalid. Check the supported columns, dates and task IDs.', 422)


@router.get('/sources')
def sources(service: Service):
    def read():
        return [{**s.model_dump(), 'last_run': service.store.last_run(s.key)}
                for s in service.settings.sheet_sync_sources]
    return result(read)


@router.post('/{source_key}/preview')
def preview(source_key: str, body: SyncRequest, service: Service):
    return result(lambda: service.preview(source_key, body.resolutions))


@router.post('/{source_key}/apply')
def apply(source_key: str, body: SyncRequest, service: Service):
    if not body.expected_plan:
        raise HTTPException(422, 'Build a preview and provide expected_plan.')
    return result(lambda: service.apply(source_key, body.expected_plan, body.resolutions))
