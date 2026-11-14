// Inject the browser token getter so API helpers also work in Node tests.
let tokenProvider = async () => null;
export function setTokenProvider(provider) { tokenProvider = provider; }
export async function authHeaders() {
  const token = await tokenProvider();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
