"""Bounded, verified conversational context. History never grants task permissions."""
import hashlib
import json
import re
from datetime import UTC, datetime

from app.agents.conversation_memory import SupabaseConversationSaver, memory_graph
from app.services.members import assignment_members, normalize_sender, resolve_member_choice
from app.services.tasks import TaskNotFound

REFERENCE = re.compile(r"\b(it|its|that task|this task)\b|^what about (?:the )?(?:deadline|due date)\??$", re.IGNORECASE)
FORGET = {'forget conversation', 'forget this conversation', 'reset conversation', 'new conversation'}
HELP_SIGNAL = re.compile(r"\b(?:i\s+)?(?:need|want|could use)\s+(?:some\s+)?help\b|\b(reassign|replacement|take over)\b", re.IGNORECASE)
HELP_CANCEL = re.compile(r"\b(?:don't|do not|no longer|not)\s+(?:need|want)\s+help\b|^(?:never mind|nevermind|cancel|no thanks)[.! ]*$", re.IGNORECASE)
HELP_UNCERTAIN = re.compile(r"\b(?:if|might|maybe|hypothetical)\b|\bdo i (?:need|want) help\b", re.IGNORECASE)
SHORT_ANSWER = {'yes', 'yeah', 'yep', 'no', 'nope', 'sure', 'yes please', 'no thanks'}


def thread_key(message, member, semester):
    # Hashed namespace includes the verified sender, even if a DM ID is missing.
    scope = ['v1', message.platform, normalize_sender(message.sender_id),
        message.space_id or 'legacy-dm', member, semester]
    return hashlib.sha256(json.dumps(scope, separators=(',', ':')).encode()).hexdigest()


def task_rows(tasks, ids):
    if hasattr(tasks, 'get_many'):
        return tasks.get_many(ids)
    rows = []
    for task_id in ids:
        try:
            rows.append(tasks.get(task_id))
        except (TaskNotFound, KeyError):
            pass
    return rows


class ConversationContext:
    def __init__(self, message, member, tasks, members, settings, store):
        self.member, self.tasks, self.members = member, tasks, members
        self.semester = settings.active_semester
        self.saver = SupabaseConversationSaver(store, member, thread_key(message, member, self.semester),
            settings.message_memory_ttl_seconds)
        self.graph = memory_graph(self.saver, settings.message_memory_max_turns)
        self.config = {'configurable': {'thread_id': self.saver.thread}}
        values = self.saver.state.get('checkpoint', {}).get('channel_values', {})
        turns = values.get('turns', [])[-settings.message_memory_max_turns:]
        self.known_turns = turns
        focus = values.get('focus_task_id')
        ids = {task_id for turn in turns for task_id in turn.get('task_versions', {})}
        ids.update(values.get('question_task_ids', []))
        if focus:
            ids.add(focus)
        self.authorized = self._authorized(task_rows(tasks, ids))
        self.turns = [turn for turn in turns if all(
            task_id in self.authorized and self.authorized[task_id].get('updated_at') == version
            for task_id, version in turn.get('task_versions', {}).items())]
        self.focus_task_id = focus if focus in self.authorized else None
        self.question_task_ids = [key for key in values.get('question_task_ids', []) if key in self.authorized]
        self.awaiting_answer = bool(values.get('awaiting_answer')) and bool(self.turns)
        self.pending_intent = values.get('pending_intent') if values.get('pending_intent') == 'request_help' else None
        self.pending_help_no = values.get('pending_help_no') if self.focus_task_id else None
        if values.get('question_task_ids') and not self.question_task_ids:
            self.pending_intent, self.awaiting_answer = None, False
        self.tracked = set()
        number = values.get('focus_request_no')
        self.focus_request_no = number if type(number) is int and number > 0 else None
        self.request_choices = [n for n in values.get('request_choices', []) if type(n) is int and n > 0][:30]
        self.pending_request_action = values.get('pending_request_action') if values.get('pending_request_action') in ('approve','reject','accept','deny') else None

    def request_focus(self, number=None, choices=None, action=None):
        self.focus_request_no = number
        self.request_choices = list(choices or [])[:30]
        self.pending_request_action = action

    def _authorized(self, rows):
        if not rows:
            return {}
        aliases = self.members.aliases(self.semester)
        allowed = {}
        for task in rows:
            codes = {task['owner_code']} if task.get('owner_code') else assignment_members(task.get('assignee_text', ''), aliases)
            if task.get('semester_code') == self.semester and codes is not None and self.member in codes:
                allowed[str(task['id'])] = task
        return allowed

    @property
    def history(self):
        return [message for turn in self.turns for message in (
            {'role': 'user', 'content': turn['user']}, {'role': 'assistant', 'content': turn['assistant']})]

    def prompt_tasks(self, selected):
        result = list(selected)
        if self.focus_task_id and self.focus_task_id not in {str(t['id']) for t in result}:
            result.append(self.authorized[self.focus_task_id])
        self.tracked.update(str(t['id']) for t in result)
        return result

    def ambiguous_reference(self, text, tasks):
        if self.focus_task_id or self.awaiting_answer or not REFERENCE.search(text):
            return False
        lower = text.casefold()
        return not any((t.get('task_code') and t['task_code'].casefold() in lower)
            or (t.get('title') and t['title'].casefold() in lower) for t in tasks)

    def focus(self, ids):
        self.focus_task_id = str(ids[0]) if len(ids) == 1 else None
        self.tracked.update(str(value) for value in ids)

    def observe_input(self, text):
        """Carry only explicit help intent, never completion/approval permission."""
        if HELP_CANCEL.search(text):
            self.pending_intent = None
        elif HELP_SIGNAL.search(text) and not HELP_UNCERTAIN.search(text):
            self.pending_intent = 'request_help'

    def clarify(self, ids):
        self.awaiting_answer = True
        if ids:
            self.question_task_ids = list(map(str, ids))
            if len(ids) == 1:
                self.focus(ids)
            else:
                self.focus([])

    def answered(self):
        self.awaiting_answer = False
        self.question_task_ids = []

    def named_task(self, text, tasks):
        value = text.strip().casefold().rstrip('.!? ')
        if self.awaiting_answer and value.isdigit() and 1 <= int(value) <= len(self.question_task_ids):
            selected = self.question_task_ids[int(value)-1]
            return next((t for t in tasks if str(t['id']) == selected), None)
        matches = [t for t in tasks if value in (
            str(t.get('task_code', '')).casefold(), str(t.get('title', '')).strip().casefold())]
        return matches[0] if len(matches) == 1 else None

    def reset_question(self):
        self.pending_intent = None
        self.pending_help_no = None
        self.answered()

    def offer_helpers(self, request):
        if request['requester_code'] == self.member and str(request['task_id']) == self.focus_task_id and request['status'] == 'suggestions_ready':
            self.pending_help_no = request['request_no']
            self.clarify([self.focus_task_id])

    def helper_choice(self, text, request):
        if (not request or request['request_no'] != self.pending_help_no or request['requester_code'] != self.member
                or str(request['task_id']) != self.focus_task_id or request['status'] != 'suggestions_ready'):
            return None
        return resolve_member_choice(text, request.get('candidates', []))

    def clear(self):
        self.saver.delete_thread(self.saver.thread)

    def replay(self, message):
        prior = next((t for t in self.known_turns if t['message_id'] == message.message_id), None)
        if prior is None:
            return None
        if prior.get('input_hash') != hashlib.sha256(message.text.encode()).hexdigest():
            return 'This message ID was already used with different content. Send a new message.'
        if prior not in self.turns:
            return 'The task changed since that message. Text tasks or send a new message to check its current state.'
        return prior['assistant']

    def record(self, message, reply):
        # Recheck every task whose facts were available to the model, not just its
        # claimed matches. Updated facts or reassignment cannot survive in history.
        ids = self.tracked | {task_id for turn in self.turns for task_id in turn.get('task_versions', {})}
        if self.focus_task_id:
            ids.add(self.focus_task_id)
        ids.update(self.question_task_ids)
        authorized = self._authorized(task_rows(self.tasks, ids))
        safe_turns = [turn for turn in self.turns if all(
            task_id in authorized and authorized[task_id].get('updated_at') == version
            for task_id, version in turn.get('task_versions', {}).items())]
        focus = self.focus_task_id if self.focus_task_id in authorized else None
        turn = None
        if self.tracked <= authorized.keys():
            turn = {'message_id': message.message_id,
                'input_hash': hashlib.sha256(message.text.encode()).hexdigest(),
                'user': message.text[:3000], 'assistant': reply[:2000],
                'task_versions': {key: authorized[key].get('updated_at') for key in self.tracked},
                'created_at': datetime.now(UTC).isoformat()}
        # A duplicate webhook cannot append again or change the conversation focus.
        if any(t['message_id'] == message.message_id for t in safe_turns):
            return
        questions = [key for key in self.question_task_ids if key in authorized]
        pending = self.pending_intent if not self.question_task_ids or questions else None
        self.graph.invoke({'turns': safe_turns, 'turn': turn, 'focus_task_id': focus,
            'focus_request_no': self.focus_request_no, 'request_choices': self.request_choices,
            'pending_request_action': self.pending_request_action,
            'pending_intent': pending, 'question_task_ids': questions,
            'pending_help_no': self.pending_help_no if focus else None,
            'awaiting_answer': self.awaiting_answer and (not self.question_task_ids or bool(questions))}, self.config)


def prepare_context(message, members, tasks, settings, store):
    if not getattr(settings, 'message_memory_enabled', False) or message.conversation_type != 'dm':
        return None
    if message.platform != 'imessage' or not message.sender_id or not message.message_id:
        return None
    member = members.resolve(message.platform, normalize_sender(message.sender_id))
    if not member:
        return None
    return ConversationContext(message, member['code'], tasks, members, settings, store)
