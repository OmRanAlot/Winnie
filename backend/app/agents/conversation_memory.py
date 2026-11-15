"""A compact LangGraph checkpointer for pure conversation-memory updates.

The graph only records backend-validated replies. It never runs task writes or sends
messages, so replaying its pure append node after a failure cannot repeat an action.
Only the latest checkpoint is kept; time travel and subgraphs are intentionally absent.
"""
import json
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver, CheckpointTuple
from langgraph.graph import END, START, StateGraph


class SupabaseConversationSaver(BaseCheckpointSaver):
    def __init__(self, store, member, thread, ttl):
        super().__init__()
        self.store, self.member, self.thread, self.ttl = store, member, thread, ttl
        self.lock = RLock()
        self.row = store.load(member, thread)
        self.version = self.row['version'] if self.row else 0
        self.state = deepcopy(self.row['state']) if self.row else {}
        if self.row and datetime.fromisoformat(self.row['expires_at']) <= datetime.now(UTC):
            self.state = {}  # Keep the version to prevent stale-writer resurrection.

    def _check(self, config):
        if config['configurable']['thread_id'] != self.thread or config['configurable'].get('checkpoint_ns', ''):
            raise ValueError('Conversation scope mismatch')

    def get_tuple(self, config):
        self._check(config)
        with self.lock:
            checkpoint = self.state.get('checkpoint')
            if not checkpoint:
                return None
            wanted = config['configurable'].get('checkpoint_id')
            if wanted and wanted != checkpoint['id']:
                return None
            return CheckpointTuple(
                {'configurable': {'thread_id': self.thread, 'checkpoint_ns': '', 'checkpoint_id': checkpoint['id']}},
                deepcopy(checkpoint), deepcopy(self.state.get('metadata', {})), pending_writes=[],
            )

    def put(self, config, checkpoint, metadata, new_versions):
        self._check(config)
        with self.lock:
            # This graph's channels contain only JSON primitives, never executable objects.
            state = json.loads(json.dumps({'checkpoint': checkpoint, 'metadata': metadata}))
            row = self.store.save(self.member, self.thread, self.version, state, self.ttl)
            self.version, self.state = row['version'], state
        return {'configurable': {'thread_id': self.thread, 'checkpoint_ns': '', 'checkpoint_id': checkpoint['id']}}

    def put_writes(self, config, writes, task_id, task_path=''):
        self._check(config)
        # There are no side effects in the graph node. Full checkpoints suffice;
        # an interrupted append is safe to recompute and deduplicates by message ID.

    def delete_thread(self, thread_id):
        if thread_id != self.thread:
            raise ValueError('Conversation scope mismatch')
        with self.lock:
            row = self.store.save(self.member, self.thread, self.version, {}, self.ttl)
            self.version, self.state = row['version'], {}

    def list(self, config, *, filter=None, before=None, limit=None):
        if config is not None and before is None and limit != 0:
            current = self.get_tuple(config)
            if current and (not filter or all(current.metadata.get(k) == v for k, v in filter.items())):
                yield current


class MemoryState(TypedDict, total=False):
    turns: list[dict]
    turn: dict | None
    focus_task_id: str | None
    pending_intent: str | None
    question_task_ids: list[str]
    awaiting_answer: bool
    pending_help_no: int | None
    focus_request_no: int | None
    request_choices: list[int]
    pending_request_action: str | None


def memory_graph(saver, max_turns):
    def append_turn(state):
        turns, turn = state.get('turns', []), state.get('turn')
        if turn and not any(t['message_id'] == turn['message_id'] for t in turns):
            turns = [*turns, turn]
        return {'turns': turns[-max_turns:], 'turn': None}
    graph = StateGraph(MemoryState)
    graph.add_node('remember', append_turn)
    graph.add_edge(START, 'remember')
    graph.add_edge('remember', END)
    return graph.compile(checkpointer=saver)
