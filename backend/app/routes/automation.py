"""OIDC-authenticated Cloud Scheduler scans and administrator notification actions."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from app.cli.sync_sheets import cycle
from app.core.auth import Principal, require_admin
from app.core.settings import Settings
from app.integrations.photon import PhotonQueue, PhotonUnavailable
from app.integrations.reminders import ReminderStore
from app.integrations.supabase import StorageUnavailable
from app.schemas.api import failure
from app.services.automation import AutomationStore
from app.services.members import MemberStore
from app.services.reminders import scan_reminders, utc_now
from app.services.sheet_sync import SheetSyncService
from app.services.tasks import TaskStore

router = APIRouter(tags=['automation'])
Admin = Annotated[Principal, Depends(require_admin)]


def authorize_scheduler(authorization: str = Header(default='')):
    s = Settings()
    if not s.scheduler_service_account or not s.scheduler_audience:
        raise HTTPException(503, 'Scheduled automation is not configured.')
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 16384:
        raise HTTPException(401, 'A scheduler identity token is required.')
    try:
        claims = id_token.verify_oauth2_token(token, GoogleRequest(), audience=s.scheduler_audience)
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(401, 'Invalid scheduler identity.') from exc
    if claims.get('email') != s.scheduler_service_account or claims.get('email_verified') is not True:
        raise HTTPException(403, 'Scheduler identity is not authorized.')


def get_automation_store():
    return AutomationStore()


def get_sync_service():
    return SheetSyncService(Settings())


def get_notification_queue():
    return PhotonQueue(Settings())


Store = Annotated[AutomationStore, Depends(get_automation_store)]
Queue = Annotated[PhotonQueue, Depends(get_notification_queue)]
Sheets = Annotated[SheetSyncService, Depends(get_sync_service)]


def kick(queue):
    try:
        queue.enqueue()
        return None
    except PhotonUnavailable:
        return 'Saved in the outbox. Text dispatch could not be queued; retry from Requests.'


@router.post('/api/notifications/tasks/{task_id}/nudge')
def nudge(task_id: UUID, admin: Admin, store: Store, queue: Queue):
    s = Settings()
    if admin.service:
        raise HTTPException(403, 'Use a signed-in administrator account to request a nudge.')
    if not s.notifications_enabled or not s.photon_enabled:
        raise HTTPException(503, 'Cloud notification delivery is not enabled.')
    try:
        data = store.rpc('nudge_task', p_actor=admin.user_id, p_task=str(task_id), p_semester=s.active_semester)
        data['notification_warning'] = kick(queue)
        return {'success': True, 'data': data}
    except StorageUnavailable:
        return failure('Notification storage is unavailable. Check the automation migration.', 503)


@router.get('/api/automation/status')
def status(admin: Admin, store: Store):
    try:
        s = Settings()
        return {'success': True, 'data': {**store.status(), 'reminders_enabled': s.reminders_enabled,
                'notifications_enabled': s.notifications_enabled, 'photon_enabled': s.photon_enabled,
                'scheduler_configured': bool(s.scheduler_service_account and s.scheduler_audience)}}
    except StorageUnavailable:
        return failure('Automation status is unavailable. Check the automation migration.', 503)


@router.post('/api/internal/automation/reminders', dependencies=[Depends(authorize_scheduler)])
def scheduled_reminders(store: Store, queue: Queue):
    s = Settings()
    key, summary = 'reminders', {}
    try:
        token = store.claim(key)
        if not token:
            raise HTTPException(409, 'Another reminder scan is running.')
        try:
            if s.reminders_enabled:
                summary['deadlines'] = scan_reminders(ReminderStore(), TaskStore(), MemberStore(), s, utc_now(), write=True)
            if s.notifications_enabled:
                summary['tasks'] = store.rpc('scan_task_notifications', p_semester=s.active_semester,
                    p_timezone=s.reminder_timezone, p_overdue=s.reminders_enabled)
            # Also recover plan/reassignment notices whose browser dispatch kick failed.
            if s.photon_enabled:
                warning = kick(queue)
                if warning:
                    raise PhotonUnavailable(warning)
            store.finish(key, token, 'succeeded', summary)
            return {'success': True, 'data': summary}
        except (StorageUnavailable, PhotonUnavailable, ValueError):
            store.finish(key, token, 'failed', {'message': 'Scan failed; check server configuration.'})
            raise HTTPException(503, 'Reminder scan failed; queued notices are retained.') from None
    except StorageUnavailable:
        raise HTTPException(503, 'Automation storage is unavailable.') from None


@router.post('/api/internal/automation/sheets', dependencies=[Depends(authorize_scheduler)])
def scheduled_sheets(store: Store, service: Sheets):
    reports, failed = [], False
    try:
        for source in service.settings.sheet_sync_sources:
            if not source.auto_apply:
                continue
            key = f'sheets:{source.key}'
            token = store.claim(key)
            if not token:
                failed = True
                continue
            report = cycle(service, apply=True, source_key=source.key)[0]
            outcome = 'conflict' if report['mode'] == 'conflict' else 'failed' if report['mode'] == 'failed' else 'succeeded'
            store.finish(key, token, outcome, report)
            reports.append(report)
            failed |= outcome == 'failed'
        if failed:
            raise HTTPException(503, 'Some tracker jobs failed or are busy. Check automation status.')
        return {'success': True, 'data': reports}
    except StorageUnavailable:
        raise HTTPException(503, 'Automation storage is unavailable.') from None
