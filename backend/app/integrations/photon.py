"""Stable Spectrum transport: signed ingress, durable state and request-scoped replies."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

import google.auth
from google.auth.transport.requests import AuthorizedSession
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable
from app.services.members import MemberStore

MAX_WEBHOOK_BYTES = 128 * 1024


class PhotonUnavailable(Exception):
    pass


def verify_signature(body, headers, settings, now=None):
    secret = settings.photon_webhook_secret.get_secret_value()
    stamp = headers.get('x-spectrum-timestamp', '')
    if not secret or not settings.photon_webhook_id:
        raise PhotonUnavailable('Photon webhook is not configured.')
    if headers.get('x-spectrum-webhook-id') != settings.photon_webhook_id:
        return False
    if not re.fullmatch(r'[0-9]{1,12}', stamp) or abs((now or time.time()) - int(stamp)) > 300:
        return False
    expected = 'v0=' + hmac.new(secret.encode(), b'v0:' + stamp.encode() + b':' + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers.get('x-spectrum-signature', ''))


def normalize_payload(data):
    """Never derive identity, routing or action from the message's text."""
    if data.get('event') != 'messages':
        return None
    message = data.get('message', {})
    if not isinstance(message, dict):
        raise TypeError('Invalid message')
    space = data.get('space') or message.get('space', {})
    if not isinstance(space, dict):
        raise TypeError('Invalid event')
    if str(message.get('platform', '')).lower() != 'imessage' or message.get('direction') != 'inbound':
        return None
    content, sender = message.get('content', {}), message.get('sender', {})
    if not isinstance(content, dict) or not isinstance(sender, dict):
        raise TypeError('Invalid message')
    if content.get('type') != 'text' or sender.get('kind') == 'agent':
        return None
    if str(space.get('platform', '')).lower() != 'imessage' or space.get('type') not in ('dm', 'group'):
        raise ValueError('Invalid conversation')
    for value in (message.get('id'), space.get('id'), sender.get('id')):
        if not isinstance(value, str) or not 1 <= len(value) <= 500:
            raise ValueError('Invalid message metadata')
    if not isinstance(content.get('text'), str) or len(content['text']) > 10000:
        raise ValueError('Invalid message text')
    phone = space.get('phone')
    if phone is not None and (not isinstance(phone, str) or len(phone) > 100):
        raise ValueError('Invalid line')
    return {'message_id': message['id'], 'space_id': space['id'], 'sender_id': sender['id'],
        'text': content['text'], 'platform': 'imessage', 'conversation_type': space['type'], 'phone': phone}


class PhotonInbox(MemberStore):
    def rpc(self, name, **values):
        client = self.client_factory()
        try:
            return client.rpc(name, values).execute().data
        except (APIError, HTTPError, OSError) as exc:
            raise StorageUnavailable('Photon inbox is unavailable. Check the webhook migration.') from exc
        finally:
            client.postgrest.session.close()

    def put(self, webhook, payload):
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return self.rpc('photon_inbox_put', p_webhook=webhook, p_message=payload['message_id'], p_hash=digest, p_payload=payload)


class PhotonQueue:
    def __init__(self, settings):
        self.settings = settings

    def enqueue(self, item_id=None, suffix=None):
        s = self.settings
        if not re.fullmatch(r'projects/[a-zA-Z0-9-]+/locations/[a-z0-9-]+/queues/[a-zA-Z0-9_-]+', s.photon_queue):
            raise PhotonUnavailable('Configure the Photon Cloud Tasks queue.')
        if not s.photon_task_url.startswith('https://') or not s.photon_task_url.endswith('/api/photon/work'):
            raise PhotonUnavailable('Configure the deployed Photon task URL.')
        secret = s.messaging_bridge_secret.get_secret_value()
        if not secret:
            raise PhotonUnavailable('Configure the backend bridge secret.')
        # Each new notification kick must run even if a previous kick just finished.
        # Inbox deliveries keep stable IDs; the database fences all physical sends.
        key = str(item_id) if item_id else f'notifications:{suffix or uuid4()}'
        task = {'name': f'{s.photon_queue}/tasks/' + hashlib.sha256(key.encode()).hexdigest(),
            'dispatchDeadline': '120s', 'httpRequest': {'httpMethod': 'POST', 'url': s.photon_task_url,
                'headers': {'Content-Type': 'application/json', 'X-Winnie-Bridge-Secret': secret},
                'body': base64.b64encode(json.dumps({'item_id': item_id}).encode()).decode()}}
        session = None
        try:
            credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
            session = AuthorizedSession(credentials)
            response = session.post(f'https://cloudtasks.googleapis.com/v2/{s.photon_queue}/tasks', json={'task': task}, timeout=10)
            if response.status_code not in (200, 201, 409):
                raise PhotonUnavailable('Cloud Tasks rejected the job. Check queue and runtime IAM configuration.')
        except PhotonUnavailable:
            raise
        except Exception as exc:
            raise PhotonUnavailable('Cloud Tasks is unavailable. Check runtime credentials.') from exc
        finally:
            if session:
                session.close()


class PhotonSender:
    def __init__(self, settings):
        self.settings = settings

    async def send(self, text, dedupe_key, *, space_id=None, phone=None, recipient=None):
        s = self.settings
        if not s.photon_project_id or not s.photon_project_secret.get_secret_value():
            raise PhotonUnavailable('Configure Photon project credentials.')
        node = shutil.which('node')
        if not node:
            raise PhotonUnavailable('The backend container is missing the Photon runtime.')
        helper = Path(__file__).resolve().parents[2] / 'photon' / 'send.mjs'
        env = {**os.environ, 'WINNIE_PHOTON_PROJECT_ID': s.photon_project_id,
            'WINNIE_PHOTON_PROJECT_SECRET': s.photon_project_secret.get_secret_value()}
        process = await asyncio.create_subprocess_exec(node, str(helper), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        try:
            output, _ = await asyncio.wait_for(process.communicate(json.dumps({'text': text,
                'dedupe_key': dedupe_key, 'space_id': space_id, 'phone': phone, 'recipient': recipient}).encode()), timeout=35)
            if process.returncode:
                raise PhotonUnavailable('Photon did not confirm the send.')
            return json.loads(output)['provider_id']
        except (TimeoutError, ValueError, KeyError) as exc:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise PhotonUnavailable('Photon send outcome is uncertain.') from exc
