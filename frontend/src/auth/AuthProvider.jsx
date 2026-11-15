// Owns the session and server-verified profile; Auth callbacks never call Supabase asynchronously.
import { createContext, useContext, useEffect, useRef, useState } from 'react';
import { supabase } from '../lib/supabase.js';
import { setTokenProvider } from '../lib/authToken.js';
import { getCurrentUser } from '../lib/api.js';
import { callbackState } from './authFlow.js';
const initial = callbackState(window.location);
const AuthContext = createContext(null);
export const ACCOUNT_TIMEOUT_MS = 10000;
const ACCOUNT_TIMEOUT_MESSAGE = 'Loading your account took too long. Check your connection and try again.';

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(Boolean(supabase));
  const [error, setError] = useState('');
  const [linkError, setLinkError] = useState(initial.error);
  const [linkFailed, setLinkFailed] = useState(Boolean(initial.error));
  const [passwordMode, setPasswordMode] = useState(initial.passwordMode);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const activeUser = useRef(null);
  const sessionRef = useRef(null);
  useEffect(() => {
    if (!supabase) return;
    let disposed = false;
    setLoading(true);
    setError('');
    // Auth events already supply the current token, including token refreshes.
    // Calling getSession again can wait on the SDK's auth lock before fetch starts.
    setTokenProvider(async () => sessionRef.current?.access_token || null);
    const timer = setTimeout(() => {
      if (!disposed) { setError(ACCOUNT_TIMEOUT_MESSAGE); setLoading(false); }
    }, ACCOUNT_TIMEOUT_MS);
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, next) => {
      if (disposed) return;
      clearTimeout(timer);
      sessionRef.current = next;
      if (next && next.user.id !== activeUser.current) { setLoading(true); setProfile(null); }
      activeUser.current = next?.user.id || null;
      setSession(next);
      if (event === 'PASSWORD_RECOVERY') setPasswordMode(true);
      if (!next) { setProfile(null); setError(''); setLoading(false); }
    });
    return () => {
      disposed = true;
      clearTimeout(timer);
      subscription.unsubscribe();
      setTokenProvider(async () => null);
    };
  }, [revision]);
  useEffect(() => {
    const current = ++generation.current;
    if (!session) return;
    if (!profile || profile.id !== session.user.id) { setProfile(null); setLoading(true); }
    setError('');
    const controller = new AbortController();
    // Bound the whole operation even if a transport ignores AbortSignal.
    const timer = setTimeout(() => {
      controller.abort();
      if (current === generation.current) {
        setProfile(null); setError(ACCOUNT_TIMEOUT_MESSAGE); setLoading(false);
      }
    }, ACCOUNT_TIMEOUT_MS);
    getCurrentUser(controller.signal).then(value => {
      if (!controller.signal.aborted && current === generation.current) setProfile(value);
    }).catch(cause => {
      if (!controller.signal.aborted && current === generation.current) { setProfile(null); setError(cause.message); }
    }).finally(() => {
      clearTimeout(timer);
      if (!controller.signal.aborted && current === generation.current) setLoading(false);
    });
    return () => { clearTimeout(timer); controller.abort(); };
  }, [session?.access_token, revision]);
  async function signOut() {
    const { error: signOutError } = await supabase.auth.signOut();
    if (signOutError) throw signOutError;
    setProfile(null); setPasswordMode(false);
    window.history.replaceState(null, '', '/');
  }
  async function finishPassword(password) {
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) throw updateError;
    await signOut();
    setLinkError('Password saved. Sign in with your email and new password.');
  }
  async function dismissLinkError() {
    if (session) await signOut();
    setLinkFailed(false); setPasswordMode(false); setLinkError('');
    window.history.replaceState(null, '', '/');
  }
  return <AuthContext.Provider value={{ session, profile, loading, error, linkError,
    passwordMode, linkFailed, dismissLinkError, signOut, finishPassword, retry: () => setRevision(n => n + 1) }}>
    {children}
  </AuthContext.Provider>;
}
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider');
  return context;
}
