// The design's landing and login pages, signing in with the real Supabase email/password account.
// Shown by SessionGate when there is no session. Accounts are created by an admin in Supabase.
import { useState, type FormEvent } from 'react';
import { supabase } from '../lib/supabase';
import { Shell } from './Shell';

type Page = 'landing' | 'login' | 'reset';

export default function Login() {
    const [page, setPage] = useState<Page>('landing');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [pending, setPending] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');

    const go = (next: Page) => { setError(''); setNotice(''); setPage(next); };

    async function run(action: () => Promise<{ error: { message: string } | null }>, done?: string) {
        if (pending) return;
        setPending(true);
        setError('');
        setNotice('');
        try {
            const { error: authError } = await action();
            if (authError) setError(authError.message);
            else if (done) setNotice(done);
        } catch {
            setError('Could not reach the login service. Please try again.');
        } finally {
            setPending(false);
        }
    }

    function signIn(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        run(() => supabase.auth.signInWithPassword({ email: email.trim(), password }));
    }

    function reset(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        run(() => supabase.auth.resetPasswordForEmail(email.trim(), { redirectTo: window.location.origin }),
            'If that email has an account, a reset link is on its way.');
    }

    const messages = <>
        {error && <p role="alert" style={{ margin: 0 }}>{error}</p>}
        {notice && <p role="status" style={{ margin: 0 }}>{notice}</p>}
    </>;
    const emailField = <>
        <label htmlFor="email">Email:</label>
        <input id="email" type="email" className="field" autoComplete="username" required
            value={email} onChange={event => setEmail(event.target.value)} />
    </>;

    if (page === 'landing') {
        return <Shell><div className="center">
            <img className="logo" src="/wics-logo.png" alt="WiCS logo"
                onError={event => { event.currentTarget.style.display = 'none'; }} />
            <h2>Ask Winnie!</h2>
            <button className="btn" style={{ width: 260, fontSize: 24 }} onClick={() => go('login')}>Login</button>
            <p style={{ margin: 0 }}>No account yet? Ask the President or an admin to add you.</p>
        </div></Shell>;
    }

    if (page === 'reset') {
        return <Shell><form className="center" onSubmit={reset}>
            <h2>Reset Password:</h2>
            <fieldset disabled={pending} style={{ border: 0, padding: 0, margin: 0 }}>
                <div className="form">{emailField}</div>
            </fieldset>
            <button className="btn" type="submit" disabled={pending}>{pending ? 'Sending…' : 'Send reset link'}</button>
            {messages}
            <button className="link" type="button" onClick={() => go('login')}>Back to Login</button>
        </form></Shell>;
    }

    return <Shell><form className="center" onSubmit={signIn}>
        <h2>Login:</h2>
        <fieldset disabled={pending} style={{ border: 0, padding: 0, margin: 0 }}>
            <div className="form">
                {emailField}
                <label htmlFor="password">Password:</label>
                <input id="password" type="password" className="field" autoComplete="current-password" required
                    value={password} onChange={event => setPassword(event.target.value)} />
            </div>
        </fieldset>
        <button className="btn" type="submit" disabled={pending}>{pending ? 'Signing in…' : 'Submit'}</button>
        {messages}
        <button className="btn out" type="button" onClick={() => go('reset')}>Reset your password</button>
        <button className="link" type="button" onClick={() => go('landing')}>Back to Home</button>
    </form></Shell>;
}
