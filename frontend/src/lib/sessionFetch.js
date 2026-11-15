// PostgREST rejects expired JWTs before executing the query/RPC. Retry only
// that rejection, never generic 401s, network failures, or database errors.
export function createSessionFetch(supabaseUrl, getAuth, fetcher = (...args) => fetch(...args)) {
  const base = new URL(supabaseUrl);
  const recoveries = new Map();

  async function recover(failedToken) {
    const auth = getAuth();
    const current = await auth.getSession();
    if (current.error || !current.data.session) return null;
    const session = current.data.session;
    // A different user must never inherit a request made by the old account.
    let subject;
    try { subject = JSON.parse(atob(failedToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).sub; }
    catch { return null; }
    if (subject !== session.user.id) return null;
    if (session.access_token !== failedToken) return session.access_token;
    const refreshed = await auth.refreshSession();
    if (refreshed.error || refreshed.data.session?.user.id !== subject) return null;
    return refreshed.data.session.access_token;
  }

  return async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : input);
    // Auth uses this same transport: never recurse into refresh on /auth/v1.
    if (url.origin !== base.origin || !url.pathname.startsWith(`${base.pathname.replace(/\/$/, '')}/rest/v1/`)) {
      return fetcher(input, init);
    }
    const request = new Request(input, init);
    const retry = request.clone();
    const response = await fetcher(request);
    if (response.status !== 401 || request.signal.aborted) return response;
    const error = await response.clone().json().catch(() => null);
    if (!['PGRST301', 'PGRST303'].includes(error?.code) || !/^JWT expired$/i.test(error?.message ?? '')) return response;
    const failedToken = request.headers.get('Authorization')?.replace(/^Bearer\s+/i, '');
    if (!failedToken) return response;
    // Concurrent profile/permission/queue requests share one refresh operation.
    if (!recoveries.has(failedToken)) {
      recoveries.set(failedToken, recover(failedToken).catch(() => null).finally(() => { recoveries.delete(failedToken); }));
    }
    const token = await recoveries.get(failedToken);
    if (!token) return response;
    const current = await getAuth().getSession();
    if (!token || current.error || current.data.session?.access_token !== token || request.signal.aborted) return response;
    retry.headers.set('Authorization', `Bearer ${token}`);
    return fetcher(retry); // Exactly one retry; its errors propagate normally.
  };
}
