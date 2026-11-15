"""Private shared proposal storage; SQL commits approval, tasks and notices atomically."""
from fastapi import HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable
from app.services.members import MemberStore


class EventPlanStore(MemberStore):
    def call(self, actor, action, plan_id=None, revision=None, payload=None):
        client = self.client_factory()
        try:
            return client.rpc("manage_event_plan", {
                "p_actor": actor, "p_action": action, "p_id": str(plan_id) if plan_id else None,
                "p_revision": revision, "p_payload": payload or {},
            }).execute().data
        except APIError as exc:
            messages = {
                "42501": (403, "An active administrator account is required."),
                "P0002": (404, "Event plan not found."),
                "40001": (409, "Event plan changed or was already decided. Reopen it before continuing."),
                "22023": (422, "Approval requires valid tasks, active owners, dates and dependencies."),
            }
            if exc.code in messages:
                status, detail = messages[exc.code]
                raise HTTPException(status, detail) from None
            raise StorageUnavailable("Event plan storage is unavailable.") from exc
        except HTTPError as exc:
            raise StorageUnavailable("Event plan storage is unavailable.") from exc
        finally:
            client.postgrest.session.close()
