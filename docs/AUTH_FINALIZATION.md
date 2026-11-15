# Finish Supabase authentication

Winnie uses invitation-only Supabase Auth. Passwords stay in Auth, `members` is the
admin-managed roster, and `profiles` is the signed-in person's private profile.
Only active, consenting roster members with confirmed matching emails can open board data.
Board positions do not automatically grant administrator access.

## Hosted setup

The hosted project already has profiles and the 13-member roster. Do not recreate
those tables or rerun the roster bundle to finish authentication. Apply only:

[`20261115020000_finalize_authentication.sql`](../supabase/migrations/20261115020000_finalize_authentication.sql)

Run that file once in Supabase's SQL Editor. It adds a protected password-completion
flag derived from Auth's password hash. Existing password accounts are backfilled.
Invited users remain incomplete until they actually set a password; browser metadata
cannot bypass this. No passwords/hashes are copied into public profiles.

Use `frontend/.env` (already configured in this checkout), or create
`frontend/.env.local` using `frontend/.env.example`, with:

```dotenv
VITE_API_BASE_URL=/api
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY
```

Use the same project as the backend. Get the publishable key from the project's
Connect/API keys panel. Never use a secret/service-role key in a `VITE_` variable.
Restart Vite after editing the environment.

In the hosted **Authentication** settings:

1. Set **Site URL** to `http://localhost:5173`, or the deployed frontend origin.
2. Add the exact redirect `http://localhost:5173/auth/set-password` and the
   corresponding deployed URL before using production invitations. Use one hostname
   consistently; localhost and 127.0.0.1 have separate browser sessions.
3. Disable **Allow new users to sign up**. Keep email confirmation enabled. Admin
   invitations remain the onboarding mechanism. Set minimum password length to 12.
4. Configure custom SMTP for mail to actual board members. Supabase's default mail
   service is restricted to project-team addresses and limited testing. Do not grant
   board members project-admin access to work around email delivery restrictions.
5. Keep invite/recovery templates using Supabase's `{{ .ConfirmationURL }}` link.
   The app supports default implicit-flow invitations and recovery redirects. Do
   not replace the templates with a PKCE flow for admin invitations.

Static hosting must rewrite `/auth/set-password` to the SPA's `index.html`.
Local `supabase/config.toml` matches these local settings but does not modify a
hosted project's settings.

References: [SMTP](https://supabase.com/docs/guides/auth/auth-smtp),
[recovery](https://supabase.com/docs/reference/javascript/auth-resetpasswordforemail),
[invitations](https://supabase.com/docs/reference/python/auth-admin-inviteuserbyemail).

## Invite a member

Only use email addresses actually provided in the consented roster. Invite manually
through **Authentication → Users → Invite user**, or preview a roster-checked invite
from `backend/`:

```powershell
uv run python -m app.cli.invite_member member@example.com
```

This checks consent, membership and schema without sending mail. When ready to send:

```powershell
uv run python -m app.cli.invite_member member@example.com --send
```

Invitations default to `https://hack-princeton-514716.web.app/auth/set-password`.
Add that exact URL to Supabase Authentication → URL Configuration → Redirect URLs.
For local testing, explicitly pass `--redirect-to http://localhost:5173/auth/set-password`.
Previously sent emails keep their original link; send a fresh invitation to use the corrected callback.
That callback must be allowlisted. No bulk invitations are sent automatically.
Existing accounts use **Forgot your password?** instead of being recreated.

The recipient follows the link, sees their fixed email, chooses and confirms a
password, and is signed out for a fresh login. The dashboard displays their roster
identity and predetermined role. Their own profile shows graduation information,
major, phone, GirlHacks title and supplied skills. Missing contact details remain blank.

Expired links show an error; they do not reuse a cached session to change a different
account's password. Missing/inactive roster links show a retry/sign-out screen.

## Administrator assignment

Assign website administrator status only through trusted backend/database access for
the reviewed Auth UUID, for example in SQL Editor:

```sql
update public.profiles set is_admin = true
where id = 'REPLACE_WITH_REVIEWED_AUTH_USER_UUID'::uuid;
```

Ordinary users cannot change this field, their role, member link, email, or password
completion flag. Neither names nor editable Auth metadata confer privileges. Website
administration is separate from messaging approval identities.

## API access

Browser requests send `Authorization: Bearer <access_token>`. FastAPI verifies the
token with Auth, then checks the linked profile, active roster record, contact consent,
and exact email match. `/api/auth/me` returns only the caller's private profile.
There is no development authentication bypass.

Tasks, members, recordings, meeting ingestion, and planning require approved membership
and completed password setup. Task creation/deletion, help approvals, and planning
review require an administrator. Members retain shared task visibility and status edits.

Existing trusted integrations may use their scoped task/help/review keys. Browser
code no longer asks operators for those keys. Internal messaging/bridge endpoints
retain separate bridge authentication. Health/CORS preflight remain public. Invalid
Bearer tokens never fall back to a shared key. Demo Auth accounts without a consenting
roster link cannot open the board.

## Verify

From `backend/`, run the read-only readiness report:

```powershell
uv run python -m app.cli.check_auth_setup
```

It reports configuration/schema readiness and eligible-member counts without exposing
keys, passwords, tokens, or contacts. SMTP/redirect settings must be checked in the
dashboard; database credentials cannot read the management configuration.

Run these checks from the repository root:

```powershell
npm --prefix frontend run build
npm --prefix frontend test
npm --prefix frontend run test:auth
npm run test:profiles
node --test supabase/tests/schema-chain.test.mjs
```

Run `uv run pytest` from `backend/`. HTTP tests exercise the real auth dependencies
with mocked provider IO; React tests cover login, restored sessions, password setup,
recovery, access denial and sign-out. SQL tests run the real migrations in PGlite.

Finally, test with one consenting member's real inbox: invitation delivery, password
setup, fresh login, predetermined profile, logout, and password recovery. Offline
tests cannot prove hosted SMTP delivery or redirect settings. No invitation emails
were sent as part of implementing this flow.
