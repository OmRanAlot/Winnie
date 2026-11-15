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

    def rpc(self, name, **values):
        try:
            return self._execute(lambda client: client.rpc(name, values))
        except StorageUnavailable as exc:
            if isinstance(exc.__cause__, APIError) and exc.__cause__.code == "P0001":
                raise ValueError(exc.__cause__.message) from exc
            raise

    def get(self, number):
        rows = self._execute(lambda client: client.table("task_help_requests").select("*").eq("request_no", number))
        return rows[0] if rows else None

    def is_admin(self, member_code):
        rows = self._execute(lambda client: client.table("members").select("code").eq(
            "code", member_code).eq("active", True).eq("messaging_admin", True))
        return len(rows) == 1

    def receipt(self, message):
        rows = self._execute(lambda client: client.table("task_help_request_messages").select("request_no").eq(
            "platform", message.platform).eq("message_id", message.message_id))
        return self.get(rows[0]["request_no"]) if rows else None

    def pending(self):
        return self._execute(lambda client: client.table("task_help_requests").select(
            "request_no,task_id,requester_code,selected_code,status,revision,candidates,task:tasks(title,task_code)"
        ).eq("status", "pending_approval").is_("reassignment_id", "null").order("request_no").limit(100))

    def group(self, group_id):
        rows = self._execute(lambda client: client.table("task_help_requests").select("*").eq(
            "group_id", group_id).eq("status", "group_active"))
        return rows[0] if rows else None
