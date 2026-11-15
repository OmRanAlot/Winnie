// The database derives identity and checks approval rights inside these RPCs.
export function reassignmentStore(client, { notify = async () => {} } = {}) {
  async function result(query) {
    const { data, error } = await query;
    if (error) throw new Error(error.message);
    return data;
  }
  async function commit(query) {
    const data = await result(query);
    try { await notify(); }
    catch { return { ...data, notification_warning: 'Saved. Text notifications could not be queued; the request is available in Requests.' }; }
    return data;
  }
  return {
    async list() {
      const rows = [];
      for (let offset = 0; ; offset += 100) {
        const page = await result(client.from('task_reassignment_requests').select('*')
          .order('created_at', { ascending: false }).order('id')
          .abortSignal(AbortSignal.timeout(15000)).range(offset, offset + 99));
        rows.push(...page);
        if (page.length < 100) return rows;
      }
    },
    submit(taskId, proposedCode, reason = '') {
      return commit(client.rpc('submit_task_reassignment', {
        p_task_id: taskId, p_proposed_assignee_code: proposedCode, p_reason: reason,
      }));
    },
    review(requestId, decision, note = '') {
      if (!['approved', 'rejected'].includes(decision)) throw new Error('Invalid decision');
      return commit(client.rpc('review_task_reassignment', {
        p_request_id: requestId, p_decision: decision, p_review_note: note,
      }));
    },
    respond(requestId, decision) {
      if (!['accepted', 'denied'].includes(decision)) throw new Error('Invalid response');
      return commit(client.rpc('respond_task_reassignment', {
        p_request_id: requestId, p_decision: decision,
      }));
    },
    archive(requestId, archived = true) {
      return result(client.rpc('archive_task_reassignment', {
        p_request_id: requestId, p_archive: archived,
      }));
    },
  };
}
