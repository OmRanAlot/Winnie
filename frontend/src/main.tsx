// Mounts the recorder behind the login screen.
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { AuthProvider, useAuth } from './auth/AuthProvider';
import Login from './auth/Login';
import './styles.css';

function AuthGate() {
  const { session, loading } = useAuth();

  if (loading) return <p role="status">Loading your session…</p>;
  if (!session) return <Login />;

  return <App />;
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  </React.StrictMode>,
);