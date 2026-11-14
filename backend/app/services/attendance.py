"""Meeting history and atomic attendance writes for the meetings routes."""

from app.services.members import MemberStore


class AttendanceStore(MemberStore):
    def list_meetings(self):
        meetings, offset = [], 0
        while True:
            page = self._execute("meetings", lambda q, offset=offset: q.select(
                "id,title,held_at,summary,transcript,attendance_recorded_at,"
                "meeting_attendance(member_code)"
            ).order("held_at", desc=True).order("id", desc=True).range(offset, offset + 499)).data
            for row in page:
                row["attendees"] = [a["member_code"] for a in row.pop("meeting_attendance", [])]
            meetings.extend(page)
            if len(page) < 500:
                return meetings
            offset += 500

    def create(self, title, held_at):
        return self._execute("meetings", lambda q: q.insert({
            "title": title, "held_at": held_at.isoformat(),
        })).data[0]

    def save(self, meeting_id, attendees):
        client = self.client_factory()
        try:
            client.rpc("save_meeting_attendance", {
                "meeting": meeting_id, "attendees": attendees,
            }).execute()
        finally:
            client.postgrest.session.close()
