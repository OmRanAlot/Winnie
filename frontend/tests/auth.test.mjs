// Pure auth flow and credential propagation tests; no actual accounts or emails.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { callbackState, authScreen, validatePassword } from '../src/auth/authFlow.js';
import { setTokenProvider } from '../src/lib/authToken.js';
import { getCurrentUser } from '../src/lib/api.js';

test('invitation and recovery URLs open password setup; expired links surface errors', () => {
  assert.equal(callbackState({ pathname: '/', search: '', hash: '#type=invite&access_token=synthetic' }).passwordMode, true);
  assert.equal(callbackState({ pathname: '/', search: '', hash: '#type=recovery' }).passwordMode, true);
  assert.equal(callbackState({ pathname: '/auth/set-password', search: '', hash: '' }).passwordMode, true);
  assert.equal(callbackState({ pathname: '/', search: '', hash: '#error=access_denied&error_description=Link+expired' }).error, 'Link expired');
});

test('password and profile gates cannot be bypassed just by having an Auth session', () => {
  const state = { loading: false, session: { user: { id: 'alice' } }, profile: null, error: '', passwordMode: false };
  assert.equal(authScreen({ ...state, loading: true }), 'loading');
  assert.equal(authScreen({ ...state, profile: { password_setup_complete: true }, linkFailed: true }), 'link-error');
  assert.equal(authScreen({ ...state, session: null }), 'login');
  assert.equal(authScreen(state), 'blocked');
  assert.equal(authScreen({ ...state, profile: { password_setup_complete: false } }), 'password');
  assert.equal(authScreen({ ...state, profile: { password_setup_complete: true }, passwordMode: true }), 'password');
  assert.equal(authScreen({ ...state, profile: { password_setup_complete: true } }), 'dashboard');
});

test('password form rejects short or mismatched passwords', () => {
  assert.ok(validatePassword('short', 'short'));
  assert.ok(validatePassword('Long-enough-example!', 'different'));
  assert.equal(validatePassword('Long-enough-example!', 'Long-enough-example!'), '');
});

test('API requests retrieve a fresh access token without exposing a shared backend key', async () => {
  const original = globalThis.fetch;
  const calls = [];
  let token = 'first-token';
  setTokenProvider(async () => token);
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, json: async () => ({ success: true, data: { name: 'Alice' } }) };
  };
  try {
    await getCurrentUser(); token = 'refreshed-token'; await getCurrentUser();
    assert.equal(calls[0].options.headers.Authorization, 'Bearer first-token');
    assert.equal(calls[1].options.headers.Authorization, 'Bearer refreshed-token');
    assert.equal(calls[1].options.headers['X-Winnie-Api-Key'], undefined);
  } finally { globalThis.fetch = original; setTokenProvider(async () => null); }
});
