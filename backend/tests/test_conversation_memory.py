"""Real LangGraph + fake durable store: restart, authorization, TTL and reset boundaries."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock

import pytest
from fastapi.testclient import TestClient

from app.agents.message_interpreter import MessageDecision
from app.integrations.supabase import StorageUnavailable
from app.main import app
from app.routes import messages
from app.services.conversation import conversation_reply
from app.services.conversation_memory import prepare_context, thread_key
from tests.test_conversation import A, B, Completions, Members, Tasks, message, settings


class Store:
    def __init__(self):
        self.rows = {}
        self.lock = RLock()
    def load(self, member, thread):
        return deepcopy(self.rows.get((member, thread)))
    def save(self, member, thread, expected, state, ttl):
        with self.lock:
            row = self.rows.get((member, thread))
            if (row['version'] if row else 0) != expected:
                raise StorageUnavailable('Concurrent memory update')
            saved = {'version': expected+1, 'state': deepcopy(state),
                'expires_at': (datetime.now(UTC)+timedelta(seconds=ttl)).isoformat()}
            self.rows[(member,thread)] = saved
            return deepcopy(saved)


def config():
    return settings(message_memory_enabled=True, message_memory_max_turns=6, message_memory_ttl_seconds=7200)


class Interpreter:
    def __init__(self):
        self.calls = []
    def interpret(self, text, tasks, *, history=None, focus_task_id=None):
        self.calls.append({'text':text,'tasks':deepcopy(tasks),'history':history,'focus':focus_task_id})
        return MessageDecision(intent='answer',task_ids=[A],completion_asserted=False,
            evidence_quote='',confidence=0.99,reply='Book room is due November 20.')


def turn(store, tasks, msg, interpreter=None):
    members, completions = Members(), Completions(tasks)
    ctx = prepare_context(msg,members,tasks,config(),store)
    llm = interpreter or Interpreter()
    reply = conversation_reply(msg,members,tasks,completions,llm,config(),ctx)
    ctx.record(msg,reply)
    return ctx,reply,llm,completions


def test_followup_survives_new_graph_and_service_instances_with_real_langgraph():
    store,tasks=Store(),Tasks()
    first=message('When is Book room due?',message_id='first',space_id='dm-a')
    turn(store,tasks,first)
    second=message('What about its deadline?',message_id='second',space_id='dm-a')
    ctx,reply,llm,completions=turn(store,tasks,second)
    assert reply=='Book room is due November 20.'
    assert llm.calls[0]['focus']==A
    assert llm.calls[0]['history'][0]['content']==first.text
    assert len(ctx.saver.state['checkpoint']['channel_values']['turns'])==2
    assert completions.writes==0


def test_history_is_isolated_by_member_sender_dm_and_semester():
    store,tasks=Store(),Tasks()
    original=message('When is Book room due?',space_id='dm-a')
    turn(store,tasks,original)
    for altered in (message('What about its deadline?',space_id='dm-b'),
                    message('What about its deadline?',sender_id='+15555559999',space_id='dm-a')):
        ctx=prepare_context(altered,Members(),tasks,config(),store)
        assert ctx is None or not ctx.history
    assert thread_key(original,'ONE','fall-2026')!=thread_key(original,'TWO','fall-2026')
    assert thread_key(original,'ONE','fall-2026')!=thread_key(original,'ONE','spring-2027')


def test_reassigned_task_and_ambiguous_followup_cannot_reuse_history():
    store,tasks=Store(),Tasks()
    turn(store,tasks,message('When is Book room due?',message_id='first'))
    tasks.rows[A].update(owner_code='TWO',updated_at='version-2')
    ctx,reply,llm,completions=turn(store,tasks,message('What about its deadline?',message_id='second'))
    assert 'Which task' in reply and not llm.calls and completions.writes==0
    assert not ctx.history and ctx.focus_task_id is None


def test_changed_facts_drop_old_history_but_keep_verified_task_referent():
    store,tasks=Store(),Tasks()
    turn(store,tasks,message('When is Book room due?',message_id='first'))
    tasks.rows[A].update(due_date='2026-12-01',updated_at='version-2')
    _,_,llm,_=turn(store,tasks,message('What about its deadline?',message_id='second'))
    assert llm.calls[0]['history']==[] and llm.calls[0]['focus']==A
    assert next(t for t in llm.calls[0]['tasks'] if t['id']==A)['due_date']=='2026-12-01'


def test_expiration_bounds_and_duplicate_message_replay():
    store,tasks=Store(),Tasks()
    for n in range(9):
        ctx,_,_,_=turn(store,tasks,message('When is Book room due?',message_id=f'event-{n}'))
    assert len(ctx.saver.state['checkpoint']['channel_values']['turns'])==6
    duplicate=message('When is Book room due?',message_id='event-8')
    current=prepare_context(duplicate,Members(),tasks,config(),store)
    assert current.replay(duplicate)=='Book room is due November 20.'
    assert 'different content' in current.replay(duplicate.model_copy(update={'text':'done WIN-202610-2'}))
    for row in store.rows.values(): row['expires_at']=(datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    expired=prepare_context(duplicate,Members(),tasks,config(),store)
    assert not expired.history and expired.focus_task_id is None


def test_bare_confirmation_still_cannot_complete_or_approve_using_memory():
    store,tasks=Store(),Tasks()
    turn(store,tasks,message('When is Book room due?',message_id='first'))
    for n,text in enumerate(('yes','done','I completed it')):
        _,reply,llm,completions=turn(store,tasks,message(text,message_id=f'bare-{n}'))
        assert 'Which task' in reply and completions.writes==0 and not llm.calls


def test_forget_uses_versioned_tombstone_and_blocks_an_older_writer():
    store,tasks=Store(),Tasks()
    turn(store,tasks,message('When is Book room due?',message_id='first'))
    msg=message('What about its deadline?',message_id='stale')
    stale=prepare_context(msg,Members(),tasks,config(),store)
    fresh=prepare_context(msg,Members(),tasks,config(),store)
    fresh.clear()
    assert store.rows[('ONE',fresh.saver.thread)]['state']=={}
    with pytest.raises(StorageUnavailable): stale.record(msg,'Old history must not return')
    cleared=prepare_context(msg,Members(),tasks,config(),store)
    assert not cleared.history and cleared.focus_task_id is None


def test_forget_command_is_available_through_authenticated_shared_message_handler(monkeypatch):
    monkeypatch.setenv('WINNIE_MESSAGE_MEMORY_ENABLED','true')
    monkeypatch.setenv('WINNIE_MESSAGING_BRIDGE_SECRET','synthetic-memory-secret')
    monkeypatch.setenv('WINNIE_PHOTON_ENABLED','false')
    store,tasks=Store(),Tasks()
    turn(store,tasks,message('When is Book room due?',message_id='first'))
    monkeypatch.setitem(app.dependency_overrides,messages.get_memory_store,lambda:store)
    monkeypatch.setitem(app.dependency_overrides,messages.get_member_store,Members)
    monkeypatch.setitem(app.dependency_overrides,messages.get_task_store,lambda:tasks)
    with TestClient(app) as client:
        result=client.post('/api/messages',json=message('forget conversation',message_id='reset').model_dump(),
            headers={'X-Winnie-Bridge-Secret':'synthetic-memory-secret'})
        assert result.status_code==200 and result.json()['reply'].startswith('Forgot this conversation')
    assert all(row['state']=={} for row in store.rows.values())
    assert tasks.rows[A]['status']=='todo' and tasks.rows[B]['status']=='todo'

def test_shared_http_handler_records_answers_and_reuses_them_without_another_model_call(monkeypatch):
    monkeypatch.setenv('WINNIE_MESSAGE_MEMORY_ENABLED','true')
    monkeypatch.setenv('WINNIE_MESSAGE_AI_ENABLED','true')
    monkeypatch.setenv('WINNIE_PHOTON_ENABLED','false')
    monkeypatch.setenv('WINNIE_MESSAGING_BRIDGE_SECRET','synthetic-memory-secret')
    store,tasks,llm=Store(),Tasks(),Interpreter()
    monkeypatch.setitem(app.dependency_overrides,messages.get_memory_store,lambda:store)
    monkeypatch.setitem(app.dependency_overrides,messages.get_member_store,Members)
    monkeypatch.setitem(app.dependency_overrides,messages.get_task_store,lambda:tasks)
    monkeypatch.setitem(app.dependency_overrides,messages.get_completion_store,lambda:Completions(tasks))
    monkeypatch.setitem(app.dependency_overrides,messages.get_message_interpreter,lambda:llm)
    headers={'X-Winnie-Bridge-Secret':'synthetic-memory-secret'}
    with TestClient(app) as client:
        first=message('When is Book room due?',message_id='first',space_id='dm-a').model_dump()
        assert client.post('/api/messages',json=first,headers=headers).json()['reply']=='Book room is due November 20.'
        followup=message('What about its deadline?',message_id='second',space_id='dm-a').model_dump()
        assert client.post('/api/messages',json=followup,headers=headers).json()['reply']=='Book room is due November 20.'
        assert llm.calls[-1]['focus']==A and llm.calls[-1]['history']
        calls=len(llm.calls)
        assert client.post('/api/messages',json=followup,headers=headers).json()['reply']=='Book room is due November 20.'
        assert len(llm.calls)==calls
        changed={**followup,'text':'done WIN-202610-2'}
        assert 'different content' in client.post('/api/messages',json=changed,headers=headers).json()['reply']
        assert tasks.rows[B]['status']=='todo'


def test_unrelated_group_does_not_receive_memory_or_a_forget_reply(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    s=SimpleNamespace(message_memory_enabled=True,help_workflow_enabled=False)
    result=asyncio.run(messages.process_message(message('forget conversation',conversation_type='group'),
        Members(),Tasks(),None,None,None,None,s,Store()))
    assert result=={'reply':None}


def test_memory_storage_failure_degrades_without_exposing_or_inventing_context(monkeypatch):
    monkeypatch.setenv('WINNIE_MESSAGE_MEMORY_ENABLED','true')
    monkeypatch.setenv('WINNIE_MESSAGE_AI_ENABLED','true')
    monkeypatch.setenv('WINNIE_PHOTON_ENABLED','false')
    monkeypatch.setenv('WINNIE_MESSAGING_BRIDGE_SECRET','synthetic-memory-secret')
    class Unavailable(Store):
        def load(self,*args):
            raise StorageUnavailable('Unavailable')
    tasks,llm=Tasks(),Interpreter()
    monkeypatch.setitem(app.dependency_overrides,messages.get_memory_store,Unavailable)
    monkeypatch.setitem(app.dependency_overrides,messages.get_member_store,Members)
    monkeypatch.setitem(app.dependency_overrides,messages.get_task_store,lambda:tasks)
    monkeypatch.setitem(app.dependency_overrides,messages.get_completion_store,lambda:Completions(tasks))
    monkeypatch.setitem(app.dependency_overrides,messages.get_message_interpreter,lambda:llm)
    with TestClient(app) as client:
        response=client.post('/api/messages',json=message('When is Book room due?').model_dump(),
            headers={'X-Winnie-Bridge-Secret':'synthetic-memory-secret'})
    assert response.status_code==200 and 'Conversation memory is unavailable' in response.json()['reply']
    assert llm.calls[0]['history'] is None and tasks.rows[A]['status']=='todo'
