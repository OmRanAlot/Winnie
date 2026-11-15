"""Leased scheduled scans and private status; no polling process inside the API."""
from fastapi import HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.integrations.supabase import StorageUnavailable
from app.services.members import MemberStore


class AutomationStore(MemberStore):
    def rpc(self, name, **values):
        client = self.client_factory()
        try:
            return client.rpc(name, values).execute().data
        except APIError as exc:
            errors = {'42501': (403, 'Administrator access is required.'),
                      'P0002': (404, 'Task not found.'),
                      '22023': (422, 'Choose an unfinished task with an opted-in, linked assignee in the active semester.')}
            if exc.code in errors:
                status, detail = errors[exc.code]
                raise HTTPException(status, detail) from None
            raise StorageUnavailable('Automation storage is unavailable. Check migrations.') from exc
        except HTTPError as exc:
            raise StorageUnavailable('Automation storage is unavailable.') from exc
        finally:
            client.postgrest.session.close()

    def claim(self, key):
        return self.rpc('claim_automation_job', p_key=key)

    def finish(self, key, token, status, summary):
        return self.rpc('finish_automation_job', p_key=key, p_token=token, p_status=status, p_summary=summary)

    def status(self):
        jobs = self._execute('automation_jobs', lambda q: q.select(
            'key,status,started_at,finished_at,summary').order('key')).data
        counts = {}
        for table in ('task_notifications', 'reminder_deliveries', 'event_plan_notifications', 'reassignment_notifications'):
            client = self.client_factory()
            try:
                counts[table] = {status: client.table(table).select('id', count='exact', head=True)
                                 .eq('status', status).execute().count
                                 for status in ('pending', 'sending', 'uncertain', 'sent')}
            except (APIError, HTTPError) as exc:
                raise StorageUnavailable('Notification status is unavailable.') from exc
            finally:
                client.postgrest.session.close()
        return {'jobs': jobs, 'notifications': counts}
