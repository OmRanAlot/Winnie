"""Natural request actions use live capabilities, saved clarification, and committed SQL results."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agents.request_interpreter import RequestDecision
from app.routes.messages import _process_message
from app.services.conversation_memory import prepare_context
from app.services.messaging_reassignments import reassignment_reply
from tests.test_conversation_memory import Store as MemoryStore
from tests.test_messaging_reassignments import Members, Tasks, message


def config():
    return SimpleNamespace(help_workflow_enabled=True, active_semester='fall-2026',
        message_ai_enabled=True,message_memory_enabled=True,message_memory_max_turns=6,message_memory_ttl_seconds=7200)


def row(number=8, title='Book room', review=True, respond=False):
    return {'request_no':number,'title':title,'can_review':review,'can_respond':respond,
        'requester_name':'Taylor','recipient_name':'Alex'}


class Requests:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [row()]
        self.calls = []

    def pending(self, msg):
        return {'requests': deepcopy(self.rows)}

    def act(self, msg, action, payload):
        self.calls.append((msg.message_id,action,payload))
        selected = next(r for r in self.rows if r['request_no']==payload['request_no'])
        if action in ('approved','rejected') and not selected['can_review']:
            raise ValueError('Only authorized reviewers may decide this request')
        self.rows.remove(selected)
        return {'status':'rejected' if action=='rejected' else 'declined' if action=='denied' else 'approved' if action=='accepted' else 'pending',
            'admin_decision':'approved' if action in ('approved','accepted') else 'rejected', 'request_no':selected['request_no']}


async def reply(text, store, context=None, interpreter=None):
    return await reassignment_reply(message(text),Members(),Tasks(),store,config(),interpreter,context)


@pytest.mark.parametrize('text,action', [('reject','rejected'),('please reject it','rejected'),('approve that request','approved')])
async def test_one_live_admin_request_accepts_plain_action_without_codes(text, action):
    store=Requests()
    result=await reply(text,store)
    assert store.calls==[('event-1',action,{'request_no':8})]
    assert 'Book room' in result and 'REQ-' not in result
    assert 'cannot reject' not in result


async def test_recipient_denial_and_acceptance_follow_live_stage():
    for verb,action in [('reject','denied'),('accept','accepted')]:
        store=Requests([row(review=False,respond=True)])
        await reply(verb,store)
        assert store.calls[0][1]==action
    before_admin=Requests([row(review=False,respond=False)])
    await reply('accept',before_admin)
    assert not before_admin.calls


async def test_two_requests_require_clarification_and_number_survives_new_context_instance():
    members,tasks,memory=Members(),Tasks(),MemoryStore()
    requests=Requests([row(),row(9,'Make flyer')])
    msg=message('reject',message_id='first')
    context=prepare_context(msg,members,tasks,config(),memory)
    answer=await reply('reject',requests,context)
    assert '1. Book room' in answer and '2. Make flyer' in answer and not requests.calls
    context.record(msg,answer)
    second=message('2',message_id='second')
    restored=prepare_context(second,members,tasks,config(),memory)
    result=await _process_message(second,members,tasks,None,None,None,requests,config(),restored)
    assert requests.calls==[('second','rejected',{'request_no':9})]
    assert 'Make flyer' in result['reply']


async def test_closed_focus_never_falls_through_to_a_different_request():
    members,tasks,memory=Members(),Tasks(),MemoryStore()
    msg=message('reject')
    ctx=prepare_context(msg,members,tasks,config(),memory)
    ctx.request_focus(8)
    store=Requests([row(9,'Different request')])
    result=await reply('reject',store,ctx)
    assert 'no longer awaiting' in result and not store.calls


@pytest.mark.parametrize('invalid',['unknown','low-confidence','fabricated','negated'])
async def test_model_output_never_bypasses_request_scope_or_explicit_current_instruction(invalid):
    store=Requests([row(),row(9,'Make flyer')])
    text='Please reject the room booking transfer' if invalid!='negated' else 'Do not reject the room booking transfer'
    proposed=RequestDecision(action='rejected',request_no=999 if invalid=='unknown' else 8,
        execute=True,confidence=.2 if invalid=='low-confidence' else .99,
        evidence_quote='invented' if invalid=='fabricated' else text)
    interpreter=SimpleNamespace(interpret_request=lambda *a,**kw:proposed)
    await reply(text,store,interpreter=interpreter)
    assert not store.calls


async def test_gemini_named_request_proposal_executes_through_verified_adapter_only():
    store=Requests([row(),row(9,'Make flyer')])
    text='Could you reject the room booking transfer, please?'
    seen=[]
    def interpret(actual, rows, **kwargs):
        seen.append(rows)
        return RequestDecision(action='rejected',request_no=8,execute=True,confidence=.99,evidence_quote='reject the room booking transfer')
    result=await reply(text,store,interpreter=SimpleNamespace(interpret_request=interpret))
    assert len(seen[0])==2 and store.calls[0][1:] == ('rejected',{'request_no':8})
    assert 'Rejected' in result
