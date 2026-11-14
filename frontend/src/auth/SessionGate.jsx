import { useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import Login from './Login';
import App from '../App';

export default function SessionGate() {
  const [session, setSession] = useState(undefined);
  const [account, setAccount] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    let eventReceived = false;
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      eventReceived = true;
      if (active) setSession(next);
    });
    supabase.auth.getSession().then(({ data, error }) => {
      if (!active || eventReceived) return;
      if (error) setError(error.message);
      setSession(data.session);
    }).catch((e) => { if (active) { setError(e.message); setSession(null); } });
    return () => { active = false; data.subscription.unsubscribe(); };
  }, []);
  useEffect(() => {
    setAccount(null);
    setError('');
    if (!session) return;
    let active = true;
    let loading = false;
    const load = async () => {
      if (loading) return;
      loading = true;
      try {
        const [profile, permission] = await Promise.all([
          supabase.from('profiles').select('id,name,member_code,is_admin,role').eq('id', session.user.id).single(),
          supabase.rpc('can_review_task_requests'),
        ]);
        if (profile.error || permission.error) throw profile.error || permission.error;
        if (active) { setAccount({ profile: profile.data, admin: permission.data === true }); setError(''); }
      } catch (e) {
        if (active) { setAccount(null); setError(e.message); }
      } finally { loading = false; }
    };
    load();
    const timer = setInterval(load, 15000);
    window.addEventListener('focus', load);
    return () => { active = false; clearInterval(timer); window.removeEventListener('focus', load); };
  }, [session?.user.id, retry]);
  const signOut = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) setError(error.message);
  };
  if (session === undefined) return <main>Loading your session…</main>;
  if (!session) return <Login />;
  if (!account) return <main><h1>Winnie</h1>{error ? <>
    <p role="alert">Could not load your account: {error}</p>
    <button onClick={() => setRetry(x => x + 1)}>Retry</button>
    <button onClick={signOut}>Sign out</button>
  </> : <p>Loading your account…</p>}</main>;
  return <App key={session.user.id} profile={account.profile} admin={account.admin} signOut={signOut} />;
}
