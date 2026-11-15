import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.settings import Settings
from app.integrations.photon import (
    PhotonQueue,
    PhotonUnavailable,
    normalize_payload,
    verify_signature,
)
from app.main import app
from app.routes import photon

WEBHOOK = '11111111-1111-4111-8111-111111111111'
ITEM = '22222222-2222-4222-8222-222222222222'
SECRET = 'synthetic-webhook-secret'
PAYLOAD = {'event':'messages', 'space':{'id':'any;-;owner@example.com','platform':'iMessage','type':'dm','phone':'shared'},
 'message':{'id':'synthetic-message','direction':'inbound','platform':'iMessage','sender':{'id':'owner@example.com'},
 'content':{'type':'text','text':'When is my task due?'}}}


def signed(body, stamp=None):
    import hashlib
    import hmac
    stamp = str(stamp if stamp is not None else int(time.time()))
    mac = hmac.new(SECRET.encode(), b'v0:' + stamp.encode() + b':' + body, hashlib.sha256).hexdigest()
    return {'x-spectrum-webhook-id':WEBHOOK,'x-spectrum-event':'messages','x-spectrum-timestamp':stamp,'x-spectrum-signature':'v0='+mac,'content-type':'application/json'}


class Inbox:
    def __init__(self):
        self.payload = None
        self.state = 'queued'
        self.reply = None
        self.calls = []
    def put(self, webhook, payload):
        self.payload = payload
        return ITEM
    def rpc(self, name, **v):
        self.calls.append((name,v))
        if name=='photon_inbox_claim':
            if self.state in ('sent','uncertain','ignored'):
                return {'done':True}
            return {'payload':self.payload,'reply':self.reply}
        self.state=v['p_state']
        self.reply=v.get('p_reply') or self.reply
        return True


@pytest.fixture
def flow(monkeypatch):
    monkeypatch.setenv('WINNIE_PHOTON_ENABLED','true')
    monkeypatch.setenv('WINNIE_PHOTON_WEBHOOK_ID',WEBHOOK)
    monkeypatch.setenv('WINNIE_PHOTON_WEBHOOK_SECRET',SECRET)
    monkeypatch.setenv('WINNIE_PHOTON_PROJECT_ID','synthetic-project')
    monkeypatch.setenv('WINNIE_PHOTON_PROJECT_SECRET','synthetic-project-secret')
    monkeypatch.setenv('WINNIE_PHOTON_QUEUE','projects/demo/locations/us-east1/queues/photon')
    monkeypatch.setenv('WINNIE_PHOTON_TASK_URL','https://example.com/api/photon/work')
    monkeypatch.setenv('WINNIE_MESSAGING_BRIDGE_SECRET','synthetic-bridge')
    inbox, queue = Inbox(), SimpleNamespace(enqueue=lambda *args: None)
    sender = SimpleNamespace(send=AsyncMock(return_value='provider-receipt'))
    monkeypatch.setitem(app.dependency_overrides,photon.get_inbox,lambda:inbox)
    monkeypatch.setitem(app.dependency_overrides,photon.get_queue,lambda:queue)
    monkeypatch.setitem(app.dependency_overrides,photon.get_sender,lambda:sender)
    monkeypatch.setattr(photon,'dispatch_notifications',AsyncMock(return_value=False))
    process = AsyncMock(return_value={'reply':'Your task is due Friday.'})
    monkeypatch.setattr(photon,'process_message',process)
    with TestClient(app) as client:
        yield client,inbox,queue,sender,process


def test_signature_uses_raw_bytes_timestamp_and_registered_webhook_id():
    body=json.dumps(PAYLOAD).encode()
    s=Settings(photon_webhook_id=WEBHOOK,photon_webhook_secret=SecretStr(SECRET))
    headers=signed(body,1000)
    assert verify_signature(body,headers,s,now=1000)
    assert not verify_signature(body+b' ',headers,s,now=1000)
    assert not verify_signature(body,headers,s,now=1400)
    assert not verify_signature(body,{**headers,'x-spectrum-webhook-id':ITEM},s,now=1000)
    assert not verify_signature(body,{**headers,'x-spectrum-timestamp':'NaN'},s,now=1000)


def test_ingress_authenticates_and_queues_without_running_gemini(flow):
    client,inbox,queue,_sender,process=flow
    calls=[]
    queue.enqueue=lambda *a:calls.append(a)
    body=json.dumps(PAYLOAD).encode()
    assert client.post('/api/photon/webhook',content=body).status_code==401
    assert inbox.payload is None
    result=client.post('/api/photon/webhook',content=body,headers=signed(body))
    assert result.status_code==200 and calls==[(ITEM,)]
    assert inbox.payload['platform']=='imessage'
    assert inbox.payload['sender_id']=='owner@example.com'
    process.assert_not_awaited()
    queue.enqueue=lambda *a: (_ for _ in ()).throw(PhotonUnavailable())
    assert client.post('/api/photon/webhook',content=body,headers=signed(body)).status_code==503


def test_worker_processes_stored_identity_and_sends_once_on_duplicate_tasks(flow):
    client,inbox,_queue,sender,process=flow
    inbox.payload=normalize_payload(PAYLOAD)
    assert client.post('/api/photon/work',json={'item_id':ITEM}).status_code==401
    for _ in range(2):
        assert client.post('/api/photon/work',json={'item_id':ITEM},headers={'x-winnie-bridge-secret':'synthetic-bridge'}).status_code==200
    process.assert_awaited_once()
    assert process.call_args.args[0].sender_id=='owner@example.com'
    sender.send.assert_awaited_once()
    assert sender.send.call_args.kwargs['space_id']=='any;-;owner@example.com'
    assert inbox.state=='sent'


def test_uncertain_provider_send_is_not_blindly_retried(flow):
    client,inbox,_queue,sender,_process=flow
    inbox.payload=normalize_payload(PAYLOAD)
    sender.send.side_effect=PhotonUnavailable()
    for _ in range(2):
        result=client.post('/api/photon/work',json={'item_id':ITEM},headers={'x-winnie-bridge-secret':'synthetic-bridge'})
        assert result.status_code==200
    sender.send.assert_awaited_once()
    assert inbox.state=='uncertain'


def test_unknown_content_and_outbound_echoes_do_not_queue(flow):
    client,inbox,*_=flow
    data={**PAYLOAD,'message':{**PAYLOAD['message'],'direction':'outbound'}}
    body=json.dumps(data).encode()
    assert client.post('/api/photon/webhook',content=body,headers=signed(body)).json()['ignored']
    assert inbox.payload is None
    for malformed in ({'message':None}, {'space':[]}, {'message':{'content':None,'platform':'imessage','direction':'inbound'}}):
        with pytest.raises((TypeError,ValueError)):
            normalize_payload({**PAYLOAD,**malformed})


def test_queue_uses_durable_id_and_private_authenticated_job(monkeypatch):
    calls=[]
    session=SimpleNamespace(post=lambda url,**kw:(calls.append((url,kw)) or SimpleNamespace(status_code=200)),close=lambda:None)
    monkeypatch.setattr('app.integrations.photon.google.auth.default',lambda **kw:('creds','project'))
    monkeypatch.setattr('app.integrations.photon.AuthorizedSession',lambda creds:session)
    settings=Settings(photon_queue='projects/demo/locations/us-east1/queues/photon',
        photon_task_url='https://example.com/api/photon/work',messaging_bridge_secret=SecretStr('private'))
    queue=PhotonQueue(settings)
    queue.enqueue(ITEM); queue.enqueue(ITEM)
    assert calls[0][1]['json']['task']['name']==calls[1][1]['json']['task']['name']
    job=calls[0][1]['json']['task']['httpRequest']
    assert job['headers']['X-Winnie-Bridge-Secret']=='private'
    assert 'owner@example.com' not in json.dumps(job)

def test_stream_listener_does_not_duplicate_webhook_replies(monkeypatch):
    monkeypatch.setenv('WINNIE_PHOTON_ENABLED','true')
    with TestClient(app) as client:
        result=client.post('/api/messages',json={'text':'ping','platform':'imessage','conversation_type':'dm'})
        assert result.status_code==200 and result.json()['reply'] is None


def test_registration_requires_deployed_route_and_saves_secret_without_exposing_it(tmp_path,monkeypatch):
    import httpx

    from app.cli import photon_webhook
    monkeypatch.setattr(photon_webhook,'ROOT',tmp_path)
    folder=tmp_path/'messaging'
    folder.mkdir()
    (folder/'.env').write_text('PROJECT_ID=synthetic-project\nPROJECT_SECRET=private-project-secret\n')
    seen=[]
    def handler(request):
        seen.append(request.method)
        if request.url.host=='example.com':
            return httpx.Response(200,json={'integration':'winnie-photon-spectrum'})
        if request.method=='GET':
            return httpx.Response(200,json={'succeed':True,'data':[]})
        return httpx.Response(200,json={'succeed':True,'data':{'id':WEBHOOK,'signingSecret':'private-webhook-secret'}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        identifier,path=photon_webhook.register('https://example.com/api/photon/webhook',session=client)
        assert identifier==WEBHOOK
        assert 'private-webhook-secret' in path.read_text()
        assert seen==['GET','GET','POST']
    seen.clear()
    with httpx.Client(transport=httpx.MockTransport(lambda r:(seen.append(r.method) or httpx.Response(404)))) as client, pytest.raises(ValueError,match='Deploy the updated backend'):
        photon_webhook.register('https://example.com/api/photon/webhook',session=client)
    assert seen==['GET']
