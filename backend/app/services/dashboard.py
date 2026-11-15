"""Persist dashboard forms through the server-only Supabase client."""

from datetime import UTC, datetime

from app.services.members import MemberStore


class DashboardNotFound(Exception):
    pass


class DashboardStore(MemberStore):
    def member(self, code):
        if not self._execute("members", lambda q: q.select("code").eq("code", code)).data:
            raise DashboardNotFound

    def evaluation(self, code):
        self.member(code)
        rows = self._execute("member_evaluations", lambda q: q.select(
            "member_code,comments,updated_at"
        ).eq("member_code", code)).data
        return rows[0] if rows else {"member_code": code, "comments": "", "updated_at": None}

    def save_evaluation(self, code, comments, reviewer):
        self.member(code)
        return self._execute("member_evaluations", lambda q: q.upsert({
            "member_code": code, "comments": comments, "reviewer_id": reviewer,
            "updated_at": datetime.now(UTC).isoformat(),
        }, on_conflict="member_code")).data[0]

    def draft(self, profile_id):
        rows = self._execute("dashboard_task_drafts", lambda q: q.select("form").eq(
            "profile_id", profile_id
        )).data
        return rows[0]["form"] if rows else None

    def save_draft(self, profile_id, form):
        return self._execute("dashboard_task_drafts", lambda q: q.upsert({
            "profile_id": profile_id, "form": form, "updated_at": datetime.now(UTC).isoformat(),
        }, on_conflict="profile_id")).data[0]["form"]

    def dependencies(self):
        rows, offset = [], 0
        while True:
            page = self._execute("task_dependencies", lambda q, offset=offset: q.select(
                "task_id,depends_on_id"
            ).order("task_id").order("depends_on_id").range(offset, offset + 499)).data
            rows.extend(page)
            if len(page) < 500:
                return rows
            offset += 500
