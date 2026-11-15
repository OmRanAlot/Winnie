// Shared proposals are stored on the server; local browser plans are never auto-imported.
import { request, dispatchPhotonNotifications } from './api.js';
export const flattenPlan = row => ({ ...row.payload, ...row });
export async function getEventPlans() {
  return (await request('/event-plans')).data.map(flattenPlan);
}
export async function getEventPlan(id) {
  return flattenPlan((await request(`/event-plans/${encodeURIComponent(id)}`)).data);
}
export async function createEventPlan(plan) {
  return flattenPlan((await request('/event-plans', { method: 'POST', body: JSON.stringify(plan) })).data);
}
export async function updateEventPlan(id, plan, expectedRevision) {
  return flattenPlan((await request(`/event-plans/${encodeURIComponent(id)}`, {
    method: 'PUT', body: JSON.stringify({ ...plan, expected_revision: expectedRevision }),
  })).data);
}
export async function reviewEventPlan(id, expectedRevision, decision) {
  const saved = flattenPlan((await request(`/event-plans/${encodeURIComponent(id)}/review`, {
    method: 'POST', body: JSON.stringify({ expected_revision: expectedRevision, decision }),
  })).data);
  if (decision === 'approved') {
    try {
      const result = await dispatchPhotonNotifications();
      if (!result.queued) saved.notification_warning = 'Tasks created. Text delivery is not enabled.';
    } catch { saved.notification_warning = 'Tasks created. Text dispatch failed; retry notifications from Requests.'; }
  }
  return saved;
}
