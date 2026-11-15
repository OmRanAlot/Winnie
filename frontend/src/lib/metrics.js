// Derived only from stored tasks, recorded attendance, and actual reassignment history.
export function memberMetrics(code, tasks, meetings, requests) {
  const owned = tasks.filter(t => t.assignee === code || (t.assignees || []).includes(code));
  const done = owned.filter(t => t.status === 'Completed');
  const timed = done.filter(t => t.completedAt && t.dueIso);
  const nyDate = value => {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York',
      year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(value));
    const byType = Object.fromEntries(parts.map(p => [p.type, p.value]));
    return `${byType.year}-${byType.month}-${byType.day}`;
  };
  const onTime = timed.filter(t => nyDate(t.completedAt) <= t.dueIso).length;
  const recorded = meetings.filter(m => m.attendance_recorded_at);
  const attended = recorded.filter(m => (m.attendees || []).includes(code)).length;
  const transfers = requests.filter(r => r.status === 'approved' && (r.previous_owner_code || r.requester_code) === code).length;
  const rate = (n, d) => d ? Math.round(n * 100 / d) : null;
  return { total: owned.length, completed: done.length, completion: rate(done.length, owned.length),
    onTime: rate(onTime, timed.length), timedCompletions: timed.length,
    attendance: rate(attended, recorded.length), attended, recordedMeetings: recorded.length, transfers };
}
