// Pure URL and screen-selection rules for Auth, also exercised by Node tests.
export function callbackState(location) {
  const hash = new URLSearchParams(location.hash.replace(/^#/, ''));
  const query = new URLSearchParams(location.search);
  const type = hash.get('type') || query.get('type');
  return {
    passwordMode: ['invite', 'recovery'].includes(type) || location.pathname === '/auth/set-password',
    error: hash.get('error_description') || query.get('error_description') ||
      (hash.get('error') || query.get('error') ? 'This email link is invalid or expired.' : ''),
  };
}
export function authScreen({ loading, session, profile, error, passwordMode, linkFailed }) {
  if (linkFailed) return 'link-error';
  if (loading) return 'loading';
  if (error) return 'blocked';
  if (!session) return 'login';
  if (error || !profile) return 'blocked';
  if (passwordMode || !profile.password_setup_complete) return 'password';
  return 'dashboard';
}
export function validatePassword(password, confirmation) {
  if (password.length < 12) return 'Use at least 12 characters.';
  if (password.length > 128) return 'Use no more than 128 characters.';
  if (password !== confirmation) return 'The passwords do not match.';
  return '';
}
