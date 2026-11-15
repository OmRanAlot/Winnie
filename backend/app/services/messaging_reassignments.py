"""Verified Photon commands share the browser's consent-based reassignment queue."""
import re

from fastapi.concurrency import run_in_threadpool
from httpx import HTTPError
from postgrest.exceptions import APIError
from pydantic import ValidationError

from app.agents.message_interpreter import InterpretationUnavailable
from app.agents.request_interpreter import RequestDecision
from app.integrations.supabase import StorageUnavailable, create_task_client
from app.services.members import normalize_sender, resolve_member_choice

RESPONSE = re.compile(r'(accept|deny|approve|reject)\s+REQ-(\d+)', re.IGNORECASE)
PROPOSE = re.compile(r'(?:reassign|transfer)\s+(WIN-\d{6}-\d+)\s+to\s+(.+)', re.IGNORECASE)
ACTION = re.compile(r'\b(approve|reject|accept|deny|decline|approval|rejection)\b|turn (?:it|that|this|the request) down', re.IGNORECASE)
SIMPLE = re.compile(r"(?:please\s+)?(?:i\s+)?(approve|reject|accept|deny|decline)(?:\s+(?:it|that|this|that request|this request|the request|that transfer))?(?:\s+please)?[.! ]*", re.IGNORECASE)
NUMBERED_ACTION = re.compile(r'(approve|reject|accept|deny|decline)\s+(?:option\s+)?(\d+)[.! ]*', re.IGNORECASE)
UNSAFE = re.compile(r"\b(don't|do not|not|never|can't|cannot|didn't|if|whether|maybe)\b|^\s*(why|how|what|should i|can i|did i)\b|\bi (will|might|would)\b", re.IGNORECASE)


def decision_action(row, verb):
    if verb == 'approve' and row.get('can_review'):
        return 'approved'
    if verb == 'accept' and row.get('can_respond'):
        return 'accepted'
    if verb in ('reject', 'deny', 'decline'):
        if row.get('can_review'):
            return 'rejected'
        if row.get('can_respond'):
            return 'denied'
    return None


def request_list(rows, prefix='Which transfer request do you mean?'):
    lines = [prefix]
    for number, row in enumerate(rows[:30], 1):
        stage = 'awaiting your admin review' if row.get('can_review') else 'awaiting your consent' if row.get('can_respond') else 'awaiting another person'
        people = f" ({row.get('requester_name', 'current owner')} → {row.get('recipient_name', 'proposed recipient')})"
        lines.append(f"{number}. {row['title']}{people} — {stage}.")
    lines.append('Reply with the task name or a list number. You do not need a member code.')
    return '\n'.join(lines)


async def natural_request_reply(message, store, settings, interpreter, context, listing=False):
    text = message.text.strip()
    simple = SIMPLE.fullmatch(text)
    numbered = NUMBERED_ACTION.fullmatch(text)
    pending = getattr(context, 'pending_request_action', None)
    if text.casefold() in ('tasks', 'my tasks', 'whoami', 'menu', 'help', 'start'):
        if context is not None:
            context.request_focus()
        return None
    if not listing and not simple and not numbered and not ACTION.search(text) and not pending and not (text.isdigit() and getattr(context, 'request_choices', [])):
        return None
    snapshot = await run_in_threadpool(store.pending, message)
    rows = snapshot['requests']
    if listing:
        if context is not None:
            context.reset_question()
            context.request_focus(choices=[r['request_no'] for r in rows])
        return request_list(rows, 'Here are your pending transfers:') + '\nTo act on the list, say “reject 1” or name the task and decision.' if rows else 'You have no pending transfers right now.'
    verb = simple[1].lower() if simple else numbered[1].lower() if numbered else pending if not ACTION.search(text) else None
    eligible = [r for r in rows if decision_action(r, verb)] if verb else [r for r in rows if r.get('can_review') or r.get('can_respond')]
    chosen, action = None, None
    choices = getattr(context, 'request_choices', [])
    number = text.strip().rstrip('.! ')
    if (pending and number.isdigit()) or numbered or (number.isdigit() and choices):
        index = int(numbered[2] if numbered else number) - 1
        selected = choices[index] if 0 <= index < len(choices) else None
        chosen = next((r for r in eligible if r['request_no'] == selected), None)
        if chosen is None:
            return 'That list choice is no longer actionable. Ask for pending requests to refresh the list.'
        if verb is None:
            if context is not None:
                context.request_focus(chosen['request_no'])
            return f'For “{chosen["title"]}”, say approve or reject.' if chosen.get('can_review') else f'For “{chosen["title"]}”, say accept or deny.'
    elif pending and not ACTION.search(text):
        named = [r for r in eligible if text.casefold().rstrip('.! ') == r['title'].casefold()]
        chosen = named[0] if len(named) == 1 else None
    elif simple:
        focus = getattr(context, 'focus_request_no', None)
        if focus is not None:
            chosen = next((r for r in eligible if r['request_no'] == focus), None)
            if chosen is None:
                return 'The transfer we were discussing is no longer awaiting that decision. Ask for pending requests to select another.'
        elif len(eligible) == 1:
            chosen = eligible[0]
    if chosen is not None:
        action = decision_action(chosen, verb)
    elif not simple and getattr(settings, 'message_ai_enabled', False) and interpreter is not None and hasattr(interpreter, 'interpret_request') and not UNSAFE.search(text):
        try:
            decision = RequestDecision.model_validate(await run_in_threadpool(interpreter.interpret_request,
                text, eligible[:60], history=getattr(context, 'history', []),
                focus_request_no=getattr(context, 'focus_request_no', None)))
            verbs = {'approved': 'approve', 'rejected': 'reject', 'accepted': 'accept', 'denied': 'deny'}
            proposed = next((r for r in eligible if r['request_no'] == decision.request_no), None)
            evidence = decision.evidence_quote.strip()
            if (decision.execute and decision.confidence >= .9 and proposed and evidence and evidence in text
                    and ACTION.search(evidence) and decision.action in verbs
                    and decision_action(proposed, verbs[decision.action]) == decision.action):
                chosen, action = proposed, decision.action
        except (InterpretationUnavailable, ValidationError):
            pass
    if chosen is None or action is None:
        if not eligible:
            return 'There is no pending transfer you can make that decision on right now. Admin review comes first; only the recipient can consent afterward.'
        if context is not None:
            context.reset_question()
            context.request_focus(choices=[r['request_no'] for r in eligible], action=verb)
        return request_list(eligible)
    # Actor, role, stage and current assignment are independently verified by the SQL RPC.
    result = await run_in_threadpool(store.act, message, action, {'request_no': chosen['request_no']})
    if context is not None:
        context.reset_question()
        context.request_focus(chosen['request_no'])
    title = chosen['title']
    if result['status'] == 'approved':
        return f'Accepted the transfer of “{title}”. Ownership has changed, and the outgoing owner remains in the transfer history.'
    if result['status'] in ('rejected', 'declined'):
        return f'Rejected the transfer of “{title}”. The task stays with its current owner.'
    if result.get('admin_decision') == 'approved':
        return f'Approved the proposed transfer of “{title}”. The recipient will now be asked for consent; ownership is unchanged until they accept.'
    return 'Your decision was recorded. Ask for pending requests to check its current stage.'


class MessagingReassignmentStore:
    def pending(self, message):
        client = create_task_client()
        try:
            return client.rpc('messaging_request_context', {'p_platform': message.platform,
                'p_sender_id': normalize_sender(message.sender_id)}).execute().data
        except APIError as exc:
            if exc.code == 'P0001':
                raise ValueError(exc.message) from exc
            raise StorageUnavailable('Request context is unavailable. Apply the conversational-request migration.') from exc
        except HTTPError as exc:
            raise StorageUnavailable('Request context is unavailable.') from exc
        finally:
            client.postgrest.session.close()

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
        return f'{code} completed. Ownership transferred after admin approval and recipient consent; the outgoing owner is recorded in transfer history.'
    if result['status'] in ('declined', 'rejected'):
        return f'{code} denied. Ownership is unchanged.'
    if result.get('admin_decision') == 'approved':
        return f'{code}: admin approved. The recipient will now be asked to accept or deny. Ownership is unchanged until acceptance.'
    return f'{code} saved for admin review first. If approved, the recipient will be asked to consent. Open Requests to follow its status.'


async def reassignment_reply(message, members, tasks, store, settings, interpreter=None, context=None):
    text = message.text.strip()
    response, proposal = RESPONSE.fullmatch(text), PROPOSE.fullmatch(text)
    listing = text.lower().rstrip('?! .') in ('requests', 'my requests', 'incoming requests', 'pending requests', 'show my requests', 'show pending requests', 'what requests are pending')
    conversational = bool(ACTION.search(text) or getattr(context, 'pending_request_action', None) or (text.isdigit() and getattr(context, 'request_choices', [])))
    if not response and not proposal and not listing and not conversational:
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
        if not response and not proposal:
            return await natural_request_reply(message, store, settings, interpreter, context, listing)
        if response:
            action, number = response.groups()
            result = await run_in_threadpool(store.act, message,
                {'accept': 'accepted', 'deny': 'denied', 'approve': 'approved', 'reject': 'rejected'}[action.lower()],
                {'request_no': int(number)})
            if context is not None:
                context.reset_question()
                context.request_focus(int(number))
        else:
            task_code, proposed = proposal.groups()
            task = await run_in_threadpool(tasks.by_task_code, task_code.upper(), settings.active_semester)
            if not task:
                return 'Task not found in the active semester. Text tasks to check its code.'
            people = await run_in_threadpool(members.list_active)
            if proposed.strip().lstrip('#').isdigit():
                return 'Use a full name for a direct transfer, or reply with a number to the saved suggestions.'
            proposed_code = resolve_member_choice(proposed, [
                {'code': p['code'], 'name': p['display_name']} for p in people
            ])
            if not proposed_code:
                return 'I could not identify one active member by that name. Use their full name, or choose a name/number from the saved suggestions.'
            result = await run_in_threadpool(store.act, message, 'submit', {
                'task_id': str(task['id']), 'semester': settings.active_semester,
                'proposed_code': proposed_code, 'reason': 'Requested through Photon',
            })
        return response_text(result)
    except ValueError as exc:
        return str(exc)
