"""Verified Photon commands share the browser's consent-based reassignment queue."""
import re

from fastapi.concurrency import run_in_threadpool
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable, create_task_client
from app.services.members import normalize_sender

RESPONSE = re.compile(r'(accept|deny|approve|reject)\s+REQ-(\d+)', re.IGNORECASE)
PROPOSE = re.compile(r'(?:reassign|transfer)\s+(WIN-\d{6}-\d+)\s+to\s+([A-Z][A-Z0-9_-]{0,49})', re.IGNORECASE)


class MessagingReassignmentStore:
    def act(self, message, action, payload):
        client = None
        try:
            client = create_task_client()
            return client.rpc('messaging_reassignment', {
                'p_platform': message.platform, 'p_sender_id': normalize_sender(message.sender_id),
                'p_message_id': message.message_id, 'p_action': action, 'p_payload': payload,
            }).execute().data
        except APIError as exc:
            if exc.code == 'P0001':
                raise ValueError(exc.message) from exc
            raise StorageUnavailable('Reassignment storage unavailable. Check the unified workflow migration.') from exc
        except HTTPError as exc:
            raise StorageUnavailable('Reassignment storage unavailable.') from exc
        finally:
            if client is not None:
                client.postgrest.session.close()


def response_text(result):
    code = f"REQ-{result['request_no']}"
    if result['status'] == 'approved':
        return f'{code} approved. Ownership transferred after recipient acceptance and admin approval.'
    if result['status'] in ('declined', 'rejected'):
        return f'{code} denied. Ownership is unchanged.'
    if result['recipient_decision'] == 'accepted':
        return f'{code} accepted. Awaiting admin approval; ownership is unchanged.'
    return f'{code} saved. The recipient must accept first, then an admin can approve. Open Requests to follow its status.'


async def reassignment_reply(message, members, tasks, store, settings):
    text = message.text.strip()
    response, proposal = RESPONSE.fullmatch(text), PROPOSE.fullmatch(text)
    listing = text.lower() in ('requests', 'my requests', 'incoming requests')
    if not response and not proposal and not listing:
        return None
    if not settings.help_workflow_enabled:
        return 'The reassignment workflow is disabled. Contact the project admin.'
    if message.conversation_type != 'dm' or message.platform != 'imessage' or not message.sender_id:
        return 'Use a direct message from your linked iMessage account.'
    if not message.message_id:
        return 'Restart the updated Photon listener before responding to requests.'
    member = await run_in_threadpool(members.resolve, message.platform, normalize_sender(message.sender_id))
    if not member:
        return 'Your messaging account is not linked. Text whoami for setup details.'
    try:
        if listing:
            result = await run_in_threadpool(store.act, message, 'list', {})
            if not result['requests']:
                return 'No pending reassignment requests for your account.'
            lines = ['Pending requests (also visible under Requests in Winnie):']
            for row in result['requests']:
                action = 'awaiting admin approval' if row['recipient_decision'] == 'accepted' else 'awaiting recipient'
                if row['incoming'] and row['recipient_decision'] == 'pending':
                    action = f"text accept REQ-{row['request_no']} / deny REQ-{row['request_no']}"
                lines.append(f"REQ-{row['request_no']}: {row['title'][:100]} ({row['task_code']}) — {action}")
            return '\n'.join(lines)
        if response:
            action, number = response.groups()
            result = await run_in_threadpool(store.act, message,
                {'accept': 'accepted', 'deny': 'denied', 'approve': 'approved', 'reject': 'rejected'}[action.lower()],
                {'request_no': int(number)})
        else:
            task_code, proposed = proposal.groups()
            task = await run_in_threadpool(tasks.by_task_code, task_code.upper(), settings.active_semester)
            if not task:
                return 'Task not found in the active semester. Text tasks to check its code.'
            result = await run_in_threadpool(store.act, message, 'submit', {
                'task_id': str(task['id']), 'semester': settings.active_semester,
                'proposed_code': proposed.upper(), 'reason': 'Requested through Photon',
            })
        return response_text(result)
    except ValueError as exc:
        return str(exc)
