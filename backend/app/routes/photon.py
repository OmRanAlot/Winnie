"""Signed Photon webhook -> durable inbox -> on-demand Cloud Task -> existing message flow."""
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.core.auth import require_member
from app.core.settings import Settings
from app.integrations.help_requests import HelpRequestStore
from app.integrations.photon import (
    MAX_WEBHOOK_BYTES,
    PhotonInbox,
    PhotonQueue,
    PhotonSender,
    PhotonUnavailable,
    normalize_payload,
    verify_signature,
)
from app.integrations.reminders import ReminderStore
from app.integrations.supabase import StorageUnavailable
from app.routes.messages import (
    IncomingMessage,
    get_completion_store,
    get_help_request_store,
    get_member_store,
    get_message_interpreter,
    get_reassignment_store,
    get_task_store,
    process_message,
)
from app.routes.reminders import authorize_reminder_bridge
from app.services.members import MemberStore
from app.services.reminders import next_reminder, utc_now
from app.services.tasks import TaskStore

router = APIRouter(prefix='/api/photon', tags=['photon'])


def get_inbox():
    return PhotonInbox()


def get_queue():
    return PhotonQueue(Settings())


def get_sender():
    return PhotonSender(Settings())


Inbox = Annotated[PhotonInbox, Depends(get_inbox)]
Queue = Annotated[PhotonQueue, Depends(get_queue)]
Sender = Annotated[PhotonSender, Depends(get_sender)]
Members = Annotated[object, Depends(get_member_store)]
Tasks = Annotated[object, Depends(get_task_store)]
Completions = Annotated[object, Depends(get_completion_store)]
Interpreter = Annotated[object, Depends(get_message_interpreter)]
HelpRequests = Annotated[object, Depends(get_help_request_store)]
Reassignments = Annotated[object, Depends(get_reassignment_store)]


@router.get('/webhook')
def webhook_status():
    s = Settings()
    return {'integration': 'winnie-photon-spectrum', 'enabled': s.photon_enabled,
        'conversation_memory_enabled': s.message_memory_enabled, 'conversation_protocol': 2,
        'request_action_protocol': 1, 'message_ai_enabled': s.message_ai_enabled,
        'help_workflow_enabled': s.help_workflow_enabled,
        'configured': bool(s.photon_webhook_secret.get_secret_value() and s.photon_webhook_id
            and s.photon_queue and s.photon_task_url and s.photon_project_id and s.photon_project_secret.get_secret_value())}


@router.post('/webhook')
async def webhook(request: Request, inbox: Inbox, queue: Queue):
    s = Settings()
    if not s.photon_enabled:
        raise HTTPException(503, 'Photon webhook is disabled.')
    if not webhook_status()['configured']:
        raise HTTPException(503, 'Photon webhook setup is incomplete.')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WEBHOOK_BYTES:
            raise HTTPException(413, 'Webhook is too large.')
    try:
        if not verify_signature(bytes(body), request.headers, s):
            raise HTTPException(401, 'Invalid Photon signature.')
        data = json.loads(body)
        if not isinstance(data, dict):
            raise TypeError('Invalid event')
        if request.headers.get('x-spectrum-event') != data.get('event'):
            raise ValueError('Event mismatch')
        payload = normalize_payload(data)
        if payload is None:
            return {'accepted': True, 'ignored': True}
        item = await run_in_threadpool(inbox.put, s.photon_webhook_id, payload)
        await run_in_threadpool(queue.enqueue, item)
        return {'accepted': True}
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, 'Invalid Photon event.') from exc
    except (StorageUnavailable, PhotonUnavailable) as exc:
        raise HTTPException(503, 'Photon queue is unavailable. Check server configuration.') from exc


async def dispatch_notifications(sender):
    store = HelpRequestStore()
    settings = Settings()
    # Two request-scoped sends stay below the Cloud Task's 120-second dispatch budget.
    for _ in range(2):
        notice = (await run_in_threadpool(store.rpc, 'claim_reassignment_notification')
                  if Settings().help_workflow_enabled else None)
        finish = 'finish_reassignment_notification'
        if not notice:
            notice = await run_in_threadpool(store.rpc, 'claim_event_plan_notification')
            finish = 'finish_event_plan_notification'
        if not notice and settings.notifications_enabled:
            notice = await run_in_threadpool(store.rpc, 'claim_task_notification',
                p_semester=settings.active_semester, p_timezone=settings.reminder_timezone)
            finish = 'finish_task_notification'
        reminder_store = None
        local_hour = datetime.now(ZoneInfo(settings.reminder_timezone)).hour
        if not notice and settings.reminders_enabled and 9 <= local_hour < 20:
            reminder_store = ReminderStore()
            result = await run_in_threadpool(next_reminder, reminder_store, TaskStore(), MemberStore(), settings, scan=False)
            delivery = result.get('delivery')
            if delivery:
                notice = {'id': delivery['id'], 'claim_token': delivery['claim_token'],
                    'text': delivery['text'], 'recipient': delivery['recipient']}
        if not notice:
            return False
        try:
            provider = await sender.send(notice['text'], str(notice['id']), recipient=notice['recipient'])
            outcome = 'sent'
        except PhotonUnavailable:
            provider, outcome = None, 'uncertain'
        if reminder_store:
            await run_in_threadpool(reminder_store.finish, notice['id'], notice['claim_token'], outcome, provider, utc_now())
        else:
            await run_in_threadpool(store.rpc, finish, p_id=notice['id'],
                p_token=notice['claim_token'], p_outcome=outcome, p_provider_id=provider)
    return True


class Work(BaseModel):
    item_id: UUID | None = None


@router.post('/work', dependencies=[Depends(authorize_reminder_bridge)])
async def work(body: Work, inbox: Inbox, sender: Sender, queue: Queue,
    members: Members, tasks: Tasks, completions: Completions, interpreter: Interpreter,
    help_requests: HelpRequests, reassignments: Reassignments):
    s = Settings()
    if not s.photon_enabled:
        raise HTTPException(503, 'Photon webhook is disabled.')
    try:
        if body.item_id:
            item, token = str(body.item_id), str(uuid4())
            job = await run_in_threadpool(inbox.rpc, 'photon_inbox_claim', p_id=item, p_token=token)
            if job.get('busy'):
                raise HTTPException(503, 'Message is already being processed.')
            if not job.get('done'):
                payload = job['payload']
                reply = job.get('reply')
                if reply is None:
                    message = IncomingMessage(**{k: v for k, v in payload.items() if k != 'phone'})
                    result = await process_message(message, members, tasks, completions, interpreter, help_requests, reassignments, s)
                    reply = result['reply']
                    saved = await run_in_threadpool(inbox.rpc, 'photon_inbox_advance', p_id=item, p_token=token,
                        p_state='ignored' if reply is None else 'ready', p_reply=reply)
                    if not saved:
                        raise HTTPException(503, 'Message claim changed.')
                if reply is not None:
                    saved = await run_in_threadpool(inbox.rpc, 'photon_inbox_advance', p_id=item, p_token=token, p_state='sending')
                    if not saved:
                        raise HTTPException(503, 'Message claim changed.')
                    try:
                        provider = await sender.send(reply, item, space_id=payload['space_id'], phone=payload.get('phone'))
                        state = 'sent'
                    except PhotonUnavailable:
                        provider, state = None, 'uncertain'
                    await run_in_threadpool(inbox.rpc, 'photon_inbox_advance', p_id=item, p_token=token, p_state=state, p_provider=provider)
        if body.item_id:
            # Separate inbound interpretation/reply time from the outbound notification batch.
            await run_in_threadpool(queue.enqueue, None, str(uuid4()))
            return {'processed': True}
        remaining = await dispatch_notifications(sender)
        if remaining:
            await run_in_threadpool(queue.enqueue, None, str(uuid4()))
        return {'processed': True}
    except (StorageUnavailable, PhotonUnavailable) as exc:
        raise HTTPException(503, 'Photon processing is temporarily unavailable.') from exc


@router.post('/dispatch', dependencies=[Depends(require_member)])
async def dispatch(queue: Queue):
    if not Settings().photon_enabled:
        return {'success': True, 'data': {'queued': False}}
    try:
        await run_in_threadpool(queue.enqueue)
        return {'success': True, 'data': {'queued': True}}
    except PhotonUnavailable as exc:
        raise HTTPException(503, 'Request saved, but notification dispatch needs server configuration.') from exc
