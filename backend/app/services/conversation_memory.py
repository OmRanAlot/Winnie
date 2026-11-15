"""Bounded, verified conversational context. History never grants task permissions."""
import hashlib
import json
import re
from datetime import UTC, datetime

from app.agents.conversation_memory import SupabaseConversationSaver, memory_graph
from app.services.members import assignment_members, normalize_sender
from app.services.tasks import TaskNotFound

REFERENCE = re.compile(r"\b(it|its|that task|this task)\b|^what about (?:the )?(?:deadline|due date)\??$", re.IGNORECASE)
FORGET = {'forget conversation', 'forget this conversation', 'reset conversation', 'new conversation'}


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
        if focus:
            ids.add(focus)
        self.authorized = self._authorized(task_rows(tasks, ids))
        self.turns = [turn for turn in turns if all(
            task_id in self.authorized and self.authorized[task_id].get('updated_at') == version
            for task_id, version in turn.get('task_versions', {}).items())]
        self.focus_task_id = focus if focus in self.authorized else None
        self.tracked = set()

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
        if self.focus_task_id or not REFERENCE.search(text):
            return False
        lower = text.casefold()
        return not any((t.get('task_code') and t['task_code'].casefold() in lower)
            or (t.get('title') and t['title'].casefold() in lower) for t in tasks)

    def focus(self, ids):
        self.focus_task_id = str(ids[0]) if len(ids) == 1 else None
        self.tracked.update(str(value) for value in ids)

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
        self.graph.invoke({'turns': safe_turns, 'turn': turn, 'focus_task_id': focus}, self.config)


def prepare_context(message, members, tasks, settings, store):
    if not getattr(settings, 'message_memory_enabled', False) or message.conversation_type != 'dm':
        return None
    if message.platform != 'imessage' or not message.sender_id or not message.message_id:
        return None
    member = members.resolve(message.platform, normalize_sender(message.sender_id))
    if not member:
        return None
    return ConversationContext(message, member['code'], tasks, members, settings, store)
