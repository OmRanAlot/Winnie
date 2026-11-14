"""Durable help requests and recent check-in context, without inventing helper recommendations."""

from datetime import timedelta

from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable, create_task_client


class HelpRequestStore:
    def __init__(self, client_factory=create_task_client):
        self.client_factory = client_factory

    def _execute(self, operation):
        client = None
        try:
            client = self.client_factory()
            return operation(client).execute().data
        except (HTTPError, APIError) as exc:
            raise StorageUnavailable("Help request storage is unavailable.") from exc
        finally:
            if client is not None:
                client.postgrest.session.close()

    def recent_offers(self, member_code, sender_id, now):
        return self._execute(lambda client: client.table("reminder_deliveries").select(
            "task_id,due_date"
        ).eq("member_code", member_code).eq("sender_id", sender_id).eq(
            "kind", "five_day_help"
        ).eq("transport", "photon").eq("status", "sent").gt(
            "expires_at", now.isoformat()
        ).gte("sent_at", (now - timedelta(hours=12)).isoformat()).order("sent_at", desc=True).limit(20))

    def request(self, message, member_code, task, digest, semester):
        return self._execute(lambda client: client.rpc("request_task_help", {
            "p_platform": message.platform, "p_message_id": message.message_id,
            "p_sender_id": message.sender_id, "p_member_code": member_code,
            "p_request_hash": digest, "p_task_id": task["id"],
            "p_expected_updated_at": task["updated_at"],
            "p_expected_assignee_text": task["assignee_text"], "p_semester": semester,
        }))
