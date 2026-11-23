// Render the real auth components; only Supabase network/session IO is mocked.
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const sdk = vi.hoisted(() => ({
  session: null, listener: null, signIn: vi.fn(), reset: vi.fn(), update: vi.fn(),
  signOut: vi.fn(), unsubscribe: vi.fn(), getProfile: vi.fn(), getSession: vi.fn(), emitInitial: true,
}));
vi.mock('../src/lib/supabase.js', () => ({ authConfigured: true, supabase: { auth: {
  signInWithPassword: sdk.signIn, resetPasswordForEmail: sdk.reset, updateUser: sdk.update,
  signOut: sdk.signOut,
  getSession: sdk.getSession,
  onAuthStateChange: callback => {
    sdk.listener = callback;
    if (sdk.emitInitial) queueMicrotask(() => callback('INITIAL_SESSION', sdk.session));
    return { data: { subscription: { unsubscribe: sdk.unsubscribe } } };
  },
} } }));
vi.mock('../src/lib/api.js', () => ({ getCurrentUser: sdk.getProfile }));
vi.mock('../src/auth/Shell.tsx', () => ({ Shell: ({ children }) => <main>{children}</main> }));

import { ACCOUNT_TIMEOUT_MS, AuthProvider } from '../src/auth/AuthProvider.jsx';
import AuthGate from '../src/auth/AuthGate.jsx';
import { authHeaders } from '../src/lib/authToken.js';

const session = { access_token: 'synthetic', user: { id: 'alice' } };
const profile = { id: 'alice', email: 'alice@example.com', password_setup_complete: true };
function mount() { return render(<AuthProvider><AuthGate><p>Board dashboard</p></AuthGate></AuthProvider>); }
async function openLogin() {
  fireEvent.click(await screen.findByRole('button', { name: 'Login' }));
  return screen.findByLabelText('Email:');
}
function event(type, value) { sdk.session = value; sdk.listener(type, value); }

beforeEach(() => {
  vi.clearAllMocks(); sdk.session = null; sdk.emitInitial = true;
  sdk.getSession.mockImplementation(() => new Promise(() => {}));
  sdk.getProfile.mockResolvedValue(profile);
  sdk.signIn.mockResolvedValue({ error: null });
  sdk.reset.mockResolvedValue({ error: null });
  sdk.update.mockResolvedValue({ error: null });
  sdk.signOut.mockImplementation(async () => { event('SIGNED_OUT', null); return { error: null }; });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('authentication screens', () => {
  it('uses auth-event tokens without waiting on getSession and updates them on refresh', async () => {
    sdk.session = session;
    mount();
    await screen.findByText('Board dashboard');
    expect(await authHeaders()).toEqual({ Authorization: 'Bearer synthetic' });
    await act(async () => event('TOKEN_REFRESHED', { ...session, access_token: 'new-token' }));
    expect(await authHeaders()).toEqual({ Authorization: 'Bearer new-token' });
    expect(sdk.getProfile).toHaveBeenCalledTimes(1);
    expect(sdk.getSession).not.toHaveBeenCalled();
    await act(async () => event('SIGNED_OUT', null));
    expect(await authHeaders()).toEqual({});
  });

  it('times out a missing initial session event and can retry session initialization', async () => {
    vi.useFakeTimers();
    sdk.emitInitial = false;
    mount();
    await act(async () => vi.advanceTimersByTimeAsync(ACCOUNT_TIMEOUT_MS));
    expect(screen.getByRole('alert').textContent).toContain('took too long');
    expect(screen.queryByRole('status')).toBeNull();
    sdk.emitInitial = true;
    sdk.session = session;
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Try again' })));
    expect(screen.getByText('Board dashboard')).toBeTruthy();
  });

  it('bounds a hung profile request, ignores its late response, and retries', async () => {
    vi.useFakeTimers();
    sdk.session = session;
    let finish;
    sdk.getProfile.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    mount();
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(ACCOUNT_TIMEOUT_MS));
    expect(screen.getByRole('alert').textContent).toContain('took too long');
    expect(sdk.getProfile.mock.calls[0][0].aborted).toBe(true);
    await act(async () => finish(profile));
    expect(screen.queryByText('Board dashboard')).toBeNull();
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Try again' })));
    expect(screen.getByText('Board dashboard')).toBeTruthy();
  });

  it('does not restore a private screen from a profile response after sign-out', async () => {
    sdk.session = session;
    let finish;
    sdk.getProfile.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    mount();
    await act(async () => {});
    await act(async () => event('SIGNED_OUT', null));
    await act(async () => finish(profile));
    expect(screen.queryByText('Board dashboard')).toBeNull();
    expect(screen.getByRole('button', { name: 'Login' })).toBeTruthy();
  });

  it('shows login errors and opens the dashboard after a valid session', async () => {
    mount();
    expect(await screen.findByRole('button', { name: 'Login' })).toBeTruthy();
    expect(document.querySelectorAll('.fairy-lights')).toHaveLength(1);
    fireEvent.change(await openLogin(), { target: { value: 'alice@example.com' } });
    expect(document.querySelectorAll('.fairy-lights')).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('Password:'), { target: { value: 'synthetic-password' } });
    sdk.signIn.mockResolvedValueOnce({ error: { message: 'Invalid login credentials' } });
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Invalid login credentials');
    sdk.signIn.mockImplementationOnce(async () => { event('SIGNED_IN', session); return { error: null }; });
    fireEvent.click(screen.getByRole('button', { name: 'Submit' }));
    expect(await screen.findByText('Board dashboard')).toBeTruthy();
    expect(document.querySelectorAll('.fairy-lights')).toHaveLength(0);
  });

  it('restores a saved session and fetches its verified profile', async () => {
    sdk.session = session;
    mount();
    expect(await screen.findByText('Board dashboard')).toBeTruthy();
    expect(sdk.getProfile).toHaveBeenCalledTimes(1);
  });

  it('sends password reset mail to the registered email with the configured callback', async () => {
    mount();
    await openLogin();
    fireEvent.click(screen.getByRole('button', { name: 'Reset your password' }));
    expect(document.querySelectorAll('.fairy-lights')).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('Email:'), { target: { value: 'alice@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }));
    expect(await screen.findByText(/If that email has an account/)).toBeTruthy();
    expect(sdk.reset).toHaveBeenCalledWith('alice@example.com', {
      redirectTo: `${window.location.origin}/auth/set-password`,
    });
  });

  it('requires invited users to set a password, then signs out for a fresh login', async () => {
    sdk.session = session;
    sdk.getProfile.mockResolvedValue({ ...profile, password_setup_complete: false });
    mount();
    fireEvent.change(await screen.findByLabelText('New password'), { target: { value: 'Long-example-password!' } });
    expect(document.querySelectorAll('.fairy-lights')).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'Other-example-password!' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save password and sign in' }));
    expect(await screen.findByText('The passwords do not match.')).toBeTruthy();
    expect(sdk.update).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'Long-example-password!' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save password and sign in' }));
    expect(await screen.findByText('Password saved. Sign in with your email and new password.')).toBeTruthy();
    expect(sdk.update).toHaveBeenCalledWith({ password: 'Long-example-password!' });
    expect(sdk.signOut).toHaveBeenCalledOnce();
    expect(screen.queryByText('Board dashboard')).toBeNull();
  });

  it('keeps recovery sessions on password setup even for an existing account', async () => {
    mount(); await screen.findByRole('button', { name: 'Login' });
    await act(async () => event('PASSWORD_RECOVERY', session));
    expect(await screen.findByLabelText('New password')).toBeTruthy();
    expect(screen.queryByText('Board dashboard')).toBeNull();
  });

  it('blocks unapproved users and lets them sign out', async () => {
    sdk.session = session;
    sdk.getProfile.mockRejectedValue(new Error('Not on the approved roster.'));
    mount();
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Not on the approved roster.');
    expect(document.querySelectorAll('.fairy-lights')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('button', { name: 'Login' })).toBeTruthy();
    expect(screen.queryByText('Board dashboard')).toBeNull();
  });

  it('removes private screens on sign-out and unsubscribes on unmount', async () => {
    sdk.session = session;
    const view = mount(); await screen.findByText('Board dashboard');
    await act(async () => event('SIGNED_OUT', null));
    await waitFor(() => expect(screen.queryByText('Board dashboard')).toBeNull());
    expect(await screen.findByRole('button', { name: 'Login' })).toBeTruthy();
    view.unmount(); expect(sdk.unsubscribe).toHaveBeenCalled();
  });
});
