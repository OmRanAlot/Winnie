// Shares Supabase's session with components through useAuth().
import {
    createContext,
    useContext,
    useEffect,
    useState,
    type ReactNode,
} from 'react';
import type { Session } from '@supabase/supabase-js';
import { supabase } from '../lib/supabase';

type AuthContextValue = {
    session: Session | null;
    loading: boolean;
    signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
    const [session, setSession] = useState<Session | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const { data: { subscription } } =
            supabase.auth.onAuthStateChange((_event, nextSession) => {
                setSession(nextSession);
                setLoading(false);
            });

        return () => subscription.unsubscribe();
    }, []);

    async function signOut() {
        const { error } = await supabase.auth.signOut();
        if (error) throw error;
    }

    return (
        <AuthContext.Provider value={{ session, loading, signOut }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);

    if (!context) {
        throw new Error('useAuth must be used inside AuthProvider');
    }

    return context;
}