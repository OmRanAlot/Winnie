// Invitation-only login, password recovery, and approved-profile gate for the dashboard.
import { useState } from 'react';
import { authConfigured } from '../lib/supabase.js';
import Login from './Login.tsx';
import { useAuth } from './AuthProvider.jsx';
import { authScreen, validatePassword } from './authFlow.js';
import './auth.css';

function SetPassword() {
  const { profile, finishPassword, signOut } = useAuth();
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const validation = validatePassword(password, confirmation);
    if (validation) { setError(validation); return; }
    setBusy(true); setError('');
    try { await finishPassword(password); }
    catch (cause) { setError(cause.message || 'Could not save your password. Try a new email link.'); }
    finally { setBusy(false); }
  }
  return <>
    <h1>Set your password</h1><p>{profile.email}</p>
    <form onSubmit={submit}><fieldset disabled={busy}>
      <label htmlFor="new-password">New password</label>
      <input id="new-password" type="password" autoComplete="new-password" minLength={12} maxLength={128}
        required value={password} onChange={e => setPassword(e.target.value)} />
      <label htmlFor="confirm-password">Confirm password</label>
      <input id="confirm-password" type="password" autoComplete="new-password" minLength={12} maxLength={128}
        required value={confirmation} onChange={e => setConfirmation(e.target.value)} />
      <p className="auth-small">Use at least 12 characters.</p>
      <button type="submit">{busy ? 'Saving…' : 'Save password and sign in'}</button>
    </fieldset>{error && <p className="auth-error" role="alert">{error}</p>}</form>
    <button className="auth-link" disabled={busy} onClick={() => signOut().catch(e => setError(e.message))}>Cancel and sign out</button>
  </>;
}

export default function AuthGate({ children }) {
  const auth = useAuth();
  const [actionError, setActionError] = useState('');
  const screen = authScreen(auth);
  if (authConfigured && screen === 'dashboard') return children;
  if (authConfigured && screen === 'login') return <Login sessionNotice={auth.linkError} />;
  let content;
  if (!authConfigured) content = <><h1>Connect Winnie</h1><p>Login is not configured. Add the Supabase URL and publishable key to the frontend environment, then restart the app.</p></>;
  else if (screen === 'link-error') content = <><h1>This email link could not be used</h1>
    <p role="alert">{auth.linkError}</p><p>Ask your administrator for a new invitation, or request another password reset link.</p>
    <button onClick={() => auth.dismissLinkError().catch(e => setActionError(e.message))}>Back to sign in</button>
    {actionError && <p role="alert">{actionError}</p>}</>;
  else if (screen === 'loading') content = <p role="status">Loading your account…</p>;
  else if (screen === 'password') content = <SetPassword />;
  else content = <><h1>Account access</h1><p role="alert">{auth.error || 'Your account is not linked to the board roster.'}</p>
    <button onClick={auth.retry}>Try again</button>
    <button className="auth-link" onClick={() => auth.signOut().catch(e => setActionError(e.message))}>Sign out</button>
    {actionError && <p role="alert">{actionError}</p>}</>;
  return <main className="auth-shell"><section className="auth-card">
    <img src="/wics-logo.png" alt="WiCS" width="80" height="80" />{content}
  </section></main>;
}
