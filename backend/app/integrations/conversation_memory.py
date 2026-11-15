"""Private REST-backed storage; no connection string or ephemeral filesystem needed."""
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable
from app.services.members import MemberStore


class ConversationMemoryStore(MemberStore):
    def load(self, member, thread):
        return self._rpc('load_photon_memory', {'p_member': member, 'p_thread': thread})

    def save(self, member, thread, expected, state, ttl):
        return self._rpc('save_photon_memory', {
            'p_member': member, 'p_thread': thread, 'p_expected': expected,
            'p_state': state, 'p_ttl': ttl,
        })

    def _rpc(self, name, params):
        client = None
        try:
            client = self.client_factory()
            return client.rpc(name, params).execute().data
        except (APIError, HTTPError) as exc:
            raise StorageUnavailable('Conversation memory could not be saved.') from exc
        finally:
            if client is not None:
                client.postgrest.session.close()
