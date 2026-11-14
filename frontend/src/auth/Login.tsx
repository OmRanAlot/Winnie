// Email/password login form, displayed when there is no session.
import { useState, type FormEvent } from 'react';
import { supabase } from '../lib/supabase';

export default function Login() {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [pending, setPending] = useState(false);
    const [error, setError] = useState('');

    async function handleSubmit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        if (pending) return;

        setPending(true);
        setError('');

        try {
            const { error: loginError } =
                await supabase.auth.signInWithPassword({
                    email: email.trim(),
                    password,
                });

            if (loginError) {
                setError(loginError.message);
            }
        } catch {
            setError('Could not reach the login service. Please try again.');
        } finally {
            setPending(false);
        }
    }

    return (
        <main>
            <h1>Sign in to Winnie</h1>
            <p>Use your board account to continue.</p>

            <form onSubmit={handleSubmit}>
                <fieldset disabled={pending}>
                    <legend>Account details</legend>

                    <label htmlFor="email">Email</label>
                    <input
                        id="email"
                        name="email"
                        type="email"
                        autoComplete="username"
                        value={email}
                        onChange={event => setEmail(event.target.value)}
                        required
                    />

                    <label htmlFor="password">Password</label>
                    <input
                        id="password"
                        name="password"
                        type="password"
                        autoComplete="current-password"
                        value={password}
                        onChange={event => setPassword(event.target.value)}
                        required
                    />

                    <button type="submit">
                        {pending ? 'Signing in…' : 'Sign in'}
                    </button>
                </fieldset>

                {error && <p role="alert">{error}</p>}
            </form>
        </main>
    );
}