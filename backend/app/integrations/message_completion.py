"""Read completion receipts and atomically save one authorized message action."""

from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable, create_task_client


class CompletionStore:
    def __init__(self, client_factory=create_task_client):
        self.client_factory = client_factory

    def _execute(self, operation):
        client = None
        try:
            client = self.client_factory()
            return operation(client).execute().data
        except (HTTPError, APIError) as exc:
            raise StorageUnavailable("Message action storage is unavailable.") from exc
        finally:
            if client is not None:
                client.postgrest.session.close()

    def receipt(self, platform, message_id, sender_id, member_code, request_hash):
        records = self._execute(lambda client: client.table("message_task_completions").select(
            "reply,request_hash"
        ).eq("platform", platform).eq("message_id", message_id).eq(
            "sender_id", sender_id
        ).eq("member_code", member_code))
        if not records:
            return None
        if records[0]["request_hash"] != request_hash:
            raise StorageUnavailable("Message payload differs from the completed action.")
        return records[0]["reply"]

    def complete(self, message, member_code, task, request_hash, semester):
        return self._execute(lambda client: client.rpc("complete_task_from_message", {
            "p_platform": message.platform, "p_message_id": message.message_id,
            "p_sender_id": message.sender_id, "p_member_code": member_code,
            "p_request_hash": request_hash, "p_task_id": task["id"],
            "p_expected_updated_at": task["updated_at"],
            "p_expected_assignee_text": task["assignee_text"], "p_semester_code": semester,
        }))
