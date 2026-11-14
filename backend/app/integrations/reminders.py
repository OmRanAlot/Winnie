"""Supabase adapter for durable queueing, claims, cancellation and delivery results."""

from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable, create_task_client


class ReminderStore:
    def __init__(self, client_factory=create_task_client):
        self.client_factory = client_factory

    def _execute(self, operation):
        client = None
        try:
            client = self.client_factory()
            return operation(client).execute().data
        except (HTTPError, APIError) as exc:
            raise StorageUnavailable("Reminder storage is unavailable.") from exc
        finally:
            if client is not None:
                client.postgrest.session.close()

    def recipients(self):
        rows, offset = [], 0
        while True:
            page = self._execute(lambda client, offset=offset: client.table(
                "member_identities"
            ).select("platform,sender_id,member_code").eq("platform", "imessage").eq(
                "reminders_enabled", True
            ).order("member_code").range(offset, offset + 499))
            rows.extend(page)
            if len(page) < 500:
                return rows
            offset += 500

    def queue(self, task, recipient, slot, body, transport, now):
        return self._execute(lambda client: client.rpc("queue_deadline_reminder", {
            "p_task_id": task["id"], "p_member_code": recipient["member_code"],
            "p_due_date": task["due_date"], "p_kind": slot["kind"], "p_transport": transport,
            "p_scheduled_at": slot["scheduled_at"], "p_expires_at": slot["expires_at"],
            "p_sender_id": recipient["sender_id"], "p_assignee_snapshot": task["assignee_text"],
            "p_body": body, "p_now": now.isoformat(),
        }))

    def claim(self, transport, now):
        return self._execute(lambda client: client.rpc("claim_deadline_reminder", {
            "p_transport": transport, "p_now": now.isoformat(),
        }))

    def begin(self, delivery_id, token, now, authorized):
        return self._execute(lambda client: client.rpc("begin_deadline_reminder", {
            "p_id": delivery_id, "p_token": token, "p_now": now.isoformat(),
            "p_assignment_verified": authorized,
        }))

    def finish(self, delivery_id, token, outcome, provider_id, now):
        return self._execute(lambda client: client.rpc("finish_deadline_reminder", {
            "p_id": delivery_id, "p_token": token, "p_outcome": outcome,
            "p_provider_id": provider_id, "p_now": now.isoformat(),
        }))

    def statuses(self):
        # Counts only: never print contact handles or message contents to the terminal.
        return {status: self._count(status) for status in (
            "pending", "claimed", "sending", "sent", "mock_sent", "cancelled", "uncertain", "failed",
        )}

    def _count(self, status):
        client = self.client_factory()
        try:
            return client.table("reminder_deliveries").select(
                "id", count="exact", head=True,
            ).eq("status", status).execute().count
        except (HTTPError, APIError) as exc:
            raise StorageUnavailable("Reminder storage is unavailable.") from exc
        finally:
            client.postgrest.session.close()
