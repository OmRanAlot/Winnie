// The single authentication entry point for the current dashboard design.
import App from '../App.jsx';
import { AuthProvider, useAuth } from './AuthProvider.jsx';
import AuthGate from './AuthGate.jsx';

function Dashboard() {
  const { profile, signOut } = useAuth();
  return <App key={profile.id} profile={profile} admin={profile.is_admin === true} signOut={signOut} />;
}

export default function SessionGate() {
  return <AuthProvider><AuthGate><Dashboard /></AuthGate></AuthProvider>;
}
